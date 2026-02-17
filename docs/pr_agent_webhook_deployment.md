# PR Agent Deployment Options (No GitHub Actions)

Since your system is **webhook-driven** (no GitHub Actions), here are PR Agent deployment options that work with your architecture.

---

## Option 1: PR Agent CLI in Lambda

Deploy PR Agent as a Lambda function that runs the CLI tool.

### Architecture

```
GitHub Webhook → API Gateway → Lambda (PR Agent CLI) → GitHub API
                              ↓
                              (parallel)
                              ↓
                → Lambda (Your webhook receiver) → SQS → Worker Lambda
```

### Implementation

**1. Create PR Agent Lambda Layer:**

```bash
# Build layer
mkdir -p lambda-layer/python
pip install pr-agent -t lambda-layer/python/
cd lambda-layer
zip -r pr-agent-layer.zip python/

# Upload to Lambda Layer
aws lambda publish-layer-version \
  --layer-name pr-agent \
  --zip-file fileb://pr-agent-layer.zip \
  --compatible-runtimes python3.11 python3.12
```

**2. Create Lambda Function:**

```python
# src/pr_agent_lambda/app.py

import json
import os
from pr_agent.cli import run_command
from pr_agent.config_loader import get_settings

def lambda_handler(event, context):
    """Run PR Agent CLI in Lambda."""
    
    # Parse webhook payload
    body = json.loads(event.get('body', '{}'))
    pr_url = (
        f"https://github.com/{body['repository']['full_name']}"
        f"/pull/{body['number']}"
    )
    
    # Configure PR Agent
    get_settings().github.user_token = os.environ['GITHUB_TOKEN']
    get_settings().openai.key = os.environ['OPENAI_API_KEY']
    
    # Run review command
    try:
        run_command(f"--pr_url={pr_url}", "review")
        return {"statusCode": 200, "body": "Review completed"}
    except Exception as e:
        print(f"Error: {e}")
        return {"statusCode": 500, "body": str(e)}
```

**3. Terraform Configuration:**

```terraform
# Add to infra/terraform/main.tf

resource "aws_lambda_layer_version" "pr_agent" {
  count               = var.pr_agent_enabled ? 1 : 0
  filename            = "${path.module}/pr-agent-layer.zip"
  layer_name          = "${local.name_prefix}-pr-agent-layer"
  compatible_runtimes = ["python3.12"]
}

resource "aws_lambda_function" "pr_agent" {
  count            = var.pr_agent_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-pr-agent-reviewer"
  role             = aws_iam_role.pr_agent_lambda[0].arn
  runtime          = "python3.12"
  handler          = "pr_agent_lambda.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 300  # PR Agent can be slow
  memory_size      = 1024
  
  layers = [aws_lambda_layer_version.pr_agent[0].arn]
  
  environment {
    variables = {
      GITHUB_TOKEN      = "get-from-secrets-manager"
      OPENAI_API_KEY    = "get-from-secrets-manager"
      OPENAI_ORG        = var.openai_org_id
    }
  }
}

# Option A: Separate webhook route
resource "aws_apigatewayv2_route" "pr_agent_webhook" {
  count     = var.pr_agent_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/pr-agent"
  target    = "integrations/${aws_apigatewayv2_integration.pr_agent_lambda[0].id}"
}

resource "aws_apigatewayv2_integration" "pr_agent_lambda" {
  count              = var.pr_agent_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.webhook.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.pr_agent[0].invoke_arn
  payload_format_version = "2.0"
}
```

**Pros:**
- ✅ Reuses your existing API Gateway + Lambda architecture
- ✅ No GitHub Actions needed
- ✅ Serverless, scales automatically
- ✅ Familiar deployment pattern

**Cons:**
- ❌ PR Agent CLI not optimized for Lambda (may timeout on large PRs)
- ❌ Layer size can be large (100+ MB)
- ❌ Cold starts (5-10 seconds)
- ❌ PR Agent expects certain file structures

---

## Option 2: PR Agent Docker on ECS/Fargate

Run PR Agent's Docker image as a webhook server on ECS.

### Architecture

```
GitHub Webhook → ALB → ECS (PR Agent container) → GitHub API
```

### Implementation

**1. Use PR Agent's Official Docker Image:**

```yaml
# Add to your existing ECS infrastructure
# infra/terraform/ecs-pr-agent.tf

resource "aws_ecs_task_definition" "pr_agent" {
  family                   = "${local.name_prefix}-pr-agent"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 1024
  memory                   = 2048
  
  container_definitions = jsonencode([{
    name  = "pr-agent"
    image = "codiumai/pr-agent:latest"
    
    portMappings = [{
      containerPort = 3000
      protocol      = "tcp"
    }]
    
    environment = [
      {name = "GITHUB_TOKEN", value = "from-secrets"},
      {name = "OPENAI_API_KEY", value = "from-secrets"},
      {name = "PORT", value = "3000"}
    ]
    
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/pr-agent"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "pr-agent"
      }
    }
  }])
}

resource "aws_ecs_service" "pr_agent" {
  name            = "${local.name_prefix}-pr-agent"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.pr_agent.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.pr_agent.id]
  }
  
  load_balancer {
    target_group_arn = aws_lb_target_group.pr_agent.arn
    container_name   = "pr-agent"
    container_port   = 3000
  }
}
```

**2. Configure Webhook in GitHub:**

```bash
# Add second webhook to GitHub App settings:
# Webhook URL: https://your-alb.us-gov-west-1.elb.amazonaws.com/webhooks/github
# Events: Pull requests
```

**Pros:**
- ✅ Uses official PR Agent Docker image
- ✅ Full PR Agent functionality
- ✅ Can handle large PRs
- ✅ No cold starts
- ✅ Easy updates (just pull latest image)

**Cons:**
- ❌ Always-on cost (ECS task running 24/7)
- ❌ More infrastructure (ECS cluster, ALB, target groups)
- ❌ Slower than Lambda for small PRs

---

## Option 3: PR Agent CLI on EC2 (Simplest)

Run PR Agent webhook server on an EC2 instance.

### Implementation

**1. Launch EC2 Instance:**

```bash
# UserData script
#!/bin/bash
yum update -y
yum install -y python3.11 python3-pip

# Install PR Agent
pip3 install pr-agent

# Create webhook server script
cat > /opt/pr-agent/webhook_server.py << 'EOF'
from flask import Flask, request
import subprocess
import os

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    pr_url = f"https://github.com/{data['repository']['full_name']}/pull/{data['number']}"
    
    # Run PR Agent CLI
    subprocess.Popen([
        'pr-agent',
        '--pr_url', pr_url,
        'review'
    ])
    
    return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
EOF

# Set environment variables
export GITHUB_TOKEN="your-token"
export OPENAI_API_KEY="your-key"

# Run webhook server
python3 /opt/pr-agent/webhook_server.py
```

**2. Configure ALB to route to EC2:**

```terraform
resource "aws_lb_target_group" "pr_agent_ec2" {
  name     = "${local.name_prefix}-pr-agent-ec2"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id
  
  health_check {
    path = "/health"
    port = 8080
  }
}

resource "aws_lb_target_group_attachment" "pr_agent" {
  target_group_arn = aws_lb_target_group.pr_agent_ec2.arn
  target_id        = aws_instance.pr_agent.id
  port             = 8080
}
```

**Pros:**
- ✅ Simplest setup
- ✅ Full PR Agent functionality
- ✅ Easy debugging (SSH and check logs)
- ✅ No cold starts

**Cons:**
- ❌ Always-on EC2 cost
- ❌ Need to manage EC2 instance (updates, monitoring)
- ❌ Less scalable (single instance)
- ❌ Need to handle failure/restart

---

## Option 4: Invoke PR Agent Remotely via CLI

Don't host PR Agent - just invoke it remotely from your existing Lambda.

### Implementation

```python
# In your existing src/worker/app.py

import subprocess
import tempfile

def _run_pr_agent_review(repo: str, pr_number: int):
    """Invoke PR Agent CLI from within Lambda."""
    
    pr_url = f"https://github.com/{repo}/pull/{pr_number}"
    
    # Run PR Agent CLI
    result = subprocess.run(
        ['pr-agent', '--pr_url', pr_url, 'review'],
        capture_output=True,
        text=True,
        timeout=60
    )
    
    if result.returncode != 0:
        logger.error("PR Agent failed", extra={"stderr": result.stderr})
    else:
        logger.info("PR Agent completed", extra={"stdout": result.stdout})

# Add to your existing lambda_handler
def lambda_handler(event, context):
    # ... existing code ...
    
    # Optionally run PR Agent alongside your review
    if os.getenv("PR_AGENT_ENABLED", "false") == "true":
        _run_pr_agent_review(repo_full_name, pr_number)
    
    # ... rest of your code ...
```

**Pros:**
- ✅ No additional infrastructure
- ✅ Reuses existing Lambda
- ✅ Simple integration

**Cons:**
- ❌ Increases Lambda execution time
- ❌ Layer size bloat
- ❌ Two tools in one Lambda (messy)

---

## Option 5: Use PR Agent's Python API Directly

Import PR Agent as a library and call it from your Lambda.

### Implementation

```python
# src/pr_agent_integration/wrapper.py

from pr_agent.git_providers.github_provider import GithubProvider
from pr_agent.agent.pr_agent import PRAgent
from pr_agent.config_loader import get_settings

def run_pr_agent_review(repo: str, pr_number: int, github_token: str, openai_key: str):
    """Run PR Agent as library (not CLI)."""
    
    # Configure
    get_settings().github.user_token = github_token
    get_settings().openai.key = openai_key
    
    # Initialize provider
    pr_url = f"https://github.com/{repo}/pull/{pr_number}"
    provider = GithubProvider(pr_url=pr_url)
    
    # Run review
    agent = PRAgent()
    agent.handle_request("/review", provider)

# Use in your worker Lambda
from pr_agent_integration.wrapper import run_pr_agent_review

def lambda_handler(event, context):
    # Option A: Run PR Agent instead of your Bedrock call
    run_pr_agent_review(repo, pr_number, github_token, openai_key)
    
    # Option B: Run both and combine results
    bedrock_result = _run_bedrock_review(...)
    pr_agent_result = run_pr_agent_review(...)
    combined = _merge_reviews(bedrock_result, pr_agent_result)
```

**Pros:**
- ✅ Full programmatic control
- ✅ Can combine with your Bedrock results
- ✅ No separate infrastructure
- ✅ Most flexible

**Cons:**
- ❌ PR Agent API may change
- ❌ Need to understand PR Agent internals
- ❌ Lambda layer size bloat

---

## Recommended Approach for Your System

### Best Option: **Borrow Ideas Only** (No Deployment)

Given constraints:
- ✅ No GitHub Actions
- ✅ Already have working Lambda architecture
- ✅ Custom features (chatbot, test gen, etc.)
- ✅ GovCloud requirement

**Don't deploy PR Agent at all.** Instead:

1. **Read PR Agent source code** to extract patterns:
   - `pr_agent/algo/pr_processing.py` - PR compression strategy
   - `pr_agent/settings/pr_reviewer_prompts.toml` - Prompt templates
   - `pr_agent/tools/pr_reviewer.py` - Review logic

2. **Adapt patterns to your Lambda:**
   - Enhance `src/worker/app.py` with compression strategy
   - Improve prompts in your Bedrock calls
   - Add `/improve` style suggestions

3. **No additional infrastructure needed**

### Second Best: **Lambda with PR Agent Library (Option 5)**

If you really want to run PR Agent:

1. Create Lambda layer with `pr-agent` package
2. Import as library in new Lambda function
3. Separate webhook route: `POST /webhook/pr-agent`
4. Small PRs → PR Agent Lambda
5. Large/security PRs → Your Worker Lambda

**Infrastructure:**
```terraform
# Minimal addition to your Terraform
resource "aws_lambda_function" "pr_agent" {
  # ... similar to your worker Lambda
  layers = [aws_lambda_layer_version.pr_agent.arn]
}

resource "aws_apigatewayv2_route" "pr_agent" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/pr-agent"
  target    = "integrations/${aws_apigatewayv2_integration.pr_agent.id}"
}
```

---

## Cost Comparison (No GitHub Actions)

| Option | Infrastructure Cost | API Cost | Total/Month |
|--------|---------------------|----------|-------------|
| Option 1: Lambda | $5-10 (Lambda) | $50-100 (OpenAI) | $55-110 |
| Option 2: ECS | $40-60 (Fargate 24/7) | $50-100 (OpenAI) | $90-160 |
| Option 3: EC2 | $15-25 (t3.small) | $50-100 (OpenAI) | $65-125 |
| Option 4: In Lambda | $0 (existing) | $50-100 (OpenAI) | $50-100 |
| Option 5: Library | $5-10 (Lambda) | $50-100 (OpenAI) | $55-110 |
| **Your Current** | $15 (Lambda+API+SQS) | $50-200 (Bedrock) | $65-215 |

---

## Next Steps

1. **Read PR Agent source code:** `git clone https://github.com/qodo-ai/pr-agent.git`
2. **Extract patterns:** Focus on `pr_agent/algo/` and `pr_agent/tools/`
3. **Enhance your Lambda:** Add compression, improve prompts
4. **Skip deployment:** No need for additional infrastructure

**Skip the test workflow example** - it won't work without GitHub Actions anyway.

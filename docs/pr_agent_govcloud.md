# Running PR Agent in AWS GovCloud

## Challenge: PR Agent in GovCloud

PR Agent is designed for commercial cloud environments. Running it in **AWS GovCloud** presents specific challenges:

### 🚫 Blockers

1. **OpenAI API Not Available**
   - OpenAI API endpoints are not accessible from GovCloud
   - Commercial cloud services generally blocked by FedRAMP requirements
   - Network egress restrictions to public internet

2. **Anthropic Claude API Not Available**
   - Claude API also not directly accessible from GovCloud
   - Same commercial service restrictions

3. **Docker Hub Rate Limits**
   - Official PR Agent Docker images (`codiumai/pr-agent`) on Docker Hub
   - GovCloud has limited/restricted Docker Hub access
   - Need private ECR registry

4. **PyPI Package Installation**
   - `pip install pr-agent` requires internet access
   - GovCloud Lambda needs VPC NAT Gateway for internet
   - Or pre-build Lambda layers

### ✅ Solution: Use AWS Bedrock Instead

**Good news:** AWS Bedrock IS available in GovCloud (us-gov-west-1)!

---

## Architecture: PR Agent + Bedrock in GovCloud

```
GitHub Enterprise (or github.com) 
    ↓
API Gateway (GovCloud)
    ↓
Lambda (PR Agent fork with Bedrock)
    ↓
AWS Bedrock (us-gov-west-1) ← Claude, other models
    ↓
GitHub API (post review)
```

---

## Option 1: Fork PR Agent and Replace LLM Backend (Recommended)

### Step 1: Fork PR Agent

```bash
git clone https://github.com/qodo-ai/pr-agent.git pr-agent-govcloud
cd pr-agent-govcloud
```

### Step 2: Replace OpenAI/Claude with Bedrock

**Replace the LLM client:**

```python
# Create: pr_agent/llm_providers/bedrock_provider.py

import boto3
import json
from typing import Optional, Dict, Any

class BedrockProvider:
    """AWS Bedrock LLM provider for GovCloud."""
    
    def __init__(self, model_id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"):
        self.model_id = model_id
        self.client = boto3.client(
            'bedrock-runtime',
            region_name='us-gov-west-1'
        )
    
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> str:
        """Generate completion using Bedrock."""
        
        # Format for Claude 3
        messages = [{"role": "user", "content": prompt}]
        
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }
        
        if system:
            body["system"] = system
        
        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body)
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']
    
    def generate_stream(self, prompt: str, **kwargs):
        """Streaming not needed for PR reviews."""
        return self.generate(prompt, **kwargs)
```

### Step 3: Patch PR Agent's LLM Calls

**Modify: pr_agent/algo/ai_handlers.py**

```python
# Find all OpenAI client initializations and replace with Bedrock

# Original PR Agent code:
# from openai import OpenAI
# client = OpenAI(api_key=settings.openai.key)

# Replace with:
from pr_agent.llm_providers.bedrock_provider import BedrockProvider
client = BedrockProvider(model_id=settings.bedrock.model_id)

# All client.chat.completions.create() calls need to be adapted:
# Original:
# response = client.chat.completions.create(
#     model="gpt-4",
#     messages=[{"role": "user", "content": prompt}],
#     temperature=0.7
# )
# result = response.choices[0].message.content

# Replace with:
result = client.generate(
    prompt=prompt,
    temperature=0.7
)
```

### Step 4: Update Configuration

**Modify: pr_agent/settings/configuration.toml**

```toml
[bedrock]
model_id = "anthropic.claude-3-5-sonnet-20240620-v1:0"
region = "us-gov-west-1"

[github]
user_token = ""  # From Secrets Manager
api_base = "https://github.example.com/api/v3"  # Or github.com

# Remove/disable OpenAI settings
# [openai]
# key = ""
```

### Step 5: Build Lambda Deployment Package

```bash
# Create deployment package for GovCloud Lambda
mkdir -p lambda-package
pip install -r requirements.txt -t lambda-package/
cp -r pr_agent/ lambda-package/

# Add Lambda handler
cat > lambda-package/lambda_handler.py << 'EOF'
import json
import os
from pr_agent.git_providers.github_provider import GithubProvider
from pr_agent.agent.pr_agent import PRAgent

def handler(event, context):
    """Lambda handler for PR Agent webhook."""
    body = json.loads(event['body'])
    
    # Extract PR info
    repo = body['repository']['full_name']
    pr_number = body['number']
    pr_url = f"https://github.com/{repo}/pull/{pr_number}"
    
    # Initialize GitHub provider
    provider = GithubProvider(pr_url=pr_url)
    
    # Run PR Agent
    agent = PRAgent()
    agent.handle_request("/review", provider)
    
    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Review completed'})
    }
EOF

# Create ZIP
cd lambda-package
zip -r ../pr-agent-govcloud.zip .
cd ..
```

### Step 6: Deploy to GovCloud

```terraform
# Add to infra/terraform/main.tf

resource "aws_lambda_function" "pr_agent_govcloud" {
  count            = var.pr_agent_govcloud_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-pr-agent-govcloud"
  role             = aws_iam_role.pr_agent_lambda[0].arn
  runtime          = "python3.12"
  handler          = "lambda_handler.handler"
  filename         = "${path.module}/pr-agent-govcloud.zip"
  source_code_hash = filebase64sha256("${path.module}/pr-agent-govcloud.zip")
  timeout          = 300
  memory_size      = 2048  # PR Agent needs more memory
  
  environment {
    variables = {
      AWS_REGION                        = "us-gov-west-1"
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      GITHUB_TOKEN_SECRET_ARN           = local.github_app_private_key_secret_arn
      GITHUB_API_BASE                   = var.github_api_base
    }
  }
  
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.pr_agent[0].id]
  }
  
  tracing_config {
    mode = "Active"
  }
}

resource "aws_iam_role_policy" "pr_agent_bedrock" {
  count = var.pr_agent_govcloud_enabled ? 1 : 0
  role  = aws_iam_role.pr_agent_lambda[0].id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "arn:aws-us-gov:bedrock:us-gov-west-1::foundation-model/${var.bedrock_model_id}"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = local.github_app_private_key_secret_arn
      }
    ]
  })
}

# API Gateway route
resource "aws_apigatewayv2_route" "pr_agent_webhook" {
  count     = var.pr_agent_govcloud_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/pr-agent"
  target    = "integrations/${aws_apigatewayv2_integration.pr_agent_lambda[0].id}"
}

resource "aws_apigatewayv2_integration" "pr_agent_lambda" {
  count              = var.pr_agent_govcloud_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.webhook.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.pr_agent_govcloud[0].invoke_arn
  payload_format_version = "2.0"
}
```

---

## Option 2: Use Your Existing System with PR Agent Patterns

**Better approach:** Don't deploy PR Agent at all. Instead, **borrow their proven patterns** into your existing GovCloud-compatible system.

### What to Extract from PR Agent

1. **PR Compression Strategy**
```python
# Add to src/worker/app.py

def _compress_pr_files(files: list[dict], max_tokens: int) -> list[dict]:
    """
    Apply PR Agent's compression strategy.
    Based on: pr_agent/algo/pr_processing.py
    """
    # 1. Calculate token budget per file
    total_changes = sum(f.get('changes', 0) for f in files)
    
    # 2. Prioritize by change significance
    scored_files = []
    for f in files:
        score = 0
        # High priority: changed code files
        if f['status'] in ('modified', 'added'):
            score += 10
        # Medium priority: new files
        if f['status'] == 'added':
            score += 5
        # Low priority: large generated files
        if f.get('changes', 0) > 500:
            score -= 5
        # Skip: test files, configs, lock files
        if any(skip in f['filename'] for skip in ['.lock', '.json', '.yaml', 'test_']):
            score -= 3
        
        scored_files.append((score, f))
    
    # 3. Sort by score and take top files within token budget
    scored_files.sort(reverse=True, key=lambda x: x[0])
    
    compressed = []
    tokens_used = 0
    for score, f in scored_files:
        estimated_tokens = len(f.get('patch', '')) / 4  # Rough estimate
        if tokens_used + estimated_tokens <= max_tokens:
            compressed.append(f)
            tokens_used += estimated_tokens
        elif len(compressed) == 0:
            # Always include at least one file (truncated)
            f['patch'] = f['patch'][:max_tokens * 4]
            compressed.append(f)
            break
    
    return compressed
```

2. **Improved Prompt Templates**
```python
# Enhance prompts in src/shared/bedrock_client.py

REVIEW_PROMPT_TEMPLATE = """
You are an expert code reviewer. Analyze this pull request and provide actionable feedback.

## PR Context
Repository: {repo}
PR #{pr_number}: {title}
Author: {author}
Files changed: {files_changed}

## Changes
{patch_content}

## Review Guidelines
1. **Security**: Check for vulnerabilities (SQL injection, XSS, hardcoded secrets)
2. **Performance**: Identify inefficiencies (N+1 queries, memory leaks)
3. **Correctness**: Find bugs, edge cases, error handling issues
4. **Best Practices**: Code style, naming, documentation
5. **Tests**: Missing test coverage

## Output Format (JSON)
{{
  "summary": "Overall assessment",
  "findings": [
    {{
      "file": "path/to/file.py",
      "line": 42,
      "severity": "high|medium|low",
      "category": "security|performance|correctness|style",
      "title": "Brief issue title",
      "description": "Detailed explanation",
      "suggestion": "How to fix it"
    }}
  ],
  "score": 1-10
}}

Provide concise, actionable feedback. Focus on critical issues.
"""
```

3. **Better File Filtering**
```python
# Add to src/worker/app.py

SKIP_PATTERNS = {
    # Generated files
    'package-lock.json', 'yarn.lock', 'Pipfile.lock', 'poetry.lock',
    'go.sum', 'Cargo.lock', 'composer.lock',
    
    # Build artifacts
    '.min.js', '.min.css', 'dist/', 'build/', 'target/',
    
    # Documentation
    'CHANGELOG.md', 'README.md',
    
    # Binary files
    '.png', '.jpg', '.gif', '.ico', '.woff', '.woff2', '.ttf', '.eot'
}

def _should_review_file(filename: str) -> bool:
    """Filter out files that don't need review (like PR Agent does)."""
    # Skip if matches any skip pattern
    if any(pattern in filename.lower() for pattern in SKIP_PATTERNS):
        return False
    
    # Only review code files
    code_extensions = {
        '.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.java', '.rb',
        '.php', '.rs', '.cpp', '.c', '.h', '.cs', '.swift', '.kt'
    }
    
    return any(filename.endswith(ext) for ext in code_extensions)
```

---

## Option 3: Minimal PR Agent Wrapper (Hybrid)

Keep most of PR Agent but swap just the LLM client.

```python
# src/pr_agent_minimal/bedrock_wrapper.py

"""
Minimal wrapper to use PR Agent with Bedrock.
This replaces only the LLM provider, keeping all PR Agent logic.
"""

import json
from typing import Any, Dict, Optional
from pr_agent.algo.ai_handlers import BaseAIHandler

class BedrockAIHandler(BaseAIHandler):
    """Bedrock implementation of PR Agent's AI handler."""
    
    def __init__(self, model_id: str):
        import boto3
        self.model_id = model_id
        self.client = boto3.client('bedrock-runtime', region_name='us-gov-west-1')
    
    def chat_completion(
        self,
        model: str,
        messages: list[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Implement PR Agent's expected interface but use Bedrock.
        """
        # Extract system message if present
        system = next((m['content'] for m in messages if m['role'] == 'system'), None)
        
        # Get user messages
        user_messages = [m for m in messages if m['role'] == 'user']
        prompt = '\n\n'.join(m['content'] for m in user_messages)
        
        # Call Bedrock
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        if system:
            body["system"] = system
        
        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body)
        )
        
        result = json.loads(response['body'].read())
        
        # Return in PR Agent's expected format (OpenAI-like)
        return {
            'choices': [{
                'message': {
                    'content': result['content'][0]['text']
                }
            }]
        }

# Monkey-patch PR Agent to use Bedrock
import pr_agent.algo.ai_handlers as ai_handlers
ai_handlers.get_ai_handler = lambda: BedrockAIHandler(
    model_id="anthropic.claude-3-5-sonnet-20240620-v1:0"
)
```

---

## Deployment Checklist for GovCloud

- [ ] **Network Configuration**
  - [ ] Lambda in VPC with private subnets
  - [ ] NAT Gateway for GitHub API access
  - [ ] Security groups allow HTTPS egress to GitHub
  - [ ] VPC endpoints for Bedrock (optional, better performance)

- [ ] **IAM Permissions**
  - [ ] `bedrock:InvokeModel` permission
  - [ ] `secretsmanager:GetSecretValue` for GitHub token
  - [ ] CloudWatch Logs permissions

- [ ] **Bedrock Setup**
  - [ ] Model access enabled in us-gov-west-1
  - [ ] Claude 3.5 Sonnet or required model
  - [ ] Guardrails configured (if needed)

- [ ] **GitHub Configuration**
  - [ ] Webhook pointing to GovCloud API Gateway
  - [ ] GitHub App or token with PR permissions
  - [ ] Test webhook delivery

- [ ] **Secrets Management**
  - [ ] GitHub token in Secrets Manager
  - [ ] KMS key for encryption
  - [ ] Token rotation configured

- [ ] **Monitoring**
  - [ ] CloudWatch Logs enabled
  - [ ] X-Ray tracing active
  - [ ] Alarms for failures

---

## Cost Comparison (GovCloud)

### Option 1: Fork PR Agent + Bedrock

**Monthly cost (100 PRs):**
- Lambda: $10-20 (2GB memory, 60s avg)
- Bedrock: $75-150 (Claude 3.5 Sonnet)
- API Gateway: $1
- NAT Gateway: $32
- **Total: ~$120-200/month**

### Option 2: Use Your Existing System

**Monthly cost (100 PRs):**
- Lambda: Already deployed
- Bedrock: Already configured
- API Gateway: Already deployed
- **Incremental cost: $0** (just better prompts/compression)

---

## Recommendation for GovCloud

### ⭐ Best Approach: **Enhance Your Existing System**

**Why:**
1. ✅ Already GovCloud-compatible
2. ✅ Already uses Bedrock (no API changes needed)
3. ✅ No new infrastructure
4. ✅ Just improve prompts and compression logic
5. ✅ Zero incremental cost
6. ✅ Keep your unique features (chatbot, test gen, etc.)

**What to do:**
1. Clone PR Agent: `git clone https://github.com/qodo-ai/pr-agent.git`
2. Study these files:
   - `pr_agent/algo/pr_processing.py` - PR compression
   - `pr_agent/settings/pr_reviewer_prompts.toml` - Prompts
   - `pr_agent/tools/pr_reviewer.py` - Review logic
3. Extract patterns and add to `src/worker/app.py`
4. Test with your existing Lambda
5. Deploy via existing Terraform

**No PR Agent deployment needed!**

---

## If You Must Deploy PR Agent in GovCloud

### Go with Option 1: Fork + Bedrock

**Steps:**
1. Fork PR Agent repo
2. Replace OpenAI client with Bedrock (see code above)
3. Build Lambda package
4. Deploy with Terraform (see configuration above)
5. Configure webhook

**Effort:** 2-3 days for fork + testing  
**Maintenance:** Ongoing (manual merges from upstream)  
**Benefit:** Get PR Agent features, lose GovCloud compatibility hassles

---

## Summary

| Approach | GovCloud Compatible | Effort | Cost | Recommendation |
|----------|---------------------|--------|------|----------------|
| Deploy PR Agent as-is | ❌ No (OpenAI blocked) | - | - | Don't do this |
| Fork + Bedrock | ✅ Yes | High (2-3 days) | $120-200/mo | Only if you really want PR Agent |
| Borrow patterns | ✅ Yes | Low (1 day) | $0 | ⭐ **Best choice** |
| Minimal wrapper | ✅ Yes | Medium (1-2 days) | $120-200/mo | Unnecessary complexity |

**Bottom line:** Just improve your existing system with PR Agent's proven patterns. No deployment needed, zero incremental cost, GovCloud-compatible by default.

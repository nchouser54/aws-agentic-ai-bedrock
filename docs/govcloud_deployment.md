# Running AWS Agentic PR Reviewer on GovCloud

## Yes, This System CAN Run on AWS GovCloud! ✅

Your entire PR reviewer system is **fully compatible** with AWS GovCloud (us-gov-west-1 or us-gov-east-1).

---

## What Works in GovCloud

### ✅ All Core Services Available

| Service | GovCloud Status | Your Usage |
|---------|----------------|------------|
| **AWS Bedrock** | ✅ Available (us-gov-west-1) | Core LLM for reviews |
| **Lambda** | ✅ Available | Webhook receiver + Worker |
| **API Gateway** | ✅ Available | HTTP API for webhooks |
| **SQS** | ✅ Available | Worker queue |
| **Secrets Manager** | ✅ Available | GitHub tokens |
| **CloudWatch** | ✅ Available | Logs + Metrics |
| **EKS** | ✅ Available | Chatbot webapp (optional) |
| **ECR** | ✅ Available | Docker images |
| **S3** | ✅ Available | (if needed for storage) |

### ✅ Bedrock Models in GovCloud

**Available in us-gov-west-1:**
- ✅ **Claude 3.5 Sonnet** (anthropic.claude-3-5-sonnet-20240620-v1:0) - **Recommended**
- ✅ Claude 3 Opus (anthropic.claude-3-opus-20240229-v1:0)
- ✅ Claude 3 Sonnet (anthropic.claude-3-sonnet-20240229-v1:0)
- ✅ Claude 3 Haiku (anthropic.claude-3-haiku-20240307-v1:0)
- ✅ Amazon Titan models

**Your current code already uses these!** No changes needed.

---

## What DOESN'T Work (and Workarounds)

### ❌ OpenAI API
- **Problem**: OpenAI API not accessible from GovCloud
- **Your Status**: ✅ Not used - you use Bedrock
- **Action**: None needed

### ❌ Anthropic Direct API
- **Problem**: Claude API not accessible directly
- **Your Status**: ✅ You use Bedrock, not direct API
- **Action**: None needed

### ⚠️ Public Internet Access
- **Problem**: GovCloud has restricted egress
- **Impact**: GitHub API calls, Docker Hub
- **Solution**: NAT Gateway + VPC (already in your infra)

### ⚠️ GitHub Actions (if self-hosted)
- **Problem**: GitHub.com Actions don't run in GovCloud
- **Your Status**: ✅ You use webhooks, not Actions
- **Action**: None needed

---

## Deployment Architecture for GovCloud

```
┌─────────────────────────────────────────────────────────┐
│  GitHub.com OR GitHub Enterprise Server                 │
│  (webhook configured)                                   │
└────────────────────┬────────────────────────────────────┘
                     │ HTTPS webhook
                     │
┌────────────────────▼────────────────────────────────────┐
│  AWS GovCloud (us-gov-west-1)                           │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ API Gateway (HTTP API)                           │  │
│  │ POST /webhook                                    │  │
│  └───────┬──────────────────────────────────────────┘  │
│          │                                              │
│  ┌───────▼──────────────────────────────────────────┐  │
│  │ Lambda: webhook_receiver                         │  │
│  │ - Validates signature                            │  │
│  │ - Sends to SQS                                   │  │
│  └───────┬──────────────────────────────────────────┘  │
│          │                                              │
│  ┌───────▼──────────────────────────────────────────┐  │
│  │ SQS Queue                                        │  │
│  └───────┬──────────────────────────────────────────┘  │
│          │                                              │
│  ┌───────▼──────────────────────────────────────────┐  │
│  │ Lambda: worker                                   │  │
│  │ - Reviews PR with Bedrock                        │  │
│  │ - Posts comments to GitHub                       │  │
│  │ - Generates test cases                           │  │
│  └───────┬──────────────────────────────────────────┘  │
│          │                                              │
│  ┌───────▼──────────────────────────────────────────┐  │
│  │ AWS Bedrock (us-gov-west-1)                      │  │
│  │ Model: Claude 3.5 Sonnet                         │  │
│  └──────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ VPC with NAT Gateway                             │  │
│  │ - Lambda in private subnets                      │  │
│  │ - NAT for GitHub API egress                      │  │
│  │ - Security groups                                │  │
│  └──────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ EKS Cluster (optional - for chatbot)             │  │
│  │ - Chatbot webapp pods                            │  │
│  │ - ALB for HTTPS                                  │  │
│  │ - Optional: Keycloak                             │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## GovCloud-Specific Configuration

### 1. Update Terraform Variables

**File: `infra/terraform/terraform.govcloud.tfvars`**

```hcl
# Region
aws_region = "us-gov-west-1"  # or us-gov-east-1

# Bedrock Model (must be available in GovCloud)
bedrock_model_id = "anthropic.claude-3-5-sonnet-20240620-v1:0"

# GitHub Configuration
github_api_base = "https://api.github.com"  # or your GHE server
github_app_id   = "your-app-id"

# VPC Configuration (REQUIRED in GovCloud)
vpc_id              = "vpc-xxxxx"
private_subnet_ids  = ["subnet-xxxxx", "subnet-yyyyy"]
enable_nat_gateway  = true  # Required for GitHub API access

# Compliance Tags
tags = {
  Environment       = "production"
  Mission           = "DevSecOps"
  Compliance        = "FedRAMP"
  FISMA             = "Moderate"
  Project           = "PR-Reviewer"
  CostCenter        = "Engineering"
  DataClassification = "Sensitive"
}
```

### 2. Update ARN Formats

GovCloud uses different ARN format: `arn:aws-us-gov:` instead of `arn:aws:`

**File: `infra/terraform/main.tf`** (already handles this):

```hcl
locals {
  # Automatically detect GovCloud
  is_govcloud = startswith(data.aws_region.current.name, "us-gov-")
  arn_partition = local.is_govcloud ? "aws-us-gov" : "aws"
}

# Use in ARNs
resource "aws_iam_role_policy" "bedrock" {
  policy = jsonencode({
    Statement = [{
      Resource = "arn:${local.arn_partition}:bedrock:${var.aws_region}::foundation-model/*"
    }]
  })
}
```

### 3. Enable VPC for Lambda (Required)

**File: `infra/terraform/main.tf`**

```hcl
resource "aws_lambda_function" "webhook_receiver" {
  # ... existing config ...
  
  # REQUIRED in GovCloud for GitHub API access
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }
}

resource "aws_security_group" "lambda" {
  vpc_id = var.vpc_id
  
  # Allow HTTPS egress to GitHub
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS to GitHub API"
  }
  
  # Allow Bedrock API (if using VPC endpoints)
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS to Bedrock"
  }
}

# NAT Gateway for private Lambda internet access
resource "aws_nat_gateway" "lambda" {
  count         = var.enable_nat_gateway ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = var.public_subnet_ids[0]
}

resource "aws_eip" "nat" {
  count  = var.enable_nat_gateway ? 1 : 0
  domain = "vpc"
}
```

### 4. Enable Bedrock Model Access

**In GovCloud Console:**

1. Navigate to **Bedrock Console** → **Model Access**
2. Click **Request model access**
3. Select:
   - ✅ Claude 3.5 Sonnet
   - ✅ Claude 3 Opus
   - ✅ Claude 3 Haiku
4. Submit (approval usually instant)

**Verify via CLI:**

```bash
aws bedrock list-foundation-models \
  --region us-gov-west-1 \
  --query 'modelSummaries[?contains(modelId,`claude`)].modelId'
```

### 5. Configure GitHub Webhook

**If using github.com:**
- Webhook URL: `https://<api-gateway-id>.execute-api.us-gov-west-1.amazonaws.com/webhook`
- Content type: `application/json`
- Secret: (store in Secrets Manager)
- Events: Pull requests, Push

**If using GitHub Enterprise Server:**
- Same configuration
- Ensure GHE can reach GovCloud API Gateway
- May need firewall rules

---

## Deployment Steps for GovCloud

### Step 1: Enable Bedrock

```bash
# Check available models
aws bedrock list-foundation-models \
  --region us-gov-west-1 \
  --by-output-modality TEXT \
  --query 'modelSummaries[*].[modelId,modelName]' \
  --output table

# Request access (if needed)
# Do this via AWS Console → Bedrock → Model Access
```

### Step 2: Deploy Infrastructure

```bash
cd infra/terraform

# Initialize with GovCloud backend
terraform init

# Create GovCloud-specific tfvars
cat > terraform.govcloud.tfvars << 'EOF'
aws_region           = "us-gov-west-1"
bedrock_model_id     = "anthropic.claude-3-5-sonnet-20240620-v1:0"
vpc_id               = "vpc-xxxxx"
private_subnet_ids   = ["subnet-xxxxx", "subnet-yyyyy"]
public_subnet_ids    = ["subnet-zzzzz", "subnet-aaaaa"]
enable_nat_gateway   = true
github_api_base      = "https://api.github.com"
github_app_id        = "123456"
github_webhook_secret = "your-secret"

tags = {
  Environment = "production"
  Compliance  = "FedRAMP"
  FISMA       = "Moderate"
}
EOF

# Plan
terraform plan -var-file=terraform.govcloud.tfvars

# Apply
terraform apply -var-file=terraform.govcloud.tfvars
```

### Step 3: Store GitHub Credentials

```bash
# Store GitHub App private key
aws secretsmanager create-secret \
  --name github-app-private-key \
  --secret-string file://github-app-key.pem \
  --region us-gov-west-1

# Store webhook secret
aws secretsmanager create-secret \
  --name github-webhook-secret \
  --secret-string "your-webhook-secret" \
  --region us-gov-west-1
```

### Step 4: Test Bedrock Access

```bash
# Test from your local machine
aws bedrock-runtime invoke-model \
  --region us-gov-west-1 \
  --model-id anthropic.claude-3-5-sonnet-20240620-v1:0 \
  --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":100,"messages":[{"role":"user","content":"Hello"}]}' \
  --cli-binary-format raw-in-base64-out \
  output.json

cat output.json
```

### Step 5: Configure GitHub Webhook

```bash
# Get API Gateway URL from Terraform output
terraform output webhook_url

# Configure in GitHub:
# Settings → Webhooks → Add webhook
# URL: https://<api-id>.execute-api.us-gov-west-1.amazonaws.com/webhook
# Secret: (from Secrets Manager)
# Events: Pull request, Push
# Active: ✓
```

### Step 6: Test End-to-End

```bash
# Create a test PR in your repo
# Check CloudWatch Logs
aws logs tail /aws/lambda/pr-reviewer-webhook-receiver \
  --region us-gov-west-1 \
  --follow

aws logs tail /aws/lambda/pr-reviewer-worker \
  --region us-gov-west-1 \
  --follow
```

---

## GovCloud Compliance Considerations

### FedRAMP Requirements

1. **Encryption at Rest**: All enabled by default
   - Lambda environment variables: KMS encrypted
   - SQS: Server-side encryption
   - Secrets Manager: KMS encrypted
   - CloudWatch Logs: KMS encrypted

2. **Encryption in Transit**: HTTPS everywhere
   - API Gateway: TLS 1.2+
   - GitHub webhooks: HTTPS
   - Bedrock API: HTTPS
   - Internal AWS: VPC private links

3. **Access Control**:
   - IAM roles with least privilege
   - VPC security groups
   - Network ACLs

4. **Audit Logging**:
   - CloudWatch Logs (all Lambda executions)
   - CloudTrail (API calls)
   - X-Ray tracing

### Additional GovCloud Hardening

**File: `infra/terraform/compliance.tf`**

```hcl
# KMS key for encryption
resource "aws_kms_key" "pr_reviewer" {
  description             = "PR Reviewer encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-kms-key"
  })
}

# Lambda environment encryption
resource "aws_lambda_function" "worker" {
  # ... existing config ...
  
  kms_key_arn = aws_kms_key.pr_reviewer.arn
  
  environment {
    variables = {
      # Force encryption
      AWS_LAMBDA_EXEC_WRAPPER = "/opt/security-wrapper"
    }
  }
}

# CloudWatch Logs encryption
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = 90  # FedRAMP requires 90+ days
  kms_key_id        = aws_kms_key.pr_reviewer.arn
}

# VPC Flow Logs (required for FedRAMP Moderate)
resource "aws_flow_log" "vpc" {
  vpc_id          = var.vpc_id
  traffic_type    = "ALL"
  iam_role_arn    = aws_iam_role.flow_logs.arn
  log_destination = aws_cloudwatch_log_group.flow_logs.arn
}
```

---

## GovCloud-Specific Troubleshooting

### Issue: Lambda Cannot Reach GitHub API

**Symptoms:**
- "Connection timeout" errors
- "Network unreachable"

**Solution:**
```bash
# 1. Verify Lambda is in VPC
aws lambda get-function-configuration \
  --function-name pr-reviewer-worker \
  --region us-gov-west-1 \
  --query 'VpcConfig'

# 2. Check NAT Gateway
aws ec2 describe-nat-gateways \
  --region us-gov-west-1 \
  --filter "Name=vpc-id,Values=vpc-xxxxx"

# 3. Check route tables
aws ec2 describe-route-tables \
  --region us-gov-west-1 \
  --filter "Name=vpc-id,Values=vpc-xxxxx"

# Route should exist: 0.0.0.0/0 → nat-xxxxx
```

### Issue: Bedrock Model Not Available

**Symptoms:**
- "ValidationException: The model ID is not supported"

**Solution:**
```bash
# Check enabled models
aws bedrock list-foundation-models \
  --region us-gov-west-1 \
  --by-provider anthropic

# Request access in console if needed
# AWS Console → Bedrock → Model Access
```

### Issue: ARN Format Errors

**Symptoms:**
- "Invalid ARN format"
- "Resource not found"

**Solution:**
Use `arn:aws-us-gov:` prefix instead of `arn:aws:`

```python
# In your code:
import boto3

# Detect partition automatically
sts = boto3.client('sts')
account_id = sts.get_caller_identity()['Account']
partition = sts.get_caller_identity()['Arn'].split(':')[1]  # aws-us-gov or aws

bedrock_arn = f"arn:{partition}:bedrock:{region}::foundation-model/{model_id}"
```

---

## Cost Estimate (GovCloud)

**Monthly cost for 100 PRs:**

| Service | Usage | GovCloud Cost |
|---------|-------|---------------|
| Bedrock (Claude 3.5) | ~10M tokens | $75-150 |
| Lambda (webhook) | 100 invocations | $0.01 |
| Lambda (worker) | 100 invocations, 2GB, 60s avg | $10-20 |
| API Gateway | 100 requests | $0.01 |
| SQS | 100 messages | $0.00 |
| NAT Gateway | 1GB data transfer | $0.05 |
| Secrets Manager | 2 secrets | $0.80 |
| CloudWatch Logs | 1GB logs | $0.50 |
| **Total** | | **$90-175/month** |

**Note**: GovCloud pricing is typically 10-20% higher than commercial regions.

---

## Summary: GovCloud Compatibility

| Component | GovCloud Compatible | Notes |
|-----------|---------------------|-------|
| Lambda Functions | ✅ Yes | Requires VPC for internet |
| API Gateway | ✅ Yes | HTTP API supported |
| Bedrock | ✅ Yes | Claude 3.5 Sonnet available |
| SQS | ✅ Yes | Standard and FIFO |
| Secrets Manager | ✅ Yes | KMS encrypted |
| CloudWatch | ✅ Yes | Logs, Metrics, Alarms |
| EKS (chatbot) | ✅ Yes | Full K8s support |
| VPC | ✅ Yes | Required for Lambda |
| NAT Gateway | ✅ Yes | Required for GitHub API |

**Bottom Line:** Your entire system works in GovCloud with minimal configuration changes. The main differences are:
1. Use `us-gov-west-1` or `us-gov-east-1` region
2. Lambda must be in VPC with NAT Gateway
3. ARN format uses `aws-us-gov` partition
4. Enable Bedrock model access
5. Add FedRAMP compliance tags

Everything else works exactly the same! 🎉

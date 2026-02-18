# Deploying to AWS GovCloud (us-gov-west-1)

This guide covers the end-to-end Terraform deployment for the AI PR Reviewer
in a GovCloud partition targeting GitHub Enterprise Server (GHES).

---

## Prerequisites

- AWS GovCloud account with Bedrock Claude access enabled
- Terraform ≥ 1.5
- AWS CLI configured for `us-gov-west-1`
- All GitHub App secrets pre-created in Secrets Manager
  (see [setup-ghes-app.md](setup-ghes-app.md))

---

## 1. Request Bedrock Model Access

In the AWS GovCloud console → **Amazon Bedrock → Model access**, request access to:

| Stage | Model | Terraform variable |
|---|---|---|
| Stage-1 planner | `anthropic.claude-3-haiku-20240307-v1:0` | `bedrock_model_light` |
| Stage-2 reviewer | `anthropic.claude-3-5-sonnet-20240620-v1:0` | `bedrock_model_heavy` |
| Legacy fallback | same as heavy | `bedrock_model_id` |

> **Note:** Available models in GovCloud differ from commercial. Run
> `aws bedrock list-foundation-models --region us-gov-west-1` to see what is
> available in your account.

---

## 2. Create Your tfvars File

Copy the example and fill it in:

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.govcloud.tfvars
```

Key variables:

```hcl
aws_region             = "us-gov-west-1"
environment            = "prod"
project_name           = "ai-pr-reviewer"

github_api_base        = "https://<ghes-hostname>/api/v3"

bedrock_model_id       = "anthropic.claude-3-5-sonnet-20240620-v1:0"
bedrock_model_light    = "anthropic.claude-3-haiku-20240307-v1:0"
bedrock_model_heavy    = "anthropic.claude-3-5-sonnet-20240620-v1:0"

check_run_name         = "AI PR Reviewer"
max_review_files       = 30
max_diff_bytes         = 8000

dry_run                = false
```

---

## 3. Deploy Infrastructure

```bash
cd infra/terraform

terraform init -backend-config="..."

terraform plan -var-file=terraform.govcloud.tfvars -out=govcloud.plan

terraform apply govcloud.plan
```

Note the outputs:

```bash
terraform output webhook_url        # → GitHub App webhook URL
terraform output secret_arns        # → ARNs for Secrets Manager
```

---

## 4. Store Secrets

After applying Terraform:

```bash
# Webhook secret
aws secretsmanager put-secret-value \
  --secret-id <github_webhook_secret_arn> \
  --secret-string '{"secret": "<WEBHOOK_SECRET>"}' \
  --region us-gov-west-1

# App private key
aws secretsmanager put-secret-value \
  --secret-id <github_app_private_key_secret_arn> \
  --secret-string "$(cat your-app.private-key.pem)" \
  --region us-gov-west-1

# App ID
aws secretsmanager put-secret-value \
  --secret-id <github_app_ids_secret_arn> \
  --secret-string '{"app_id": "12345"}' \
  --region us-gov-west-1
```

---

## 5. Smoke Test

Open a small PR (2–3 files) in one of the installed repositories.
Within 1–3 minutes you should see:

1. A GitHub Check Run named `AI PR Reviewer` appear on the PR.
2. The check run status transitions from `in_progress` → `completed / neutral`.
3. PR review comments posted inline for any findings with mapped line positions.

To trigger manually:

```bash
python scripts/local_invoke_webhook.py \
  --payload scripts/sample_pull_request_opened.json
```

---

## 6. Verify CloudWatch Alarms

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix ai-pr-reviewer \
  --region us-gov-west-1 \
  --query 'MetricAlarms[*].{Name:AlarmName,State:StateValue}'
```

Expected alarms (all `OK` when no failures):
- `ai-pr-reviewer-prod-dlq-messages`
- `ai-pr-reviewer-prod-review-queue-age`
- `ai-pr-reviewer-prod-worker-errors`
- `ai-pr-reviewer-prod-receiver-errors`

---

## 7. Enable 2-Stage Reviews

Once smoke test passes, confirm 2-stage is active by checking CloudWatch Logs:

```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/ai-pr-reviewer-prod-pr-review-worker \
  --filter-pattern "two_stage_review_start" \
  --region us-gov-west-1
```

---

## Rollback

Set `dry_run = true` in your tfvars and apply to halt review posting:

```bash
terraform apply -var="dry_run=true" -var-file=terraform.govcloud.tfvars
```

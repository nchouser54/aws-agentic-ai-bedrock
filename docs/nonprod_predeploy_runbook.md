# Non-Prod Pre-Deploy Runbook (KB + Chatbot)

This runbook is the fast path to determine whether you are ready to run Terraform plan/apply for non-prod.

## 1) Run the automated preflight

Run `scripts/predeploy_nonprod_checks.py` against your tfvars file.

Expected outcomes:

- `[OK] terraform version: ...` with version `>= 1.6.0`
- `[OK] required KB values are set`
- Final line: `Result: READY for terraform plan/apply`

If you see `Result: NOT READY for apply`, fix all `[FAIL]` items first.

## 2) Required values checklist

You must set these values in your non-prod tfvars:

- `bedrock_knowledge_base_id`
- `bedrock_kb_data_source_id`

Recommended first-rollout safety settings:

- `environment = "nonprod"`
- `chatbot_retrieval_mode = "hybrid"`
- `kb_sync_enabled = true`
- `dry_run = true`
- `teams_adapter_enabled = false`

## 3) Terraform execution sequence

After preflight passes:

1. Run Terraform init in `infra/terraform`
2. Run Terraform validate
3. Run Terraform plan with your non-prod tfvars
4. Run Terraform apply

## 4) Post-apply checks

Confirm outputs include:

- `chatbot_url`
- `kb_sync_function_name`
- `kb_sync_documents_bucket`

Then run smoke checks:

- chatbot mode checks (`live`, `kb`, `hybrid`)
- manual invocation of KB sync Lambda

## 5) Go/No-Go

Go if all are true:

- Terraform plan/apply succeeds without IAM/resource errors
- KB sync Lambda runs and returns an ingestion job when uploads occur
- Chatbot responses include expected source telemetry (`context_source`)
- No critical errors in CloudWatch logs

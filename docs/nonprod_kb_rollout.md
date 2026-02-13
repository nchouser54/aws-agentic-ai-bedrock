# Non-Prod Rollout Checklist: Confluence + Bedrock Knowledge Base

## 1) Terraform variables

Set these in `infra/terraform/terraform.nonprod.tfvars` (copied from the example) before deploy:

- `chatbot_retrieval_mode = "hybrid"`
- `bedrock_knowledge_base_id = "<kb-id>"`
- `bedrock_kb_top_k = 5`
- `kb_sync_enabled = true`
- `bedrock_kb_data_source_id = "<kb-data-source-id>"`
- `kb_sync_schedule_expression = "rate(6 hours)"`
- `kb_sync_s3_prefix = "confluence"`
- `confluence_sync_cql = "type=page order by lastmodified desc"`
- `confluence_sync_limit = 25`

Recommended safety settings during first rollout:

- `dry_run = true` (worker)
- `teams_adapter_enabled = false` unless actively testing Teams path

## 2) Secrets validation

Confirm these Secrets Manager entries are populated with real values:

- `github_webhook_secret`
- `github_app_private_key_pem`
- `github_app_ids`
- `atlassian_credentials`

`atlassian_credentials` JSON should include:

- `jira_base_url`
- `confluence_base_url`
- `email`
- `api_token`

## 3) Deploy and capture outputs

After apply, verify outputs:

- `chatbot_url`
- `kb_sync_function_name`
- `kb_sync_documents_bucket`

## 4) Smoke tests

### Chatbot retrieval mode checks

Use `scripts/smoke_test_chatbot_modes.py` against `chatbot_url`:

- mode `live` should return `sources.context_source=live`
- mode `kb` should return `sources.context_source=kb` (if KB has data)
- mode `hybrid` should return either `kb` or `hybrid_fallback`

### KB sync trigger check

Use `scripts/trigger_kb_sync.py` against `kb_sync_function_name`:

- verify `uploaded > 0` for expected pages
- verify `ingestion_job_id` is present when uploads occur

## 5) Observability checks

In CloudWatch logs:

- Chatbot logs include `retrieval_mode`, `context_source`, `kb_items`
- KB sync logs include `uploaded`, `candidate_results`, `knowledge_base_id`, `ingestion_job_id`

## 6) Go/No-Go criteria

Go to broader non-prod testing when all are true:

- Terraform apply succeeds cleanly
- Chatbot smoke test returns expected source telemetry
- Scheduled KB sync runs on schedule and starts ingestion jobs
- No auth/permission errors for Bedrock, S3, Secrets Manager, or Atlassian

# AI PR Reviewer (AWS GovCloud + Terraform + GitHub App)

Production-grade asynchronous Pull Request reviewer for **AWS GovCloud (us-gov-west-1)** using a **company-hosted GitHub App** (no GitHub Actions), Amazon Bedrock, and Terraform.

## Why this architecture

This implementation uses **API Gateway HTTP API** (instead of Lambda Function URL) for ingress because it provides cleaner route management (`POST /webhook/github`), better operational controls, and easier extension points (authorizers/WAF/throttling/stages) for enterprise/GovCloud environments.

## Implemented flow

1. GitHub sends `pull_request` webhook to `POST /webhook/github`.
2. Webhook Lambda verifies `X-Hub-Signature-256` against Secrets Manager secret, validates event/action, and enqueues SQS message immediately.
3. Worker Lambda consumes SQS asynchronously.
4. Worker claims idempotency in DynamoDB with key `{repo}:{pr}:{sha}` and TTL.
5. Worker fetches PR metadata/files from GitHub REST API using GitHub App installation token.
6. Worker calls Bedrock Agent first, then falls back to direct model invocation if agent call fails.
7. Worker validates strict JSON schema output, sanitizes sensitive-file findings, attempts inline diff-position comments when safely mappable, and posts one PR review.
8. Retries and failures route through SQS redrive to DLQ.

## Repo layout

- `infra/terraform` — all infrastructure as code.
- `src/webhook_receiver` — webhook ingress Lambda.
- `src/worker` — asynchronous PR review Lambda.
- `src/shared` — auth, GitHub client, Bedrock client, schema, logging, retry utilities.
- `tests` — unit tests.
- `scripts` — local payload/signature/invoke helpers.

## GitHub App setup

Create a **GitHub App** (organization or enterprise owned) and configure:

- **Webhook URL:** Terraform output `webhook_url`
- **Webhook secret:** value stored in Secrets Manager `github_webhook_secret`
- **Webhook event subscriptions:**
  - `Pull request`
- **Repository permissions:**
  - `Pull requests`: **Read & write** (required to create PR reviews)
  - `Contents`: **Read & write** (required for autonomous remediation PR commits)
  - `Metadata`: **Read-only**

Install the app on desired repositories/org repos.

## Required AWS Secrets Manager secrets

Terraform creates placeholders:

- `github_webhook_secret`
- `github_app_private_key_pem`
- `github_app_ids` (JSON: `{"app_id":"...","installation_id":"..."}`)

After deployment, replace placeholder values with real values.

## Environment/config

Worker Lambda env vars:

- `AWS_REGION=us-gov-west-1`
- `BEDROCK_AGENT_ID` (optional)
- `BEDROCK_AGENT_ALIAS_ID` (optional)
- `BEDROCK_MODEL_ID` (fallback model)
- `GITHUB_API_BASE=https://api.github.com`
- `DRY_RUN=true|false`
- `AUTO_PR_ENABLED=true|false`
- `AUTO_PR_MAX_FILES` (default `5`)
- `AUTO_PR_BRANCH_PREFIX` (default `ai-autofix`)
- `REVIEW_COMMENT_MODE=summary_only|inline_best_effort|strict_inline`
- `CHATBOT_MODEL_ID` (Jira/Confluence chatbot model)
- `ATLASSIAN_CREDENTIALS_SECRET_ARN`

Webhook Lambda env vars:

- `WEBHOOK_SECRET_ARN`
- `QUEUE_URL`
- `GITHUB_ALLOWED_REPOS` (optional CSV allow-list)

Chatbot endpoint:

- `POST /chatbot/query`
- JSON body:
  - `query` (required)
  - `jira_jql` (optional)
  - `confluence_cql` (optional)

Teams adapter endpoint:

- `POST /chatbot/teams`
- Request body follows Teams/Bot activity shape (uses `text`)
- Optional header auth: `X-Teams-Adapter-Token: <token>`
- Deployment is optional and **disabled by default** (`teams_adapter_enabled=false`)

## Terraform deployment

### Prerequisites

- AWS GovCloud credentials targeting `us-gov-west-1`
- Terraform >= 1.6

### Deploy

1. `cd infra/terraform`
2. `terraform init`
3. `cp terraform.tfvars.example terraform.tfvars`
4. Edit values as needed.
5. `terraform plan`
6. `terraform apply`
7. Capture output `webhook_url` and set in GitHub App webhook config.

### Outputs

- `webhook_url`
- `queue_name`
- `idempotency_table_name`
- `secret_arns`

## Local testing

### Install dependencies

- `python -m venv .venv`
- `source .venv/bin/activate`
- `pip install -r requirements.txt`

### Run unit tests

- `pytest -q`

### Generate webhook signature

- `python scripts/generate_signature.py <webhook_secret> scripts/sample_pull_request_opened.json`

### Local invoke helpers

- `python scripts/local_invoke_webhook.py`
- `python scripts/local_invoke_worker.py`

> Note: local invokes still expect AWS credentials/resources for full path behavior unless mocked.

## Quality gates (lint + tests)

This repository includes CI checks for pull requests and pushes to `main`:

- Ruff linting (`python -m ruff check src tests scripts`)
- Pytest unit tests (`python -m pytest -q`)

Run the same checks locally:

- `make install`
- `make check`

## Operations runbook

### Idempotency

DynamoDB conditional put ensures one review per PR head SHA.

### Retry behavior

GitHub API calls use exponential backoff + jitter for transient failures (`403`, `429`, `5xx`) and network exceptions.

### DLQ

Failed SQS messages route to DLQ after max receive attempts (`5`). Investigate worker logs + message body before replay.

### Metrics

Worker emits CloudWatch custom metrics:

- `reviews_success`
- `reviews_failed`
- `duration_ms`

### Structured logging

JSON logs include correlation context fields:

- `delivery_id`
- `repo`
- `pr_number`
- `sha`
- `correlation_id`

### Dry-run mode

Set `DRY_RUN=true` to skip GitHub review posting and log intended payload only.

### PR review options

You can choose how PR comments are posted via `REVIEW_COMMENT_MODE`:

- `summary_only`: post summary review body only, no inline comments.
- `inline_best_effort` (default): post inline comments where mapping is safe; keep others in summary body.
- `strict_inline`: if any mapping is uncertain, suppress all inline comments and keep findings in summary body.

### Autonomous remediation PR mode

When `AUTO_PR_ENABLED=true`, the worker attempts to create a follow-up autofix PR:

- Uses model-provided `suggested_patch` entries only.
- Skips sensitive files (`.env`, keys, secrets-related paths).
- Applies unified-diff patches to changed files.
- Creates a branch (`AUTO_PR_BRANCH_PREFIX/...`) and opens a PR targeting the original base branch.

Recommended rollout:

1. Keep `DRY_RUN=true` and `AUTO_PR_ENABLED=true` to inspect logs first.
2. Move to `DRY_RUN=false` in non-prod sandbox repos.
3. Enable for production repos after approval.

## Troubleshooting

### Signature verification failures

- Confirm GitHub App webhook secret matches `github_webhook_secret` exactly.
- Confirm raw request body is used for HMAC (no re-serialization).
- Confirm header is `X-Hub-Signature-256`.

### GitHub rate limits / abuse protection

- Watch for `403`/`429` in worker logs.
- Backoff and retries are built-in; consider reducing throughput or widening queue processing windows.

### Bedrock agent/model errors

- Ensure region is `us-gov-west-1` and selected model/agent is available in GovCloud account.
- If agent invocation fails, worker falls back to direct model invocation using `BEDROCK_MODEL_ID`.

### Inline comments not posted

- Inline comments only post when file+line mapping to PR diff `position` is safe.
- Unmappable findings are retained in the review body.

### Autofix PR not created

- Confirm `AUTO_PR_ENABLED=true` and `DRY_RUN=false`.
- Verify GitHub App has `Contents: Read & write`.
- Check whether findings included valid `suggested_patch` unified diffs.

### Jira/Confluence chatbot setup

1. Populate Secrets Manager secret `atlassian_credentials` with JSON:
  - `jira_base_url`
  - `confluence_base_url`
  - `email`
  - `api_token`
2. Deploy Terraform and capture `chatbot_url` output.
3. Send requests to `POST /chatbot/query`.

Example request body:

- `{"query":"Summarize top blockers for release","jira_jql":"project=PLAT AND statusCategory!=Done","confluence_cql":"type=page AND space=ENG"}`

### Teams adapter setup

1. Enable `teams_adapter_enabled=true` in Terraform.
2. (Optional) set `teams_adapter_token` and configure your caller to send `X-Teams-Adapter-Token`.
3. Deploy and capture `teams_chatbot_url` output.
4. Configure your Teams bot/webhook relay to POST activity payloads to `/chatbot/teams`.

## Security notes

- Secrets are in AWS Secrets Manager encrypted with customer-managed KMS key.
- IAM is least-privilege scoped to specific resources where possible.
- Worker enforces safety rule: no suggested patches for sensitive files (`.env`, keys, secret-bearing files).
- Security findings avoid copying potential secrets.

## References (required docs)

- GitHub webhook signature validation (`X-Hub-Signature-256`):
  - [Validate webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
- GitHub PR Reviews REST endpoints:
  - [REST API: Pull request reviews](https://docs.github.com/en/rest/pulls/reviews)
- GitHub App authentication (JWT + installation token):
  - [Authenticating with a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app)
- AWS Lambda webhook endpoints via API Gateway HTTP API:
  - [HTTP API Lambda proxy integration](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html)
- Amazon Bedrock Agents and region support:
  - [Bedrock Agents user guide](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
  - [Bedrock region support](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-regions.html)

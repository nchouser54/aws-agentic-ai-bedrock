# AI PR Reviewer (AWS GovCloud + Terraform + GitHub App)

Production-grade asynchronous Pull Request reviewer for **AWS GovCloud (us-gov-west-1)** using a **company-hosted GitHub App** (no GitHub Actions), Amazon Bedrock, and Terraform.

> **New here?** See [docs/SETUP.md](docs/SETUP.md) for the complete setup guide covering all features, shared prerequisites, and company-hosted (Data Center) vs Cloud configuration.

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
- `src/chatbot` — Jira/Confluence chatbot Lambda.
- `src/sprint_report` — sprint/standup report agent Lambda.
- `src/test_gen` — test generation agent Lambda.
- `src/pr_description` — PR description generator Lambda.
- `src/release_notes` — release notes generator Lambda.
- `src/kb_sync` — Confluence → KB sync Lambda.
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
- `GITHUB_API_BASE=https://github.example.com/api/v3` (or `https://api.github.com` for github.com)
- `DRY_RUN=true|false`
- `AUTO_PR_ENABLED=true|false`
- `AUTO_PR_MAX_FILES` (default `5`)
- `AUTO_PR_BRANCH_PREFIX` (default `ai-autofix`)
- `REVIEW_COMMENT_MODE=summary_only|inline_best_effort|strict_inline`
- `CHATBOT_MODEL_ID` (Jira/Confluence chatbot model)
- `ATLASSIAN_CREDENTIALS_SECRET_ARN`
- `CHATBOT_API_TOKEN` or `CHATBOT_API_TOKEN_SECRET_ARN` (used when `chatbot_auth_mode=token`)
- `TEAMS_ADAPTER_TOKEN` or `TEAMS_ADAPTER_TOKEN_SECRET_ARN` (used for `/chatbot/teams` when `chatbot_auth_mode=token`)

Webhook Lambda env vars:

- `WEBHOOK_SECRET_ARN`
- `QUEUE_URL`
- `GITHUB_ALLOWED_REPOS` (optional CSV allow-list)

Chatbot endpoint:

- `POST /chatbot/query`
- JSON body:
  - `query` (required)
  - `conversation_id` (optional; enables per-thread memory when memory is enabled)
  - `stream` (optional bool; returns chunked stream payload for stream-style UI)
  - `stream_chunk_chars` (optional int; chunk size for stream payload)
  - `assistant_mode` (optional: `contextual|general`; defaults to `contextual`)
  - `llm_provider` (optional: `bedrock|anthropic_direct`; defaults to `bedrock`)
  - `model_id` (optional override; validated against allow-list when configured)
  - `jira_jql` (optional)
  - `confluence_cql` (optional)
  - `retrieval_mode` (optional: `live|kb|hybrid`; defaults to `hybrid`)

Assistant mode behavior:

- `contextual`: existing Jira/Confluence/KB/GitHub context-aware flow.
- `general`: freeform AI chat (no Jira/Confluence/KB retrieval context).

Provider behavior:

- `bedrock`: uses Bedrock runtime and supports model override (including enabled Amazon-hosted Bedrock models).
- `anthropic_direct`: optional direct Anthropic API path using your own API key.

Anthropic direct configuration (optional):

- `CHATBOT_ENABLE_ANTHROPIC_DIRECT=true`
- `CHATBOT_ANTHROPIC_API_KEY` or `CHATBOT_ANTHROPIC_API_KEY_SECRET_ARN`
- `CHATBOT_ANTHROPIC_MODEL_ID` (default when request does not supply `model_id`)
- `CHATBOT_ANTHROPIC_API_BASE` (default `https://api.anthropic.com`)

Bedrock model selection controls:

- `CHATBOT_ALLOWED_MODEL_IDS` (CSV; optional allow-list for request `model_id`)
- If unset, any model ID available to the account/region can be requested.

Model discovery endpoint:

- `GET /chatbot/models`
- Returns active text-capable Bedrock foundation models visible in the configured region (GovCloud), optionally filtered by `CHATBOT_ALLOWED_MODEL_IDS`.

Image generation endpoint:

- `POST /chatbot/image`
- JSON body:
  - `query` (required image prompt)
  - `model_id` (optional Bedrock image model override)
  - `size` (optional `WIDTHxHEIGHT`, defaults to `CHATBOT_IMAGE_SIZE`)
- Returns base64-encoded image payload(s) in `images`.

Conversation memory options (optional):

- `CHATBOT_MEMORY_ENABLED=true|false`
- `CHATBOT_MEMORY_TABLE=<dynamodb table name>`
- `CHATBOT_MEMORY_MAX_TURNS` (default `6`)
- `CHATBOT_MEMORY_TTL_DAYS` (default `30`)
- `CHATBOT_MEMORY_COMPACTION_CHARS` (default `12000`; writes rolling summary entries when exceeded)
- `CHATBOT_USER_REQUESTS_PER_MINUTE` (default `120`)
- `CHATBOT_CONVERSATION_REQUESTS_PER_MINUTE` (default `60`)

Memory hygiene endpoints:

- `POST /chatbot/memory/clear` with `{ "conversation_id": "..." }`
- `POST /chatbot/memory/clear-all` clears memory for the current authenticated actor scope

Chatbot observability options:

- `chatbot_observability_enabled` (Terraform; default `true`)
- `chatbot_metrics_namespace` (Terraform; optional override, defaults to `${project_name}/${environment}`)
- Lambda emits custom metrics:
  - `ChatbotRequestCount`
  - `ChatbotLatencyMs`
  - `ChatbotErrorCount`
  - `ChatbotServerErrorCount`
  - `ChatbotImageGeneratedCount`
- Runtime toggle: `CHATBOT_METRICS_ENABLED=true|false`

When enabled, Terraform provisions a CloudWatch dashboard for chatbot route-level telemetry and server-error alarms for query/image endpoints.

Optional live GitHub lookup (disabled by default):

- `chatbot_github_live_enabled=true`
- `chatbot_github_live_repos=["owner/repo", ...]`
- `chatbot_github_live_max_results=3`

When enabled, `live`/`hybrid` mode can include real-time GitHub code/doc snippets in chatbot context.

Chatbot login/auth options (Terraform `chatbot_auth_mode`):

- `token` (default): shared header tokens
- `jwt`: API Gateway JWT authorizer using company SSO/OIDC (`chatbot_jwt_issuer`, `chatbot_jwt_audience`)
- `github_oauth`: API Gateway Lambda authorizer validates GitHub OAuth bearer tokens (`Authorization: Bearer <token>`)
  - Optional org restriction: `github_oauth_allowed_orgs`

Recommended auth mode selection:

| Mode | Best for | Pros | Trade-offs |
|---|---|---|---|
| `token` | Fast local/dev smoke testing | Easiest setup, no IdP dependency | Shared secret model (not per-user identity) |
| `jwt` | Company-wide production SSO | Centralized identity/MFA and standard enterprise controls | Requires OIDC issuer + audience configuration |
| `github_oauth` | Engineering-focused bot access | Reuses GitHub/GHES identity, optional org gating | OAuth token validation path and GitHub API dependency |

Recommended defaults by environment:

- `dev`: `chatbot_auth_mode = "token"`
- `nonprod`: `chatbot_auth_mode = "jwt"` (preferred) or `"github_oauth"` for engineering pilot
- `prod`: `chatbot_auth_mode = "jwt"` for broad enterprise access; use `"github_oauth"` only for engineering-scoped deployments

Teams adapter endpoint:

- `POST /chatbot/teams`
- Request body follows Teams/Bot activity shape (uses `text`)
- Optional header auth: `X-Teams-Adapter-Token: <token>`
- Deployment is optional and **disabled by default** (`teams_adapter_enabled=false`)

Sprint report endpoint:

- `POST /reports/sprint`
- JSON body: `repo` (required), `jira_project`, `jira_jql`, `report_type` (`standup`|`sprint`), `days_back`
- Also supports EventBridge schedule trigger
- Deployment: `sprint_report_enabled=true`

Test generation endpoint:

- `POST /test-gen/generate`
- JSON body: `repo` (required), `pr_number` (required)
- Also auto-triggers via SQS from worker after PR review
- Deployment: `test_gen_enabled=true`

PR description generator endpoint:

- `POST /pr-description/generate`
- JSON body: `repo` (required), `pr_number` (required), `apply` (default `true`), `dry_run`
- Also auto-triggers via SQS from webhook receiver on PR open/synchronize
- Deployment: `pr_description_enabled=true`

## Terraform deployment

### Prerequisites

- AWS GovCloud credentials targeting `us-gov-west-1`
- Terraform >= 1.6

### Toolchain consistency (recommended)

To reduce local/CI drift, this repo includes:

- `.tool-versions` (python + terraform)
- `.python-version`

If you use `mise`/`asdf`, install pinned tools from repo root before running checks.

Quick local consistency checks:

- `make verify-toolchain`
- `make terraform-fmt-check`
- `make check`

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
- `chatbot_url`
- `sprint_report_url`
- `test_gen_url`
- `pr_description_url`
- `release_notes_url`
- `github_kb_sync_function_name`

## Local testing

### Install dependencies

- `python -m venv .venv`
- `source .venv/bin/activate`
- `pip install -r requirements.txt`

### Run unit tests

- `pytest -q`

### Verify local toolchain against repo constraints

- `make verify-toolchain`

### Generate webhook signature

- `python scripts/generate_signature.py <webhook_secret> scripts/sample_pull_request_opened.json`

### Local invoke helpers

- `python scripts/local_invoke_webhook.py`
- `python scripts/local_invoke_worker.py`
- `python scripts/smoke_test_chatbot_modes.py --url <chatbot_url>`
- `python scripts/trigger_kb_sync.py --function-name <kb_sync_function_name>`
- `python scripts/predeploy_nonprod_checks.py --tfvars infra/terraform/terraform.tfvars`

### Small local web app (chatbot UI)

This repository now includes a tiny browser UI for querying the chatbot API:

- `webapp/index.html`
- `webapp/app.js`
- `webapp/styles.css`

Run it locally:

- `python scripts/run_chatbot_webapp.py --port 8080`

Then open:

- `http://localhost:8080`

In the UI, provide:

- Chatbot URL (`chatbot_url` Terraform output)
- Auth mode (`token`, `bearer`, or `none`)
- Auth value (API token or bearer token)
- Assistant Mode (`contextual` or `general`)
- LLM Provider (`bedrock` or `anthropic_direct`)
- Optional Model ID override (for example Amazon-hosted Bedrock model IDs)
- Optional Conversation ID to retain memory across messages
- Stream-style response mode toggle

To load currently active GovCloud model options into the model picker:

- Click **Refresh GovCloud Models** in the web app.

To generate an image from the same prompt field:

- Click **Generate Image** in the web app.

Optional GitHub login in web app:

- Expand **GitHub Login (device flow, optional)**
- Set **GitHub OAuth Base URL** to your **enterprise hosted GitHub** base URL (GHES host)
- Enter your GitHub OAuth App Client ID
- Click **Login with GitHub** and complete verification on GitHub
- The app will auto-fill `bearer` auth mode/token for chatbot calls

If your environment blocks browser calls to GitHub OAuth endpoints, use manual `bearer` mode and paste a token.

> Note: if your API Gateway CORS policy does not allow `http://localhost:8080`, browser requests may fail until CORS is enabled for that origin.

> Note: local invokes still expect AWS credentials/resources for full path behavior unless mocked.

Non-prod rollout checklist for KB mode and scheduled sync:

- `docs/nonprod_kb_rollout.md`
- `docs/nonprod_predeploy_runbook.md`

## Quality gates (lint + tests)

This repository includes CI checks for pull requests and pushes to `main`:

- Ruff linting (`python -m ruff check src tests scripts`)
- Pytest unit tests (`python -m pytest -q`)
- Optional PR title convention advisory (non-blocking on pull requests)

Run the same checks locally:

- `make install`
- `make check`

## PR metadata standards

To keep merge history clean and release notes accurate, use scoped PR titles since squash-merge uses the PR title as the commit subject.

Preferred format:

- `feat(scope): short outcome`
- `fix(scope): short outcome`
- `chore(scope): short outcome`

Examples:

- `feat(reviewer): add Jira enrichment for ticket-aware findings`
- `feat(platform): add sprint report, test-gen, and PR description agents`
- `chore(ci): add lint/test and terraform quality gates`

Use the repository PR template at `.github/pull_request_template.md` to keep scope and validation checks consistent.

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
  - `jira_base_url` — e.g., `https://jira.example.com` (Data Center) or `https://yourcompany.atlassian.net` (Cloud)
  - `confluence_base_url` — e.g., `https://confluence.example.com` (Data Center) or `https://yourcompany.atlassian.net` (Cloud)
  - `email` — service account username (Data Center) or email (Cloud)
  - `api_token` — personal access token (Data Center) or API token (Cloud)
  - `platform` — `datacenter` or `cloud` (defaults to `cloud` if omitted)
2. Deploy Terraform and capture `chatbot_url` output.
3. Send requests to `POST /chatbot/query`.

Example request body:

- `{"query":"Summarize top blockers for release","jira_jql":"project=PLAT AND statusCategory!=Done","confluence_cql":"type=page AND space=ENG"}`

### Bedrock Knowledge Base retrieval modes

The chatbot can retrieve context from Bedrock Knowledge Bases and optionally fall back to live Jira/Confluence lookups:

- `live`: use Jira/Confluence API only.
- `kb`: use Bedrock Knowledge Base retrieval only.
- `hybrid` (recommended): use Knowledge Base first, fall back to live Jira/Confluence when no KB passages are found.

Terraform variables:

- `chatbot_retrieval_mode`
- `bedrock_knowledge_base_id`
- `bedrock_kb_top_k`

Response payload now includes source telemetry:

- `sources.mode`
- `sources.context_source` (`kb`, `live`, `hybrid_fallback`)
- `sources.kb_count`

### Scheduled Confluence -> Knowledge Base sync

Optional scheduled sync job normalizes Confluence page content into S3 and starts a Bedrock Knowledge Base ingestion job.

Terraform variables:

- `kb_sync_enabled`
- `bedrock_kb_data_source_id`
- `kb_sync_schedule_expression`
- `kb_sync_s3_prefix`
- `confluence_sync_cql`
- `confluence_sync_limit`

When enabled, Terraform outputs:

- `kb_sync_function_name`
- `kb_sync_documents_bucket`

### Scheduled GitHub docs -> Knowledge Base sync

Optional scheduled sync job reads documentation files from selected GitHub repos, normalizes them into S3, and starts a Bedrock Knowledge Base ingestion job.

Terraform variables:

- `github_kb_sync_enabled`
- `github_kb_data_source_id` (optional; falls back to `bedrock_kb_data_source_id`)
- `github_kb_sync_schedule_expression`
- `github_kb_sync_s3_prefix`
- `github_kb_repos`
- `github_kb_include_patterns`
- `github_kb_max_files_per_repo`

When enabled, Terraform outputs:

- `github_kb_sync_function_name`
- `kb_sync_documents_bucket`

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

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

This project defaults to **existing secret ARNs only** (`create_secrets_manager_secrets=false`).

Set these Terraform variables:

- `existing_github_webhook_secret_arn`
- `existing_github_app_private_key_secret_arn`
- `existing_github_app_ids_secret_arn` (JSON value: `{"app_id":"...","installation_id":"..."}`)
- `existing_atlassian_credentials_secret_arn`

When `chatbot_auth_mode="token"`, also set:

- `existing_chatbot_api_token_secret_arn`

When `teams_adapter_enabled=true`, also set:

- `existing_teams_adapter_token_secret_arn`

Legacy behavior is still available by setting `create_secrets_manager_secrets=true`.

## Environment/config

Worker Lambda env vars:

- `AWS_REGION=us-gov-west-1`
- `BEDROCK_AGENT_ID` (optional)
- `BEDROCK_AGENT_ALIAS_ID` (optional)
- `BEDROCK_MODEL_ID` (fallback model)
- `BEDROCK_GUARDRAIL_ID` (optional; apply guardrails on direct Bedrock model invocation)
- `BEDROCK_GUARDRAIL_VERSION` (required when `BEDROCK_GUARDRAIL_ID` is set; numeric or `DRAFT`)
- `BEDROCK_GUARDRAIL_TRACE` (optional: `ENABLED|DISABLED|ENABLED_FULL`, default `DISABLED`)
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
  - `llm_provider` (optional; defaults to `bedrock`)
  - `model_id` (optional override; validated against allow-list when configured)
  - `jira_jql` (optional)
  - `confluence_cql` (optional)
  - `retrieval_mode` (optional: `live|kb|hybrid`; defaults to `hybrid`)
  - `atlassian_session_id` (optional; brokered short-lived Atlassian credential session)
  - `atlassian_email` + `atlassian_api_token` (optional pair; only used when `CHATBOT_ATLASSIAN_USER_AUTH_ENABLED=true`)
- Response includes:
  - `answer` (assistant response; contextual mode appends a compact citations footer by default)
  - `citations` (structured source records for Jira/Confluence/KB/GitHub context)
  - `sources` (provider, retrieval, memory, and guardrail metadata)

True streaming transport (WebSocket):

- Connect to `chatbot_websocket_url` output (wss endpoint)
- Send message payloads like:
  - `{ "action": "query", "query": "...", "conversation_id": "thread-1" }`
- Server pushes provider-runtime streaming frames with `type=chunk`, then a final `type=done`

Assistant mode behavior:

- `contextual`: existing Jira/Confluence/KB/GitHub context-aware flow.
- `general`: freeform AI chat (no Jira/Confluence/KB retrieval context).

Provider behavior:

- `bedrock`: uses Bedrock runtime and supports model override (including enabled Amazon-hosted Bedrock models).

This deployment is configured as **Bedrock-only** (no direct third-party LLM API path).

Bedrock model selection controls:

- `CHATBOT_ALLOWED_MODEL_IDS` (CSV; optional allow-list for request `model_id`)
- `CHATBOT_ALLOWED_LLM_PROVIDERS` (CSV allow-list; default `bedrock`)
- If model allow-lists are unset, chatbot defaults are used as the implicit allow-list.

Context reranking controls:

- `CHATBOT_RERANK_ENABLED=true|false` (default `true`)
- `CHATBOT_RERANK_TOP_K_PER_SOURCE` (default `3`; top items kept per source before prompting)

Prompt/context safety controls:

- `CHATBOT_PROMPT_SAFETY_ENABLED=true|false` (default `true`)
- `CHATBOT_CONTEXT_SAFETY_BLOCK_REQUEST=true|false` (default `false`; when false, unsafe retrieved items are dropped)
- `CHATBOT_SAFETY_SCAN_CHAR_LIMIT` (default `8000`)
- Safety detects common prompt-injection and data-exfiltration patterns in user input and retrieved context.
- Memory/cache writes are skipped when secret-like material is detected in user/assistant text.
- API errors:
  - `unsafe_prompt_detected` (400)
  - `unsafe_context_detected` (400)
  - `data_exfiltration_attempt` (403)

Dynamic routing + budget controls:

- `CHATBOT_BUDGETS_ENABLED=true|false` (default `true`)
- `CHATBOT_BUDGET_TABLE` (optional DynamoDB table; defaults to chatbot memory table when configured)
- `CHATBOT_BUDGET_SOFT_LIMIT_USD` (default `0.25`)
- `CHATBOT_BUDGET_HARD_LIMIT_USD` (default `0.75`)
- `CHATBOT_BUDGET_TTL_DAYS` (default `90`)
- `CHATBOT_ROUTER_LOW_COST_BEDROCK_MODEL_ID` / `CHATBOT_ROUTER_HIGH_QUALITY_BEDROCK_MODEL_ID`
- `CHATBOT_MODEL_PRICING_JSON` (optional model pricing map for estimated cost accounting)
- API error: `conversation_budget_exceeded` (429)

Chatbot Bedrock guardrails (optional):

- `CHATBOT_GUARDRAIL_ID`
- `CHATBOT_GUARDRAIL_VERSION`
- `CHATBOT_GUARDRAIL_TRACE` (`enabled|disabled`, default `disabled`)
- If chatbot-specific values are unset, chatbot falls back to `BEDROCK_GUARDRAIL_ID` + `BEDROCK_GUARDRAIL_VERSION`.

Model discovery endpoint:

- `GET /chatbot/models`
- Returns active text-capable Bedrock foundation models visible in the configured region (GovCloud), optionally filtered by `CHATBOT_ALLOWED_MODEL_IDS`.

Image generation endpoint:

- `POST /chatbot/image`
- Requires `CHATBOT_IMAGE_ENABLED=true` (Terraform default is `false` to avoid image-model spend)
- JSON body:
  - `query` (required image prompt)
  - `model_id` (optional Bedrock image model override)
  - `size` (optional `WIDTHxHEIGHT`, defaults to `CHATBOT_IMAGE_SIZE`)
- Returns base64-encoded image payload(s) in `images`.

Image safety and rate controls:

- `CHATBOT_IMAGE_ENABLED=true|false` (default `false` in Terraform)
- `CHATBOT_IMAGE_SAFETY_ENABLED=true|false`
- `CHATBOT_IMAGE_BANNED_TERMS` (CSV blocked phrases)
- `CHATBOT_IMAGE_USER_REQUESTS_PER_MINUTE` (default `6`)
- `CHATBOT_IMAGE_CONVERSATION_REQUESTS_PER_MINUTE` (default `3`)

Conversation memory options (optional):

- `CHATBOT_MEMORY_ENABLED=true|false`
- `CHATBOT_MEMORY_TABLE=<dynamodb table name>`
- `CHATBOT_MEMORY_MAX_TURNS` (default `4`)
- `CHATBOT_MEMORY_TTL_DAYS` (default `30`)
- `CHATBOT_MEMORY_COMPACTION_CHARS` (default `12000`; writes rolling summary entries when exceeded)
- `CHATBOT_USER_REQUESTS_PER_MINUTE` (default `120`)
- `CHATBOT_CONVERSATION_REQUESTS_PER_MINUTE` (default `60`)
- `CHATBOT_QUOTA_FAIL_OPEN=false|true` (default `false`; recommended fail-closed behavior)

Atlassian auth mode:

- Default behavior uses shared service-account credentials from `ATLASSIAN_CREDENTIALS_SECRET_ARN`.
- Optional per-user override: set `CHATBOT_ATLASSIAN_USER_AUTH_ENABLED=true`, then send request-scoped `atlassian_email` + `atlassian_api_token` (or headers `X-Atlassian-Email` + `X-Atlassian-Api-Token`).
- If per-user override is enabled and only one credential is provided, the request is rejected.
- Optional credential broker: set `CHATBOT_ATLASSIAN_SESSION_BROKER_ENABLED=true`, then create short-lived sessions via:
  - `POST /chatbot/atlassian/session` with `atlassian_email` + `atlassian_api_token`
  - `POST /chatbot/atlassian/session/clear` with `atlassian_session_id`
- Broker still requires `CHATBOT_ATLASSIAN_USER_AUTH_ENABLED=true` because sessions encapsulate per-user Atlassian credentials.
- Broker storage uses the chatbot DynamoDB table configured by `CHATBOT_MEMORY_TABLE` (Terraform provisions it when broker mode is enabled).
- Broker TTL: `CHATBOT_ATLASSIAN_SESSION_TTL_SECONDS` (default `3600`, minimum `300`)
- Query precedence in contextual mode:
  - If `atlassian_session_id` is provided, chatbot loads server-side credentials from that session.
  - Otherwise, it falls back to request-scoped `atlassian_email` + `atlassian_api_token`.
  - Otherwise, it uses shared service-account credentials.

Response cache options (optional):

- `CHATBOT_RESPONSE_CACHE_ENABLED=true|false` (default `true`)
- `CHATBOT_RESPONSE_CACHE_TABLE=<dynamodb table name>` (optional; defaults to memory table when configured)
- `CHATBOT_RESPONSE_CACHE_TTL_SECONDS` (default `1200`)
- `CHATBOT_RESPONSE_CACHE_MIN_QUERY_LENGTH` (default `12`; short queries skip cache lookup)
- `CHATBOT_RESPONSE_CACHE_MAX_ANSWER_CHARS` (default `16000`; large answers are not cached)
- `CHATBOT_RESPONSE_CACHE_LOCK_TTL_SECONDS` (default `15`)
- `CHATBOT_RESPONSE_CACHE_LOCK_WAIT_MS` (default `150`)
- `CHATBOT_RESPONSE_CACHE_LOCK_WAIT_ATTEMPTS` (default `6`)
- Cache lookup is two-tiered: `exact` (conversation/history aware) then `faq` (cross-conversation semantic reuse).
- Cache key includes semantic-normalized query text, assistant mode, retrieval mode, provider/model, and retrieval filters; exact tier also includes conversation id + history digest.

Context budget controls:

- `CHATBOT_CONTEXT_MAX_CHARS_PER_SOURCE` (default `2500`)
- `CHATBOT_CONTEXT_MAX_TOTAL_CHARS` (default `8000`)
- Context blocks are truncated before model invocation to reduce latency/cost while preserving source diversity.

Live retrieval fanout controls:

- `CHATBOT_JIRA_MAX_RESULTS` (default `3`)
- `CHATBOT_CONFLUENCE_MAX_RESULTS` (default `3`)
- `GITHUB_CHAT_MAX_RESULTS` (default `2`)
- `BEDROCK_KB_TOP_K` (default `3`)

Memory hygiene endpoints:

- `POST /chatbot/memory/clear` with `{ "conversation_id": "..." }`
- `POST /chatbot/memory/clear-all` clears memory for the current authenticated actor scope

Atlassian session broker endpoints (optional):

- `POST /chatbot/atlassian/session` with `{ "atlassian_email": "...", "atlassian_api_token": "..." }`
  - Returns `atlassian_session_id`, `expires_at`, and `ttl_seconds`
- `POST /chatbot/atlassian/session/clear` with `{ "atlassian_session_id": "..." }`

Feedback endpoint:

- `POST /chatbot/feedback`
- JSON body:
  - `rating` (optional `1..5`)
  - `sentiment` (optional `positive|neutral|negative`; aliases `up/down` supported)
  - `comment` (optional, max 2000 chars)
  - `conversation_id` (optional)
  - `query` / `answer` (optional snapshots for offline analysis)
- Requires at least one of `rating` or `sentiment`.

Chatbot observability options:

- `chatbot_observability_enabled` (Terraform; default `true`)
- `chatbot_metrics_namespace` (Terraform; optional override, defaults to `${project_name}/${environment}`)
- Lambda emits custom metrics:
  - `ChatbotRequestCount`
  - `ChatbotLatencyMs`
  - `ChatbotErrorCount`
  - `ChatbotServerErrorCount`
  - `ChatbotImageGeneratedCount`
  - `ChatbotGuardrailOutcomeCount`
  - `ChatbotFeedbackCount`
- `ChatbotQuotaBackendErrorCount`
- `ChatbotSafetyEventCount`
- `ChatbotModelRouteCount`
- `ChatbotCacheHitCount`
- `ChatbotCacheMissCount`
- `ChatbotCacheStoreCount`
- `ChatbotContextTrimCount`
- `ChatbotSensitiveStoreSkippedCount`
- Runtime toggle: `CHATBOT_METRICS_ENABLED=true|false`

Infrastructure cost controls (Terraform defaults):

- `log_retention_days=14`
- `worker_lambda_architecture="arm64"` and `worker_lambda_memory_size=768`
- `chatbot_lambda_architecture="arm64"` and `chatbot_lambda_memory_size=384`

WebSocket streaming options:

- `chatbot_websocket_enabled` (Terraform; default `true`)
- `chatbot_websocket_stage` (Terraform; default `prod`)
- `chatbot_websocket_default_chunk_chars` (Terraform; default `120`)

When enabled, Terraform provisions a CloudWatch dashboard for chatbot route-level telemetry and server-error alarms for query/image endpoints.

Optional live GitHub lookup (disabled by default):

- `chatbot_github_live_enabled=true`
- `chatbot_github_live_repos=["owner/repo", ...]`
- `chatbot_github_live_max_results=2`

When enabled, `live`/`hybrid` mode can include real-time GitHub code/doc snippets in chatbot context.

Chatbot login/auth options (Terraform `chatbot_auth_mode`):

- `token` (default): shared header tokens
- `jwt`: API Gateway JWT authorizer using company SSO/OIDC (`chatbot_jwt_issuer`, `chatbot_jwt_audience`)
- `github_oauth`: API Gateway Lambda authorizer validates GitHub OAuth bearer tokens (`Authorization: Bearer <token>`)
  - Optional org restriction: `github_oauth_allowed_orgs`

Recommended auth mode selection:

| Mode | Best for | Pros | Trade-offs |
| --- | --- | --- | --- |
| `token` | Fast local/dev smoke testing | Easiest setup, no IdP dependency | Shared secret model (not per-user identity) |
| `jwt` | Company-wide production SSO | Centralized identity/MFA and standard enterprise controls | Requires OIDC issuer + audience configuration |
| `github_oauth` | Engineering-focused bot access | Reuses GitHub/GHES identity, optional org gating | OAuth token validation path and GitHub API dependency |

Recommended defaults by environment:

- `dev`: `chatbot_auth_mode = "token"`
- `nonprod`: `chatbot_auth_mode = "jwt"` (preferred) or `"github_oauth"` for engineering pilot
- `prod`: `chatbot_auth_mode = "jwt"` for broad enterprise access; use `"github_oauth"` only for engineering-scoped deployments
- Terraform enforces this in prod: `chatbot_auth_mode="token"` is rejected when `environment="prod"`.

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
- `webapp_url` (when `webapp_hosting_enabled=true`)
- `webapp_hosting_mode`
- `webapp_static_ip` (when `webapp_hosting_mode="ec2_eip"`)
- `webapp_https_url` (when `webapp_tls_enabled=true`)
- `webapp_tls_static_ips` (when `webapp_tls_enabled=true`)

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
- `python scripts/postdeploy_operator_report.py --terraform-dir infra/terraform --auth-mode token --auth-value <token>`

Post-deploy operator report notes:

- Pulls Terraform/OpenTofu outputs (`webhook_url`, `chatbot_url`, `webapp_url`/`webapp_https_url`)
- Performs endpoint reachability checks for webhook, chatbot query/models, and webapp UI
- Returns JSON summary with per-check status (`ok`, `warn`, `fail`) and exits non-zero only on hard failures
- Convenience target: `make postdeploy-report`

### GitHub MCP server (optional)

This repo now includes an MCP server that reuses existing GitHub App auth/client code:

- Entry point: `src/mcp_server/github_pr_server.py`
- Optional dependency file: `requirements-mcp.txt`

Additional MCP server options are available:

- `src/mcp_server/github_release_ops_server.py`
- `src/mcp_server/atlassian_context_server.py`
- `src/mcp_server/unified_context_server.py`

Install + run:

- `make install-mcp`
- `make mcp-dev-check`
- `make mcp-ec2-bootstrap` (one-command EC2 bootstrap for Podman + Kubernetes + EKS + repo MCP)
- `export GITHUB_APP_IDS_SECRET_ARN=<secret-arn>`
- `export GITHUB_APP_PRIVATE_KEY_SECRET_ARN=<secret-arn>`
- `export GITHUB_API_BASE=https://api.github.com` (or your GHES API base)
- `make mcp-github-server`

Dev stack runbook (Podman + Kubernetes + EKS + repo MCP):

- `docs/mcp-dev-stack.md`

Atlassian MCP env var:

- `export ATLASSIAN_CREDENTIALS_SECRET_ARN=<secret-arn>`

List/run server options:

- `make mcp-list`
- `make mcp-github-server`
- `make mcp-github-release-server`
- `make mcp-atlassian-server`
- `make mcp-unified-server`

Exposed MCP tools:

- `list_open_pull_requests(repo_full_name, per_page=20)`
- `get_pull_request(repo_full_name, pull_number)`
- `get_pull_request_files(repo_full_name, pull_number)`
- `search_repository_code(repo_full_name, query, per_page=10)`

Other server toolsets:

- GitHub Release/Ops:
  - `list_tags(repo_full_name, per_page=30)`
  - `get_latest_release(repo_full_name)`
  - `get_release_by_tag(repo_full_name, tag)`
  - `compare_commits(repo_full_name, base, head)`
  - `list_merged_prs_between(repo_full_name, base_sha, head_sha)`
- Atlassian Context:
  - `get_jira_issue(issue_key)`
  - `search_jira(jql, max_results=10)`
  - `get_confluence_page(page_id, body_format="storage")`
  - `search_confluence(cql, limit=10)`
  - `get_atlassian_platform()`
- Unified Context:
  - `github_list_open_pull_requests(...)`
  - `github_search_repository_code(...)`
  - `jira_search(...)`
  - `confluence_search(...)`
  - `health_context()`

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
- LLM Provider (`bedrock`)
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

### AWS-hosted web app (S3 or fixed-IP EC2)

If you want the chatbot UI hosted in AWS (instead of local only), enable Terraform-managed hosting:

- `webapp_hosting_enabled = true`
- `webapp_hosting_mode = "s3"` (default) **or** `"ec2_eip"`

S3 website mode (simple public hosting):

- `webapp_hosting_mode = "s3"`
- `webapp_bucket_name = ""` (optional explicit name; leave empty for derived default)

Fixed-IP mode for firewall allowlisting:

- `webapp_hosting_mode = "ec2_eip"`
- `webapp_ec2_subnet_id = "subnet-..."` (required)
- `webapp_ec2_allowed_cidrs = ["203.0.113.10/32"]` (recommended restrictive ingress)
- Optional: `webapp_ec2_instance_type`, `webapp_ec2_key_name`, `webapp_ec2_ami_id`

EC2 hosting behavior (important):

- Terraform uploads `webapp/index.html`, `webapp/app.js`, `webapp/styles.css`, and `webapp/config.js` to the webapp S3 bucket.
- EC2 bootstrapping (user-data) syncs those assets from S3 into nginx document root.
- Default runtime values are injected by overwriting `config.js` on-instance with Terraform-rendered defaults.
- Manual SSH edits are not recommended because they are overwritten by code-driven deployments.

Private-only VPC mode (no public IPs at all):

- `webapp_hosting_mode = "ec2_eip"`
- `webapp_private_only = true`
- `webapp_ec2_subnet_id = "subnet-private-..."`

In this mode, Terraform does **not** create public EIPs for the instance, and the app is reachable only from within your VPC/network.

HTTPS + domain-ready fixed-IP (recommended for enterprise):

- `webapp_tls_enabled = true`
- `webapp_tls_acm_certificate_arn = "arn:aws-us-gov:acm:..."`
- `webapp_tls_subnet_ids = ["subnet-a", "subnet-b"]` (public subnets for NLB)

This provisions an internet-facing NLB with static Elastic IPs and TLS termination.
Point your DNS record to the output IPs in `webapp_tls_static_ips` (or use the NLB DNS name from `webapp_https_url`).

If `webapp_private_only=true`, the NLB is internal-only and no public static IPs are created.

After `terraform apply`, use outputs:

- `webapp_url`
- `webapp_hosting_mode`
- `webapp_static_ip` (fixed-IP mode)
- `webapp_https_url` (TLS mode)
- `webapp_tls_static_ips` (TLS mode static allowlist IPs)

For strict private-only mode:

- `webapp_url` returns a private address
- `webapp_static_ip` is empty
- `webapp_tls_static_ips` is empty

Website update workflow (EC2 mode, no SSH required):

1. Update files under `webapp/` in this repo.
2. Run `terraform plan` and `terraform apply`.
3. Terraform detects asset hash changes and replaces the EC2 webapp instance (`user_data_replace_on_change=true`).
4. New instance boots, pulls latest assets from S3, and serves updated UI through nginx.

This keeps updates reproducible and avoids snowflake drift from in-place SSH edits.

Then set your chatbot API URL and auth values in the web UI settings page.

Need exact copy/paste steps for private-only deployment?

- `docs/private_vpc_webapp_runbook.md`
- `docs/private_vpc_operator_quick_card.md` (one-page fast path)

Need exact copy/paste steps for private-only deployment behind your **existing internal enterprise load balancer**?

- `docs/private_vpc_existing_lb_runbook.md`

Need a **CloudFormation** path (existing VPC/subnet, no VPC creation)?

- `docs/cloudformation_private_vpc_quickstart.md`
- `docs/cloudformation_private_vpc_internal_nlb_tls_quickstart.md` (internal NLB + TLS)

Need a single operator checklist for full rollout/signoff?

- `docs/day1_deployment_checklist.md`

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

## Prompt Regression Evals (Promptfoo)

Prompt eval suites live under `evals/promptfoo`:

- PR-review JSON/schema regressions: `evals/promptfoo/pr-review.promptfooconfig.yaml`
- Chatbot retrieval-grounding regressions: `evals/promptfoo/chatbot-rag.promptfooconfig.yaml`

Run locally (requires AWS credentials with Bedrock runtime access):

- `make promptfoo-eval-pr`
- `make promptfoo-eval-chatbot`

Optional env vars:

- `PROMPTFOO_AWS_REGION` (default `us-gov-west-1`)
- `PROMPTFOO_BEDROCK_MODEL_ID` (default `anthropic.claude-3-5-sonnet-20240620-v1:0`)

A manual GitHub Actions workflow is also included:

- `.github/workflows/prompt-evals.yml`
- Configure one credential mode in repository secrets:
  - `AWS_ROLE_TO_ASSUME` (preferred OIDC role), or
  - `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (+ optional `AWS_SESSION_TOKEN`)

## Lambda Power Tuning

Run tuning locally with an existing Lambda Power Tuning Step Functions state machine:

- `python scripts/run_lambda_power_tuning.py --state-machine-arn <arn> --function-name <lambda-name-or-arn> --region us-gov-west-1`

Useful options:

- `--strategy cost|speed|balanced`
- `--num 25`
- `--power-values 128,256,512,768,1024,1536,2048,2560,3008`
- `--payload-file payload.json` (or `--payload-json '{...}'`)

Manual workflow for repeatable runs + artifact upload:

- `.github/workflows/lambda-power-tuning.yml`
- The workflow expects an existing Lambda Power Tuning Step Functions state machine ARN as input.

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

1. Populate Secrets Manager secret `atlassian_credentials` with JSON keys: `jira_base_url`, `confluence_base_url`, `email`, `api_token`, and `platform` (`datacenter` or `cloud`, defaults to `cloud` if omitted).

2. Deploy Terraform and capture `chatbot_url` output.

3. Send requests to `POST /chatbot/query`.

Example request body:

- `{"query":"Summarize top blockers for release","jira_jql":"project=PLAT AND statusCategory!=Done","confluence_cql":"type=page AND space=ENG"}`

If you receive `401`/`403` errors from the chatbot endpoint, verify auth-mode alignment:

- `chatbot_auth_mode="token"` => client must send `X-Api-Token` (web UI auth mode `token`).
- `chatbot_auth_mode="jwt"` or `"github_oauth"` => client should use bearer auth (web UI auth mode `bearer`).

For private-VPC webapp access through enterprise firewalls, expose **443 at the internal LB** and forward to `webapp_private_ip:80` (or `webapp_instance_id:80` for instance-type target groups).

### Chatbot 503 errors

- `quota_backend_unavailable` / `dynamodb_unavailable`: Lambda cannot reach or access DynamoDB for quota/memory controls.
- `atlassian_session_store_unavailable`: session broker is enabled but DynamoDB table access/path is missing.
- Verify VPC egress/endpoints and IAM permissions for Secrets Manager, DynamoDB, Bedrock, and CloudWatch Logs.

### Bedrock Knowledge Base retrieval modes

The chatbot can retrieve context from Bedrock Knowledge Bases and optionally fall back to live Jira/Confluence lookups:

- `live`: use Jira/Confluence API only.
- `kb`: use Bedrock Knowledge Base retrieval only.
- `hybrid` (recommended): use Knowledge Base first, fall back to live Jira/Confluence when no KB passages are found.

Terraform variables:

- `chatbot_retrieval_mode`
- `bedrock_knowledge_base_id`
- `bedrock_kb_top_k`

Optional Terraform-managed KB path:

- `create_bedrock_kb_resources`
- `create_managed_bedrock_kb_role`
- `managed_bedrock_kb_role_arn` (or Terraform-managed role)
- `create_managed_bedrock_kb_opensearch_collection`
- `managed_bedrock_kb_opensearch_collection_arn` (or Terraform-managed collection)
- `managed_bedrock_kb_opensearch_vector_index_name`

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

# Complete Setup Guide

<!-- markdownlint-disable MD024 MD060 MD032 -->

This document provides detailed setup instructions for every feature in the AI PR Reviewer.
It is written for **company-hosted / self-hosted** environments:

- **GitHub Enterprise Server** (no GitHub Actions)
- **Jira Data Center / Server** (on-premises)
- **Confluence Data Center / Server** (on-premises)
- **AWS GovCloud (us-gov-west-1)**

All features also work with Atlassian Cloud and GitHub.com — see the [Cloud vs Data Center](#cloud-vs-data-center) section for the differences.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Feature Matrix — What's Shared](#feature-matrix--whats-shared)
3. [Shared Prerequisites (do these FIRST)](#shared-prerequisites-do-these-first)
4. [Feature 1: PR Reviewer (core)](#feature-1-pr-reviewer-core)
5. [Feature 2: Jira/Confluence Chatbot](#feature-2-jiraconfluence-chatbot)
6. [Feature 3: Jira-Enriched PR Reviews](#feature-3-jira-enriched-pr-reviews)
7. [Feature 4: Release Notes Generator](#feature-4-release-notes-generator)
8. [Feature 5: Confluence → KB Sync](#feature-5-confluence--kb-sync)
9. [Feature 6: Teams Adapter](#feature-6-teams-adapter)
10. [Cloud vs Data Center](#cloud-vs-data-center)
11. [Terraform Variables Reference](#terraform-variables-reference)
12. [Secrets Manager Reference](#secrets-manager-reference)
13. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```text
┌──────────────────────────────────────────────────────────────┐
│                    GitHub Enterprise Server                    │
│  (webhook fires on PR events → hits API Gateway endpoint)     │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTPS POST
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              AWS GovCloud (us-gov-west-1)                     │
│                                                               │
│  ┌─────────────────────────────────────────────┐             │
│  │          API Gateway HTTP API                │             │
│  │  POST /webhook/github      → Webhook Lambda  │             │
│  │  POST /chatbot/query       → Chatbot Lambda  │             │
│  │  POST /chatbot/teams       → Teams Lambda    │             │
│  │  POST /release-notes/gen.  → ReleaseNotes Λ  │             │
│  └────────────────┬────────────────────────────┘             │
│                   │                                           │
│  ┌────────────────▼───────────┐                              │
│  │  SQS Queue → Worker Lambda │──→ Bedrock (AI model)        │
│  │  (async PR review)         │──→ GitHub API (post review)   │
│  │                            │──→ Jira API (fetch context)   │
│  └────────────────────────────┘                              │
│                                                               │
│  Shared: KMS key, Secrets Manager, CloudWatch Logs            │
└──────────────────────────────────────────────────────────────┘
```

**No GitHub Actions required.** Everything is webhook-driven via API Gateway + Lambda.

---

## Feature Matrix — What's Shared

| Shared Asset | PR Reviewer | Chatbot | Jira in PRs | Release Notes | KB Sync | Teams | Sprint Report | Test Gen | PR Description |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **KMS key** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **API Gateway** | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| **GitHub App secrets** | ✅ | — | ✅ | ✅ | — | — | ✅ | ✅ | ✅ |
| **Atlassian credentials secret** | — | ✅ | ✅ | ✅ | ✅ | — | ✅ | — | ✅ |
| **`GitHubClient` + `GitHubAppAuth`** | ✅ | — | ✅ | ✅ | — | — | ✅ | ✅ | ✅ |
| **`AtlassianClient`** | — | ✅ | ✅ | ✅ | ✅ | — | ✅ | — | ✅ |
| **`BedrockChatClient`** | — | ✅ | — | ✅ | — | — | ✅ | ✅ | ✅ |
| **Bedrock `InvokeModel`** | ✅ | ✅ | — | ✅ | — | — | ✅ | ✅ | ✅ |
| **SQS queue + DLQ** | ✅ | — | ✅ | — | — | — | — | ✅ | ✅ |
| **DynamoDB idempotency** | ✅ | — | ✅ | — | — | — | — | — | — |
| **S3 bucket** | — | — | — | — | ✅ | — | — | — | — |

**Key takeaway:** The 4 shared prerequisites below must be completed before enabling _any_ feature.

---

## Shared Prerequisites (do these FIRST)

These resources are required by all features and are always created by Terraform (not gated behind feature flags).

### 1. AWS GovCloud Account & Credentials

- Region: `us-gov-west-1`
- Required: AWS credentials with permissions to create IAM roles, Lambda, SQS, DynamoDB, Secrets Manager, API Gateway, KMS, CloudWatch, S3
- Terraform >= 1.6.0

#### GovCloud Bedrock Model Availability

**FedRAMP/IL4/5 Authorized Models** (as of February 2026):
- ✅ **Claude Sonnet 4.5** - Latest, best quality
- ✅ **Claude 3.7 Sonnet** - High quality
- ✅ **Claude 3.5 Sonnet v1** (`anthropic.claude-3-5-sonnet-20240620-v1:0`) - **Default, recommended**
- ✅ **All Amazon Titan Models** - Lower cost options
- ❌ **NOT Available**: Claude 3 Sonnet, Claude 3 Haiku, Llama models

**Important**: Verify models are enabled in your Bedrock console at `us-gov-west-1` before deployment.

See: [AWS GovCloud Bedrock Documentation](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-bedrock.html)

#### GovCloud Image Generation Limitation

**⛔ NO Bedrock image models available in `us-gov-west-1`**:
- ❌ Amazon Titan Image Generator G1 / G1 v2
- ❌ Amazon Nova Canvas
- ❌ Stability AI (Stable Diffusion, Stable Image)

**Configuration Required**: 
- Keep `chatbot_image_enabled = false` (default)
- The `/chatbot/image` endpoint will not work in GovCloud

**Alternative for Image Generation**:
If you need image generation in GovCloud, deploy an open-source model on **SageMaker** using:
- SageMaker JumpStart (available in GovCloud)
- GPU instances (e.g., ml.g5.xlarge, availability permitting)
- Open models: Stable Diffusion XL, SDXL Turbo, or similar

Contact your AWS SA for SageMaker image generation deployment guidance.

### 1.1 Local Toolchain (recommended to avoid drift)

This repo pins recommended local versions in:

- `.tool-versions`
- `.python-version`

If you use `mise` or `asdf`, install tools from repo root, then run:

```bash
make verify-toolchain
make terraform-fmt-check
```

### 2. GitHub Enterprise Server — GitHub App

Create a **GitHub App** on your GitHub Enterprise Server instance:

| Setting | Value |
| --- | --- |
| **Homepage URL** | Anything (e.g., your team's wiki page) |
| **Webhook URL** | Will be set after first deploy (Terraform output `webhook_url`) |
| **Webhook secret** | Generate a strong random string — you'll store this in Secrets Manager |
| **Webhook events** | `Pull request` |
| **Repository permissions** | `Pull requests: Read & write`, `Contents: Read & write`, `Metadata: Read-only` |

After creation:

- Note the **App ID** and **Installation ID** (install the app on your org/repos)
- Download the **private key PEM file**

### 3. Jira & Confluence Credentials

For **Data Center / Server** (on-premises):

- A service account username with read access to Jira projects and Confluence spaces
- A **personal access token** (PAT) for that service account
- The base URLs (e.g., `https://jira.example.com`, `https://confluence.example.com`)

For **Cloud** (atlassian.net):

- A service account email address
- An **API token** from <https://id.atlassian.com/manage-profile/security/api-tokens>
- The base URL (e.g., `https://yourcompany.atlassian.net` for both Jira and Confluence)

### 4. Terraform Init & Secrets Population

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your values (see [Terraform Variables Reference](#terraform-variables-reference)).

**Critical: Set `github_api_base`** for GitHub Enterprise Server:

```hcl
# GitHub Enterprise Server
github_api_base = "https://github.example.com/api/v3"

# Or for github.com (default):
# github_api_base = "https://api.github.com"
```

Deploy infrastructure:

```bash
terraform init
terraform plan
terraform apply
```

Use **existing Secrets Manager secrets only** (default `create_secrets_manager_secrets=false`) and set ARN variables in `terraform.tfvars`:

| Variable | Contents |
| --- | --- |
| `existing_github_webhook_secret_arn` | GitHub App webhook secret string |
| `existing_github_app_private_key_secret_arn` | Full GitHub App private key PEM |
| `existing_github_app_ids_secret_arn` | JSON: `{"app_id": "12345", "installation_id": "67890"}` |
| `existing_atlassian_credentials_secret_arn` | See [Secrets Manager Reference](#secrets-manager-reference) |

If `chatbot_auth_mode="token"`, also set:

- `existing_chatbot_api_token_secret_arn`

If `teams_adapter_enabled=true`, also set:

- `existing_teams_adapter_token_secret_arn`

Legacy placeholder-secret creation is available only when `create_secrets_manager_secrets=true`:

| Secret | Contents |
| --- | --- |
| `github_webhook_secret` | Your GitHub App webhook secret string |
| `github_app_private_key_pem` | The full PEM file contents (including BEGIN/END lines) |
| `github_app_ids` | JSON: `{"app_id": "12345", "installation_id": "67890"}` |
| `atlassian_credentials` | See [Secrets Manager Reference](#secrets-manager-reference) |

Then set the **Webhook URL** in your GitHub App settings:

```text
# From Terraform output:
terraform output webhook_url
```

---

## Feature 1: PR Reviewer (core)

**What it does:** Automatically reviews pull requests using Amazon Bedrock AI models. Posts review comments back to the PR (summary + inline comments).

**Always enabled** — this is the core feature.

### Setup

1. Complete all [shared prerequisites](#shared-prerequisites-do-these-first)
2. No additional Terraform variables needed beyond shared

### Key Terraform Variables

| Variable | Description | Default |
|---|---|---|
| `bedrock_model_id` | Bedrock model for PR review (GovCloud: use 3.5/3.7/4.5 Sonnet) | `anthropic.claude-3-5-sonnet-20240620-v1:0` |
| `bedrock_agent_id` | Optional Bedrock Agent (tried first) | `""` |
| `bedrock_agent_alias_id` | Agent alias ID | `""` |
| `dry_run` | `true` = log reviews without posting | `true` |
| `review_comment_mode` | `summary_only`, `inline_best_effort`, `strict_inline` | `inline_best_effort` |
| `auto_pr_enabled` | Create autofix PRs from AI suggestions | `false` |
| `github_allowed_repos` | Restrict to specific repos (empty = all) | `[]` |

### How it works

1. GitHub fires `pull_request` webhook → API Gateway → Webhook Lambda
2. Webhook Lambda verifies `X-Hub-Signature-256`, validates event, enqueues SQS message
3. Worker Lambda consumes SQS, fetches PR metadata + files from GitHub API
4. Calls Bedrock for AI review (agent first, falls back to direct model)
5. Posts review comments back to the PR

### Verify

```bash
# Check webhook delivery in GitHub App settings → Advanced → Recent Deliveries
# Check Lambda logs in CloudWatch: /aws/lambda/<prefix>-webhook-receiver, /aws/lambda/<prefix>-pr-review-worker
```

---

## Feature 2: Jira/Confluence Chatbot

**What it does:** HTTP endpoint that answers natural language questions by querying Jira and Confluence (live, via Bedrock Knowledge Base, or hybrid).

**Terraform flag:** `chatbot_enabled = true` (default: `true`)

### Additional Setup

1. Complete all [shared prerequisites](#shared-prerequisites-do-these-first)
2. Ensure `atlassian_credentials` secret is populated (see [Secrets Manager Reference](#secrets-manager-reference))

### Key Terraform Variables

| Variable | Description | Default |
|---|---|---|
| `chatbot_enabled` | Enable/disable chatbot | `true` |
| `chatbot_model_id` | Bedrock model for chatbot | `anthropic.claude-3-sonnet-20240229-v1:0` |
| `chatbot_retrieval_mode` | `live`, `kb`, or `hybrid` | `hybrid` |
| `existing_chatbot_api_token_secret_arn` | Required when `chatbot_auth_mode="token"` | `""` |
| `bedrock_knowledge_base_id` | Required if mode is `kb` or `hybrid` | `""` |
| `bedrock_kb_top_k` | Number of KB retrieval results | `5` |

### How it works

1. Client sends `POST /chatbot/query` with JSON body
2. Chatbot Lambda queries Jira/Confluence (live or KB) for context
3. Sends context + question to Bedrock model
4. Returns AI-generated answer with source telemetry

### Verify

```bash
# Get chatbot URL from Terraform output
terraform output chatbot_url

# Test with curl (add -H "X-Api-Token: <token>" when chatbot_auth_mode="token")
curl -X POST <chatbot_url> \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the open blockers?", "jira_jql": "project=PLAT AND statusCategory!=Done", "retrieval_mode": "live"}'
```

Auth-mode alignment note:

- `chatbot_auth_mode="token"` => clients must send `X-Api-Token` (web UI auth mode `token`).
- `chatbot_auth_mode="jwt"` or `"github_oauth"` => clients should use bearer auth (web UI auth mode `bearer`).

---

## Feature 3: Jira-Enriched PR Reviews

**What it does:** The PR reviewer automatically detects Jira issue keys in PR titles, branches, and descriptions. It fetches those Jira tickets and includes them as context in the AI review prompt, so the reviewer can verify code changes align with ticket requirements.

**Always enabled when `atlassian_credentials` secret is populated.** No feature flag — it gracefully degrades if no Atlassian secret ARN is set.

### Additional Setup

1. Complete all [shared prerequisites](#shared-prerequisites-do-these-first)
2. Ensure `atlassian_credentials` secret is populated

### How it works

1. Worker Lambda extracts Jira keys (e.g., `PROJ-123`) from the PR title, branch name, and body using regex `\b([A-Z][A-Z0-9_]+-\d+)\b`
2. Fetches issue details (summary, description, status, type, priority) via Jira REST API
3. Includes Jira context in the Bedrock prompt with the rule: _"Verify code changes align with the linked Jira ticket requirements"_
4. AI review now references ticket context when commenting on the PR

### Naming Conventions

For best detection, include Jira keys in:
- **PR title:** `PROJ-123: Add user authentication`
- **Branch name:** `feature/PROJ-123-add-auth`
- **PR description:** `Closes PROJ-123, PROJ-456`

---

## Feature 4: Release Notes Generator

**What it does:** Generates categorized release notes from merged PRs between two Git tags. Optionally enriches with Jira ticket context and can auto-update GitHub Release bodies.

**Terraform flag:** `release_notes_enabled = true` (default: `false`)

### Additional Setup

1. Complete all [shared prerequisites](#shared-prerequisites-do-these-first)
2. Set `release_notes_enabled = true` in tfvars
3. Optionally set `release_notes_model_id` (falls back to `bedrock_model_id`)

### Key Terraform Variables

| Variable | Description | Default |
|---|---|---|
| `release_notes_enabled` | Enable release notes Lambda + API route | `false` |
| `release_notes_model_id` | Bedrock model (empty = use `bedrock_model_id`) | `""` |

### How it works

1. Client sends `POST /release-notes/generate` with JSON body
2. Lambda compares commits between two tags, finds all merged PRs in that range
3. Extracts Jira keys from those PRs, fetches Jira issue details
4. Sends PR list + Jira context to Bedrock with instructions to categorize
5. Returns Markdown release notes (Features / Bug Fixes / Improvements / Breaking Changes / etc.)
6. Optionally updates the GitHub Release body if `update_release: true`

### API

```bash
# Get release notes URL from Terraform output
terraform output release_notes_url

# Generate release notes for a tag
curl -X POST <release_notes_url> \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "my-org/my-repo",
    "tag": "v1.5.0",
    "previous_tag": "v1.4.0",
    "dry_run": true
  }'

# Auto-detect previous tag and update GitHub Release
curl -X POST <release_notes_url> \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "my-org/my-repo",
    "tag": "v1.5.0",
    "update_release": true
  }'
```

| Field | Required | Description |
|---|---|---|
| `repo` | Yes | `owner/repo` format |
| `tag` | Yes | Target tag (e.g., `v1.5.0`) |
| `previous_tag` | No | Base tag (auto-detected if omitted) |
| `update_release` | No | `true` to PATCH the GitHub Release body |
| `dry_run` | No | `true` to return notes without posting |

---

## Feature 5: Confluence → KB Sync

**What it does:** Scheduled Lambda that fetches Confluence pages, normalizes them to plain text, uploads to S3, and triggers Bedrock Knowledge Base ingestion.

**Terraform flag:** `kb_sync_enabled = true` (default: `false`)

### Additional Setup

1. Complete all [shared prerequisites](#shared-prerequisites-do-these-first)
2. Choose one KB path:
  - Existing KB path: create a Bedrock Knowledge Base + S3 data source, then capture IDs
  - Managed KB path: set `create_bedrock_kb_resources=true` and optionally let Terraform create role/OpenSearch collection too
3. Set variables in tfvars

### Key Terraform Variables

| Variable | Description | Default |
|---|---|---|
| `kb_sync_enabled` | Enable scheduled sync | `false` |
| `bedrock_knowledge_base_id` | KB ID | `""` |
| `bedrock_kb_data_source_id` | KB data source ID | `""` |
| `create_bedrock_kb_resources` | Terraform-manage KB + S3 data source | `false` |
| `create_managed_bedrock_kb_role` | Terraform-manage KB IAM role | `false` |
| `managed_bedrock_kb_role_arn` | Existing KB role ARN (if not creating role) | `""` |
| `create_managed_bedrock_kb_opensearch_collection` | Terraform-manage OpenSearch collection | `false` |
| `managed_bedrock_kb_opensearch_collection_arn` | Existing collection ARN (if not creating collection) | `""` |
| `managed_bedrock_kb_opensearch_vector_index_name` | Vector index name for KB storage | `bedrock-kb-default-index` |
| `kb_sync_schedule_expression` | EventBridge schedule | `rate(6 hours)` |
| `kb_sync_s3_prefix` | S3 prefix for documents | `confluence` |
| `confluence_sync_cql` | CQL to select pages | `type=page order by lastmodified desc` |
| `confluence_sync_limit` | Max pages per run | `25` |

### How it works

1. EventBridge triggers Lambda on schedule
2. Lambda queries Confluence search API with `confluence_sync_cql`
3. Fetches full page body for each result, strips HTML to plain text
4. Uploads to S3 with metadata (title, space, URL)
5. Starts Bedrock KB ingestion job

### Verify

```bash
# Manually trigger
aws lambda invoke --function-name $(terraform output -raw kb_sync_function_name) /tmp/sync_output.json
cat /tmp/sync_output.json

# Or use the helper script
python scripts/trigger_kb_sync.py --function-name $(terraform output -raw kb_sync_function_name)
```

---

## Feature 6: Teams Adapter

**What it does:** Microsoft Teams bot adapter that relays Teams messages to the chatbot endpoint.

**Terraform flag:** `teams_adapter_enabled = true` (default: `false`, requires `chatbot_enabled = true`)

### Additional Setup

1. Chatbot must be enabled and working
2. Set `teams_adapter_enabled = true`
3. Optionally set `teams_adapter_token` for auth

### Key Terraform Variables

| Variable | Description | Default |
|---|---|---|
| `teams_adapter_enabled` | Enable Teams endpoint | `false` |
| `teams_adapter_token` | Optional shared auth token | `""` |

### Verify

```bash
terraform output teams_chatbot_url
```

---

## Feature 7: Sprint/Standup Report Agent

**What it does:** Generates daily standup or sprint summary reports by combining Jira sprint data with GitHub PR/commit activity, powered by Bedrock.

**Terraform flag:** `sprint_report_enabled = true` (default: `false`)

### Additional Setup

1. Set `sprint_report_enabled = true`
2. Optionally configure scheduled reports: `sprint_report_schedule_enabled = true`
3. Set default repo and Jira project for scheduled runs

### Key Terraform Variables

| Variable | Description | Default |
|---|---|---|
| `sprint_report_enabled` | Enable sprint report Lambda | `false` |
| `sprint_report_model_id` | Model for generation (falls back to `bedrock_model_id`) | `""` |
| `sprint_report_schedule_enabled` | Enable EventBridge schedule | `false` |
| `sprint_report_schedule_expression` | Schedule expression | `cron(0 9 ? * MON-FRI *)` |
| `sprint_report_repo` | Default repo for scheduled runs | `""` |
| `sprint_report_jira_project` | Default Jira project key | `""` |
| `sprint_report_jql` | Custom JQL override | `""` |
| `sprint_report_type` | `standup` or `sprint` | `standup` |
| `sprint_report_days_back` | Days of history | `1` |

### How it works

1. Either an API call (`POST /reports/sprint`) or an EventBridge schedule triggers the Lambda.
2. Lambda queries Jira for sprint/board data using JQL and GitHub for recent PRs/commits.
3. Data is sent to Bedrock with a structured prompt to generate a standup or sprint report.
4. Report is returned as Markdown.

### Verify

```bash
terraform output sprint_report_url
curl -X POST <sprint_report_url> -H 'Content-Type: application/json' \
  -d '{"repo": "org/repo", "jira_project": "PROJ", "report_type": "standup"}'
```

---

## Feature 8: Test Generation Agent

**What it does:** After a PR review completes (or on manual trigger), generates suggested unit tests for changed files using Bedrock.

**Terraform flag:** `test_gen_enabled = true` (default: `false`)

### Additional Setup

1. Set `test_gen_enabled = true`
2. Choose delivery mode: `comment` (PR comment) or `draft_pr` (opens a draft PR with test files)
3. Auto-trigger: after the worker completes a PR review, it enqueues a test-gen job via SQS
4. Manual trigger: `POST /test-gen/generate`

### Key Terraform Variables

| Variable | Description | Default |
|---|---|---|
| `test_gen_enabled` | Enable test generation | `false` |
| `test_gen_model_id` | Model for generation (falls back to `bedrock_model_id`) | `""` |
| `test_gen_delivery_mode` | `comment` or `draft_pr` | `comment` |
| `test_gen_max_files` | Max files per PR | `10` |

### How it works

1. Worker finishes review → enqueues message to test-gen SQS queue (if `TEST_GEN_QUEUE_URL` is set).
2. Test Gen Lambda reads PR files, filters to testable source files, reads full content.
3. Sends code to Bedrock with language-aware test generation prompt.
4. Delivers results as a PR comment (collapsible) or creates a draft PR with test files.

### Verify

```bash
terraform output test_gen_url
curl -X POST <test_gen_url> -H 'Content-Type: application/json' \
  -d '{"repo": "org/repo", "pr_number": 42}'
```

---

## Feature 9: PR Description Generator

**What it does:** Automatically generates and appends an AI-powered summary section to PR descriptions using diff analysis, commit messages, and Jira context.

**Terraform flag:** `pr_description_enabled = true` (default: `false`)

### Additional Setup

1. Set `pr_description_enabled = true`
2. Auto-trigger: webhook receiver fans out to PR description SQS queue on PR open/synchronize
3. Manual trigger: `POST /pr-description/generate`

### Key Terraform Variables

| Variable | Description | Default |
|---|---|---|
| `pr_description_enabled` | Enable PR description generator | `false` |
| `pr_description_model_id` | Model for generation (falls back to `bedrock_model_id`) | `""` |

### How it works

1. Webhook receiver sends a copy of the PR event to the PR description SQS queue.
2. Lambda fetches PR metadata, diff, commit messages, and Jira context (if `ATLASSIAN_CREDENTIALS_SECRET_ARN` set).
3. Sends data to Bedrock to generate a structured description (Summary/Changes/Linked Tickets/Testing Notes).
4. Appends or replaces the section delimited by `<!-- AI-GENERATED SUMMARY START -->` and `<!-- AI-GENERATED SUMMARY END -->` in the PR body via the GitHub API.
5. On `synchronize` events, the existing AI section is replaced with an updated version.

### Verify

```bash
terraform output pr_description_url
curl -X POST <pr_description_url> -H 'Content-Type: application/json' \
  -d '{"repo": "org/repo", "pr_number": 42, "apply": true}'
```

---

## Cloud vs Data Center

The `atlassian_credentials` Secrets Manager secret includes an optional `platform` field that controls API behavior:

### Jira

| Aspect | Cloud | Data Center / Server |
|---|---|---|
| **Base URL** | `https://yourcompany.atlassian.net` | `https://jira.example.com` |
| **REST API version** | `/rest/api/3/` | `/rest/api/2/` |
| **Search endpoint** | `/rest/api/3/search/jql` | `/rest/api/2/search` |
| **Auth** | email + API token (basic auth) | username + PAT or password (basic auth) |
| **`platform` value** | `cloud` (default) | `datacenter` |

### Confluence

| Aspect | Cloud | Data Center / Server |
|---|---|---|
| **Base URL** | `https://yourcompany.atlassian.net` | `https://confluence.example.com` |
| **Page endpoint** | `/wiki/api/v2/pages/{id}` | `/rest/api/content/{id}` |
| **Search endpoint** | `/wiki/rest/api/search` | `/rest/api/search` |
| **Page expand param** | `body-format=storage` | `expand=body.storage` |
| **Auth** | email + API token (basic auth) | username + PAT or password (basic auth) |
| **`platform` value** | `cloud` (default) | `datacenter` |

### GitHub

| Aspect | GitHub.com | GitHub Enterprise Server |
|---|---|---|
| **API base** | `https://api.github.com` | `https://<hostname>/api/v3` |
| **Terraform var** | `github_api_base = "https://api.github.com"` | `github_api_base = "https://github.example.com/api/v3"` |
| **GitHub Actions** | Available but **not used** | Not required (webhook-driven) |
| **GitHub App** | Create at github.com | Create at `https://<hostname>/settings/apps` |

---

## Terraform Variables Reference

### Always Required

| Variable | Description | Example |
|---|---|---|
| `project_name` | Resource name prefix | `ai-pr-reviewer` |
| `environment` | Environment label | `prod`, `nonprod` |
| `github_api_base` | GitHub API URL | `https://github.example.com/api/v3` |
| `bedrock_model_id` | Bedrock model ID | `anthropic.claude-3-sonnet-20240229-v1:0` |

### Feature Flags

| Variable | Enables | Default |
|---|---|---|
| `chatbot_enabled` | Jira/Confluence chatbot | `true` |
| `kb_sync_enabled` | Confluence → KB sync | `false` |
| `teams_adapter_enabled` | Teams adapter | `false` |
| `release_notes_enabled` | Release notes generator | `false` |
| `sprint_report_enabled` | Sprint/standup report agent | `false` |
| `test_gen_enabled` | Test generation agent | `false` |
| `pr_description_enabled` | PR description generator | `false` |
| `webapp_hosting_enabled` | Terraform-managed chatbot web UI hosting | `false` |
| `auto_pr_enabled` | Autofix PR creation | `false` |
| `dry_run` | Skip posting (log only) | `true` |

### Static chatbot web UI hosting modes

When `webapp_hosting_enabled = true`, choose one mode:

- `webapp_hosting_mode = "s3"` for simple S3 static website hosting
- `webapp_hosting_mode = "ec2_eip"` for fixed-IP hosting (firewall allowlist friendly)

Key fixed-IP variables:

- `webapp_ec2_subnet_id` (required for `ec2_eip`)
- `webapp_ec2_allowed_cidrs` (recommended to restrict to enterprise ingress ranges)
- `webapp_ec2_instance_type`, `webapp_ec2_key_name`, `webapp_ec2_ami_id` (optional tuning)

Strict private-only mode (no public IP usage):

- `webapp_private_only = true`
- Use private subnets and private DNS routing
- No Elastic IPs are created for the webapp instance

Optional HTTPS/TLS front door for fixed-IP mode:

- `webapp_tls_enabled = true`
- `webapp_tls_acm_certificate_arn = "arn:aws-us-gov:acm:..."`
- `webapp_tls_subnet_ids = ["subnet-a", "subnet-b"]`

When enabled, Terraform provisions an internet-facing NLB with static Elastic IPs and TLS termination.
Use output `webapp_tls_static_ips` for firewall allowlisting and `webapp_https_url` for endpoint access.

When `webapp_private_only=true`, Terraform provisions an **internal** NLB and does not allocate public static IPs.

For exact operator-friendly copy/paste deployment steps, see:

- `docs/private_vpc_webapp_runbook.md`
- `docs/private_vpc_existing_lb_runbook.md`
- `docs/private_vpc_operator_quick_card.md`

For CloudFormation (existing VPC only), see:

- `docs/cloudformation_private_vpc_quickstart.md`
- `docs/cloudformation_private_vpc_internal_nlb_tls_quickstart.md`

For full Day-1 rollout and signoff tracking, use:

- `docs/day1_deployment_checklist.md`

### Full List

See `infra/terraform/variables.tf` for all 30+ variables with descriptions and defaults.

---

## Secrets Manager Reference

### `github_webhook_secret`

Plain string — the webhook secret you configured in your GitHub App.

### `github_app_private_key_pem`

The full PEM private key file content:

```text
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQ...
-----END RSA PRIVATE KEY-----
```

### `github_app_ids`

```json
{
  "app_id": "12345",
  "installation_id": "67890"
}
```

Find these in your GitHub App settings.

### `atlassian_credentials`

**For Data Center / Server (company-hosted):**

```json
{
  "jira_base_url": "https://jira.example.com",
  "confluence_base_url": "https://confluence.example.com",
  "email": "svc-ai-reviewer",
  "api_token": "your-personal-access-token",
  "platform": "datacenter"
}
```

**For Cloud (atlassian.net):**

```json
{
  "jira_base_url": "https://yourcompany.atlassian.net",
  "confluence_base_url": "https://yourcompany.atlassian.net",
  "email": "bot@yourcompany.com",
  "api_token": "your-api-token",
  "platform": "cloud"
}
```

> **Note:** For Data Center, `email` is your **username** (not an email) and `api_token` is a **personal access token or password**. The `platform` field defaults to `cloud` if omitted.

---

## Troubleshooting

### GitHub Enterprise Server: Connection refused / SSL errors

- Ensure `github_api_base` includes `/api/v3` (e.g., `https://github.example.com/api/v3`)
- Ensure the Lambda VPC/security groups can reach your GitHub Enterprise Server
- If using a private CA, add the CA cert to the Lambda layer or set `REQUESTS_CA_BUNDLE`

### Jira/Confluence: 401 Unauthorized

- **Data Center:** Verify PAT is still valid and the service account has project access
- **Cloud:** Verify the API token at <https://id.atlassian.com/manage-profile/security/api-tokens>
- Check that `platform` field in the secret matches your deployment (`cloud` vs `datacenter`)

### Chatbot: 401/403 from private web UI

- If using `chatbot_auth_mode="token"`, ensure `existing_chatbot_api_token_secret_arn` is set and the client sends `X-Api-Token`.
- Ensure `webapp_default_auth_mode` matches your backend auth mode (`token` for token mode, `bearer` for jwt/github_oauth).

### Chatbot: 503 errors

- `quota_backend_unavailable` / `dynamodb_unavailable`: DynamoDB quota or memory backend unavailable.
- `atlassian_session_store_unavailable`: Atlassian session broker enabled but table access/path missing.
- In private VPC, ensure Lambda has IAM + network path (NAT or VPC endpoints) for Secrets Manager, DynamoDB, Bedrock, and CloudWatch Logs.

### Private webapp through firewall on 443

- Expose HTTPS listener on **443** at your internal LB/NLB.
- Forward backend traffic to `webapp_private_ip:80` (or `webapp_instance_id:80` for instance target groups).
- Confirm SG/NACL allow LB-to-instance port `80` and client-to-LB port `443`.

### Jira/Confluence: 404 Not Found

- **Data Center users seeing 404 on Confluence pages:** Ensure `platform` is set to `datacenter` — Cloud uses `/wiki/api/v2/` paths that don't exist on Data Center
- **Data Center users seeing 404 on Jira search:** Ensure `platform` is set to `datacenter` — Cloud uses `/rest/api/3/search/jql` which doesn't exist on Data Center

### Jira keys not detected in PRs

- Keys must match the pattern `[A-Z][A-Z0-9_]+-\d+` (e.g., `PROJ-123`, `MY_TEAM-456`)
- Include keys in PR title, branch name, or description
- The `ATLASSIAN_CREDENTIALS_SECRET_ARN` env var must be set on the worker Lambda

### Bedrock: Model not available

- **GovCloud users**: Only Claude 3.5 Sonnet v1, Claude 3.7 Sonnet, Claude Sonnet 4.5, and Titan models have FedRAMP/IL4/5 authorization
- Verify the model is enabled in your GovCloud Bedrock console at `us-gov-west-1`
- Check that your model ID matches: `anthropic.claude-3-5-sonnet-20240620-v1:0` (default)
- Ensure IAM policy includes `bedrock:InvokeModel` permission

### Image Generation: Not working or 400 error

- **GovCloud users**: Image generation is NOT available - no Bedrock image models in `us-gov-west-1`
  - Verify `chatbot_image_enabled = false` in your Terraform configuration
  - Do NOT attempt to use `/chatbot/image` endpoint in GovCloud
  - Alternative: Deploy SageMaker JumpStart with GPU instances for open-source image models
- **Commercial AWS regions**: Verify `CHATBOT_IMAGE_ENABLED=true` in Lambda environment
  - Ensure image model is enabled in Bedrock console (e.g., Amazon Nova Canvas)
  - Check IAM permissions include `bedrock:InvokeModel` for image models

### Lambda: Timeout

- Worker Lambda has 180s timeout — increase if PRs have many files
- Chatbot Lambda has 30s — increase if Jira/Confluence responses are slow
- Check if Lambda can reach external services (GHES, Jira, Confluence) via VPC routing

### Network: Lambda can't reach GHES/Jira/Confluence

- If these are on an internal network, Lambda needs VPC configuration with:
  - Subnets that route to the internal network
  - Security groups allowing outbound HTTPS (443) to GHES/Jira/Confluence hosts
  - NAT Gateway for S3/Secrets Manager/Bedrock access (or VPC endpoints)
- Add VPC config to the Lambda resources in `main.tf`:

  ```hcl
  vpc_config {
    subnet_ids         = var.lambda_subnet_ids
    security_group_ids = var.lambda_security_group_ids
  }
  ```

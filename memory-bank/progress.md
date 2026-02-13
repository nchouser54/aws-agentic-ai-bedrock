# Progress

## Done

- [x] Initialize project
- [x] Add Bedrock Knowledge Base retrieval client (`src/shared/bedrock_kb.py`)
- [x] Add chatbot retrieval modes (`live`, `kb`, `hybrid`) with source telemetry
- [x] Add scheduled Confluence -> KB sync Lambda (`src/kb_sync/app.py`)
- [x] Add Terraform wiring for KB/chatbot mode/sync schedule and missing Atlassian secret resource
- [x] Add tests for KB client, chatbot mode routing/fallback, and sync document normalization
- [x] Pass lint and unit tests (`ruff`, `pytest`)
- [x] Add small local chatbot webapp (`webapp/*`, `scripts/run_chatbot_webapp.py`)
- [x] Add optional GitHub login (OAuth device flow) in webapp with bearer auto-fill
- [x] Enforce enterprise hosted GitHub OAuth base URL in webapp login flow
- [x] Add chatbot `general` AI mode for freeform prompts (context retrieval optional)
- [x] Add LLM provider routing (`bedrock` and optional `anthropic_direct`)
- [x] Add optional request `model_id` override with Bedrock allow-list support
- [x] Add webapp controls for assistant mode/provider/model override
- [x] Add GovCloud model discovery endpoint and webapp refresh for active Bedrock models
- [x] Add Terraform knobs for provider defaults and Anthropic direct configuration
- [x] Verify test suite after chat/provider/model updates (`174 passed`)
- [x] Add optional chatbot conversation memory (DynamoDB-backed)
- [x] Add stream-style response payload support and webapp progressive rendering
- [x] Add chatbot image generation endpoint and webapp image preview
- [x] Add Terraform wiring for chatbot memory table, IAM, and image route/env
- [x] Add tests covering stream/memory helpers and image endpoint routing
- [x] Add local toolchain pin files (`.tool-versions`, `.python-version`) for consistency
- [x] Update Makefile with venv-aware Python and Terraform validation targets
- [x] Make predeploy Terraform version checks derive minimum version from `versions.tf`
- [x] Add chatbot custom CloudWatch metrics (request, latency, error, server error, image count)
- [x] Add chatbot route-level observability alarms and CloudWatch dashboard in Terraform
- [x] Add chatbot observability docs and output (`chatbot_observability_dashboard_name`)
- [x] Add chatbot metric emission unit tests and keep suite green (`183 passed`)
- [x] Add actor-scoped chatbot memory keys and clear-memory APIs (`/chatbot/memory/clear`, `/chatbot/memory/clear-all`)
- [x] Add chatbot memory hygiene controls (summary compaction and per-user/per-conversation request quotas)
- [x] Add Terraform wiring for memory hygiene env vars, IAM delete permission, and API routes
- [x] Add chatbot tests for memory clear routes and rate-limit HTTP handling
- [x] Add image safety prompt filtering with configurable blocked phrase list
- [x] Add image route per-user and per-conversation per-minute quotas
- [x] Add Terraform variables/env wiring for image safety and quotas
- [x] Add image route tests for safety blocking and 429 quota responses
- [x] Add websocket streaming transport handler for chatbot query chunks (`action=query`)
- [x] Add Terraform websocket API resources, invoke permission, and output URL
- [x] Add websocket unit tests for chunk/done frame flow and unsupported route handling
- [x] Enforce websocket API token auth for `$connect` and query routes in chatbot lambda
- [x] Add websocket auth unit tests (unauthorized/authorized connect and unauthorized query)
- [x] Clean up README/SETUP markdown diagnostics (tables, fence spacing/language, list formatting)

## Doing

- [ ] Prepare deployment values for `bedrock_knowledge_base_id` and `bedrock_kb_data_source_id`

## Next

- [ ] Deploy Terraform changes to non-prod and verify scheduled sync + chatbot source telemetry
- [ ] Validate GitHub OAuth app settings (client ID / scopes / allowed orgs) in non-prod chatbot flow

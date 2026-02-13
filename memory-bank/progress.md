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

## Doing

- [ ] Prepare deployment values for `bedrock_knowledge_base_id` and `bedrock_kb_data_source_id`

## Next

- [ ] Deploy Terraform changes to non-prod and verify scheduled sync + chatbot source telemetry
- [ ] Validate GitHub OAuth app settings (client ID / scopes / allowed orgs) in non-prod chatbot flow

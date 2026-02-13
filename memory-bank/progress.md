# Progress

## Done

- [x] Initialize project
- [x] Add Bedrock Knowledge Base retrieval client (`src/shared/bedrock_kb.py`)
- [x] Add chatbot retrieval modes (`live`, `kb`, `hybrid`) with source telemetry
- [x] Add scheduled Confluence -> KB sync Lambda (`src/kb_sync/app.py`)
- [x] Add Terraform wiring for KB/chatbot mode/sync schedule and missing Atlassian secret resource
- [x] Add tests for KB client, chatbot mode routing/fallback, and sync document normalization
- [x] Pass lint and unit tests (`ruff`, `pytest`)

## Doing

- [ ] Prepare deployment values for `bedrock_knowledge_base_id` and `bedrock_kb_data_source_id`

## Next

- [ ] Deploy Terraform changes to non-prod and verify scheduled sync + chatbot source telemetry

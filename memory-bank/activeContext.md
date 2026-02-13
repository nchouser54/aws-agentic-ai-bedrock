# Active Context

## Current Goals

- Stabilize and deploy hybrid Jira/Confluence + Bedrock Knowledge Base chatbot retrieval.
- Enable scheduled Confluence sync into Bedrock Knowledge Base data source.
- Keep existing PR-review and Teams adapter behavior backward compatible.
- Provide an easy web chatbot access path with optional GitHub login for bearer auth.
- Enforce enterprise hosted GitHub OAuth endpoint usage in the chatbot web login flow.
- Support general AI chat mode and model/provider selection in chatbot requests.
- Allow optional direct Anthropic provider while keeping Bedrock as default.
- Expose dynamic GovCloud Bedrock model discovery for chat model selection (`GET /chatbot/models`).
- Add optional conversation memory for chatbot threads.
- Add stream-style chunked response payloads for improved UI rendering.
- Add image generation endpoint (`POST /chatbot/image`) and webapp integration.
- Execute phase-1 implementation for cross-environment toolchain consistency checks and docs.
- Implement phase-2 chatbot observability foundation (custom metrics, alarms, dashboard).
- Implement phase-3 chatbot memory hygiene (actor-scoped memory, quotas, compaction, clear-memory APIs).

## Current Blockers

- None currently; validate Bedrock KB IDs/data source IDs and enterprise hosted GitHub OAuth app client configuration in target environment before deploy.

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
- Implement phase-4 image safety and per-actor/per-conversation rate controls.
- Implement phase-5 true websocket streaming transport for chatbot responses.
- Harden websocket auth path to enforce API token checks on `$connect` and websocket query events.
- Reduce markdown diagnostics in README/SETUP to keep docs maintenance signal clean.
- Add optional AWS-hosted static webapp deployment (S3 website) with Terraform outputs.
- Add firewall-allowlist-friendly fixed-IP AWS webapp hosting mode (EC2 + Elastic IP) alongside S3 mode.
- Add optional HTTPS/domain-ready front door for fixed-IP webapp hosting using NLB + ACM + static EIPs.
- Support strict private-only webapp hosting with no public IP or public EIP allocation.
- Provide CloudFormation deploy option for private webapp into existing VPC/subnet (no VPC creation).
- Provide CloudFormation deploy option for existing VPC + internal NLB TLS private endpoint.
- Enforce existing Secrets Manager ARNs as default Terraform mode (no secret creation) for private-VPC rollouts.
- Align private-VPC docs with 443 firewall path (client -> internal LB 443, LB -> EC2 private IP 80).
- Reduce chatbot 401/403 setup drift by defaulting web UI auth mode to token unless explicitly using bearer auth flows.

## Current Blockers

- None currently; validate secret ARN values and internal LB listener/target mapping in target environment before deploy.

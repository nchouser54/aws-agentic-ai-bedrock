variable "aws_region" {
  description = "AWS region for all resources. Defaults to GovCloud us-gov-west-1."
  type        = string
  default     = "us-gov-west-1"
}

variable "project_name" {
  description = "Project name prefix for resources"
  type        = string
  default     = "ai-pr-reviewer"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention in days"
  type        = number
  default     = 30
}

variable "github_api_base" {
  description = "GitHub API base URL. Use https://api.github.com for GitHub.com or https://<hostname>/api/v3 for GitHub Enterprise Server"
  type        = string
  default     = "https://api.github.com"
}

variable "github_allowed_repos" {
  description = "Optional allow-list of GitHub repos in owner/repo format"
  type        = list(string)
  default     = []
}

variable "bedrock_agent_id" {
  description = "Optional Bedrock Agent ID"
  type        = string
  default     = ""
}

variable "bedrock_agent_alias_id" {
  description = "Optional Bedrock Agent Alias ID"
  type        = string
  default     = ""
}

variable "bedrock_model_id" {
  description = "Fallback Bedrock model ID"
  type        = string
  default     = "anthropic.claude-3-sonnet-20240229-v1:0"
}

variable "bedrock_guardrail_id" {
  description = "Optional Bedrock Guardrail identifier applied to direct InvokeModel calls (for example PR reviewer fallback)"
  type        = string
  default     = ""
}

variable "bedrock_guardrail_version" {
  description = "Bedrock Guardrail version for bedrock_guardrail_id (numeric version or DRAFT)"
  type        = string
  default     = ""
}

variable "bedrock_guardrail_trace" {
  description = "Optional Bedrock InvokeModel trace mode when guardrails are enabled"
  type        = string
  default     = "DISABLED"

  validation {
    condition     = contains(["ENABLED", "DISABLED", "ENABLED_FULL"], var.bedrock_guardrail_trace)
    error_message = "Must be one of: ENABLED, DISABLED, ENABLED_FULL."
  }
}

variable "dry_run" {
  description = "Dry-run mode for worker posting"
  type        = bool
  default     = true
}

variable "auto_pr_enabled" {
  description = "Enable autonomous remediation PR creation"
  type        = bool
  default     = false
}

variable "auto_pr_max_files" {
  description = "Maximum number of files to update in one autonomous remediation PR"
  type        = number
  default     = 5
}

variable "auto_pr_branch_prefix" {
  description = "Branch prefix for autonomous remediation PR branches"
  type        = string
  default     = "ai-autofix"
}

variable "review_comment_mode" {
  description = "PR review comment mode: summary_only, inline_best_effort, strict_inline"
  type        = string
  default     = "inline_best_effort"

  validation {
    condition     = contains(["summary_only", "inline_best_effort", "strict_inline"], var.review_comment_mode)
    error_message = "Must be one of: summary_only, inline_best_effort, strict_inline."
  }
}

variable "chatbot_enabled" {
  description = "Enable Jira/Confluence chatbot Lambda and API route"
  type        = bool
  default     = true
}

variable "chatbot_model_id" {
  description = "Bedrock model ID for Jira/Confluence chatbot"
  type        = string
  default     = "anthropic.claude-3-sonnet-20240229-v1:0"
}

variable "chatbot_guardrail_id" {
  description = "Optional Bedrock Guardrail identifier for chatbot Converse requests"
  type        = string
  default     = ""
}

variable "chatbot_guardrail_version" {
  description = "Bedrock Guardrail version for chatbot_guardrail_id (numeric version or DRAFT)"
  type        = string
  default     = ""
}

variable "chatbot_guardrail_trace" {
  description = "Optional Bedrock Converse guardrail trace mode for chatbot"
  type        = string
  default     = "disabled"

  validation {
    condition     = contains(["enabled", "disabled"], var.chatbot_guardrail_trace)
    error_message = "Must be one of: enabled, disabled."
  }
}

variable "chatbot_retrieval_mode" {
  description = "Chatbot retrieval mode: live, kb, or hybrid"
  type        = string
  default     = "hybrid"

  validation {
    condition     = contains(["live", "kb", "hybrid"], var.chatbot_retrieval_mode)
    error_message = "Must be one of: live, kb, hybrid."
  }
}

variable "chatbot_default_assistant_mode" {
  description = "Default chatbot assistant mode: contextual or general"
  type        = string
  default     = "contextual"

  validation {
    condition     = contains(["contextual", "general"], var.chatbot_default_assistant_mode)
    error_message = "Must be one of: contextual, general."
  }
}

variable "chatbot_llm_provider" {
  description = "Default chatbot LLM provider: bedrock or anthropic_direct"
  type        = string
  default     = "bedrock"

  validation {
    condition     = contains(["bedrock", "anthropic_direct"], var.chatbot_llm_provider)
    error_message = "Must be one of: bedrock, anthropic_direct."
  }
}

variable "chatbot_allowed_llm_providers" {
  description = "Allow-list of requestable chatbot providers"
  type        = list(string)
  default     = ["bedrock"]

  validation {
    condition = alltrue([
      for provider in var.chatbot_allowed_llm_providers : contains(["bedrock", "anthropic_direct"], provider)
    ])
    error_message = "chatbot_allowed_llm_providers values must be bedrock and/or anthropic_direct."
  }
}

variable "chatbot_allowed_model_ids" {
  description = "Optional allow-list of Bedrock model IDs that the chatbot may use when model_id override is supplied"
  type        = list(string)
  default     = []
}

variable "chatbot_allowed_anthropic_model_ids" {
  description = "Optional allow-list of direct Anthropic model IDs that the chatbot may use when model_id override is supplied"
  type        = list(string)
  default     = []
}

variable "chatbot_enable_anthropic_direct" {
  description = "Enable direct Anthropic API provider path in chatbot"
  type        = bool
  default     = false
}

variable "chatbot_anthropic_api_key_secret_arn" {
  description = "Optional Secrets Manager ARN containing Anthropic API key for direct provider path"
  type        = string
  default     = ""
}

variable "chatbot_anthropic_api_base" {
  description = "Base URL for direct Anthropic API provider"
  type        = string
  default     = "https://api.anthropic.com"
}

variable "chatbot_anthropic_model_id" {
  description = "Default Anthropic direct model ID used when request model_id is not provided"
  type        = string
  default     = "claude-sonnet-4-5"
}

variable "chatbot_github_live_enabled" {
  description = "Enable optional live GitHub code/doc lookup during chatbot live/hybrid fallback mode"
  type        = bool
  default     = false
}

variable "chatbot_github_live_repos" {
  description = "Repositories (owner/repo) allowed for optional live GitHub chatbot lookup"
  type        = list(string)
  default     = []
}

variable "chatbot_github_live_max_results" {
  description = "Maximum live GitHub search results used per chatbot query"
  type        = number
  default     = 3

  validation {
    condition     = var.chatbot_github_live_max_results >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_memory_enabled" {
  description = "Enable DynamoDB-backed chatbot conversation memory"
  type        = bool
  default     = false
}

variable "chatbot_atlassian_user_auth_enabled" {
  description = "Allow optional per-request Jira/Confluence user credentials override (falls back to shared service account when omitted)"
  type        = bool
  default     = false
}

variable "chatbot_memory_max_turns" {
  description = "Maximum number of recent memory turns included in each chatbot prompt"
  type        = number
  default     = 6

  validation {
    condition     = var.chatbot_memory_max_turns >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_memory_ttl_days" {
  description = "Days before stored chatbot conversation turns expire"
  type        = number
  default     = 30

  validation {
    condition     = var.chatbot_memory_ttl_days >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_memory_compaction_chars" {
  description = "Conversation character threshold that triggers summary compaction writes"
  type        = number
  default     = 12000

  validation {
    condition     = var.chatbot_memory_compaction_chars >= 2000
    error_message = "Must be at least 2000."
  }
}

variable "chatbot_user_requests_per_minute" {
  description = "Per-user request quota per minute for chatbot query endpoint"
  type        = number
  default     = 120

  validation {
    condition     = var.chatbot_user_requests_per_minute >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_conversation_requests_per_minute" {
  description = "Per-conversation request quota per minute for chatbot query endpoint"
  type        = number
  default     = 60

  validation {
    condition     = var.chatbot_conversation_requests_per_minute >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_quota_fail_open" {
  description = "Allow requests when quota backend checks fail (not recommended)"
  type        = bool
  default     = false
}

variable "chatbot_response_cache_enabled" {
  description = "Enable semantic response cache for repeated chatbot queries"
  type        = bool
  default     = false
}

variable "chatbot_response_cache_table" {
  description = "Optional DynamoDB table for chatbot response cache; defaults to chatbot memory table when available"
  type        = string
  default     = ""
}

variable "chatbot_response_cache_ttl_seconds" {
  description = "TTL in seconds for chatbot response cache entries"
  type        = number
  default     = 300

  validation {
    condition     = var.chatbot_response_cache_ttl_seconds >= 30
    error_message = "Must be at least 30."
  }
}

variable "chatbot_response_cache_min_query_length" {
  description = "Minimum query length before chatbot response cache lookup is attempted"
  type        = number
  default     = 12

  validation {
    condition     = var.chatbot_response_cache_min_query_length >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_response_cache_max_answer_chars" {
  description = "Maximum cached chatbot answer size in characters"
  type        = number
  default     = 16000

  validation {
    condition     = var.chatbot_response_cache_max_answer_chars >= 200
    error_message = "Must be at least 200."
  }
}

variable "chatbot_response_cache_lock_ttl_seconds" {
  description = "Short-lived lock TTL in seconds for response cache miss single-flight coordination"
  type        = number
  default     = 15

  validation {
    condition     = var.chatbot_response_cache_lock_ttl_seconds >= 5
    error_message = "Must be at least 5."
  }
}

variable "chatbot_response_cache_lock_wait_ms" {
  description = "Wait interval in milliseconds when another invocation is generating a cache entry"
  type        = number
  default     = 150

  validation {
    condition     = var.chatbot_response_cache_lock_wait_ms >= 50
    error_message = "Must be at least 50."
  }
}

variable "chatbot_response_cache_lock_wait_attempts" {
  description = "Number of wait-retry attempts when response cache lock is already held"
  type        = number
  default     = 6

  validation {
    condition     = var.chatbot_response_cache_lock_wait_attempts >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_rerank_enabled" {
  description = "Enable lexical reranking of retrieved context before prompting"
  type        = bool
  default     = true
}

variable "chatbot_rerank_top_k_per_source" {
  description = "Number of top reranked context items to keep per source"
  type        = number
  default     = 3

  validation {
    condition     = var.chatbot_rerank_top_k_per_source >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_prompt_safety_enabled" {
  description = "Enable prompt injection and data-exfiltration detection for chatbot queries/context"
  type        = bool
  default     = true
}

variable "chatbot_context_safety_block_request" {
  description = "Fail the request when unsafe patterns are found in retrieved context instead of dropping those items"
  type        = bool
  default     = false
}

variable "chatbot_safety_scan_char_limit" {
  description = "Maximum characters scanned per prompt/context item for safety detection"
  type        = number
  default     = 8000

  validation {
    condition     = var.chatbot_safety_scan_char_limit >= 256
    error_message = "Must be at least 256."
  }
}

variable "chatbot_context_max_chars_per_source" {
  description = "Maximum context characters per source block (Jira/Confluence/KB/GitHub) included in chatbot prompts"
  type        = number
  default     = 3500

  validation {
    condition     = var.chatbot_context_max_chars_per_source >= 256
    error_message = "Must be at least 256."
  }
}

variable "chatbot_context_max_total_chars" {
  description = "Maximum total context characters included in chatbot prompts across all sources"
  type        = number
  default     = 12000

  validation {
    condition     = var.chatbot_context_max_total_chars >= 1024
    error_message = "Must be at least 1024."
  }
}

variable "chatbot_budgets_enabled" {
  description = "Enable conversation-level budget tracking and model routing"
  type        = bool
  default     = false
}

variable "chatbot_budget_table" {
  description = "Optional DynamoDB table for budget tracking; defaults to chatbot memory table when available"
  type        = string
  default     = ""
}

variable "chatbot_budget_soft_limit_usd" {
  description = "Conversation-level soft budget limit in USD for routing toward low-cost models"
  type        = number
  default     = 0.5

  validation {
    condition     = var.chatbot_budget_soft_limit_usd >= 0
    error_message = "Must be >= 0."
  }
}

variable "chatbot_budget_hard_limit_usd" {
  description = "Conversation-level hard budget limit in USD; requests are rejected when exceeded"
  type        = number
  default     = 1.0

  validation {
    condition     = var.chatbot_budget_hard_limit_usd >= var.chatbot_budget_soft_limit_usd
    error_message = "Must be >= chatbot_budget_soft_limit_usd."
  }
}

variable "chatbot_budget_ttl_days" {
  description = "Days before conversation budget tracking records expire"
  type        = number
  default     = 90

  validation {
    condition     = var.chatbot_budget_ttl_days >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_router_low_cost_bedrock_model_id" {
  description = "Optional low-cost Bedrock model for dynamic routing"
  type        = string
  default     = ""
}

variable "chatbot_router_high_quality_bedrock_model_id" {
  description = "Optional high-quality Bedrock model override for dynamic routing"
  type        = string
  default     = ""
}

variable "chatbot_router_low_cost_anthropic_model_id" {
  description = "Optional low-cost Anthropic-direct model for dynamic routing"
  type        = string
  default     = ""
}

variable "chatbot_router_high_quality_anthropic_model_id" {
  description = "Optional high-quality Anthropic-direct model override for dynamic routing"
  type        = string
  default     = ""
}

variable "chatbot_model_pricing_json" {
  description = "Optional JSON map of model pricing used for budget cost estimation"
  type        = string
  default     = "{}"
}

variable "chatbot_image_model_id" {
  description = "Bedrock image model ID for /chatbot/image endpoint"
  type        = string
  default     = "amazon.nova-canvas-v1:0"
}

variable "chatbot_image_default_size" {
  description = "Default image size for /chatbot/image in WIDTHxHEIGHT format"
  type        = string
  default     = "1024x1024"
}

variable "chatbot_image_safety_enabled" {
  description = "Enable conservative image prompt safety filtering"
  type        = bool
  default     = true
}

variable "chatbot_image_banned_terms" {
  description = "Case-insensitive blocked phrases for image prompts"
  type        = list(string)
  default = [
    "explicit sexual",
    "nudity",
    "child sexual",
    "self-harm",
    "graphic gore",
    "extreme violence",
    "dismemberment",
  ]
}

variable "chatbot_image_user_requests_per_minute" {
  description = "Per-user image generation request quota per minute"
  type        = number
  default     = 30

  validation {
    condition     = var.chatbot_image_user_requests_per_minute >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_image_conversation_requests_per_minute" {
  description = "Per-conversation image generation request quota per minute"
  type        = number
  default     = 10

  validation {
    condition     = var.chatbot_image_conversation_requests_per_minute >= 1
    error_message = "Must be at least 1."
  }
}

variable "chatbot_observability_enabled" {
  description = "Enable chatbot custom metrics dashboard and related CloudWatch alarms"
  type        = bool
  default     = true
}

variable "chatbot_metrics_namespace" {
  description = "Optional CloudWatch metrics namespace override for chatbot custom metrics"
  type        = string
  default     = ""
}

variable "chatbot_websocket_enabled" {
  description = "Enable websocket transport for true chatbot streaming responses"
  type        = bool
  default     = true
}

variable "chatbot_websocket_stage" {
  description = "API Gateway websocket stage name for chatbot streaming transport"
  type        = string
  default     = "prod"
}

variable "chatbot_websocket_default_chunk_chars" {
  description = "Default websocket response chunk size in characters"
  type        = number
  default     = 120

  validation {
    condition     = var.chatbot_websocket_default_chunk_chars >= 20
    error_message = "Must be at least 20."
  }
}

variable "bedrock_knowledge_base_id" {
  description = "Optional Bedrock Knowledge Base ID used by chatbot and sync jobs"
  type        = string
  default     = ""
}

variable "bedrock_kb_top_k" {
  description = "Number of Knowledge Base retrieval results for chatbot queries"
  type        = number
  default     = 5

  validation {
    condition     = var.bedrock_kb_top_k >= 1
    error_message = "Must be at least 1."
  }
}

variable "kb_sync_enabled" {
  description = "Enable scheduled Confluence to Bedrock Knowledge Base sync"
  type        = bool
  default     = false
}

variable "bedrock_kb_data_source_id" {
  description = "Bedrock Knowledge Base data source ID used for ingestion sync jobs"
  type        = string
  default     = ""
}

variable "kb_sync_schedule_expression" {
  description = "EventBridge schedule expression for Confluence sync job"
  type        = string
  default     = "rate(6 hours)"

  validation {
    condition     = can(regex("^(rate|cron)\\(", var.kb_sync_schedule_expression))
    error_message = "Must start with rate( or cron(."
  }
}

variable "kb_sync_s3_prefix" {
  description = "S3 prefix where normalized Confluence documents are written"
  type        = string
  default     = "confluence"
}

variable "confluence_sync_cql" {
  description = "CQL used by the scheduled sync job when selecting Confluence pages"
  type        = string
  default     = "type=page order by lastmodified desc"
}

variable "confluence_sync_limit" {
  description = "Maximum number of Confluence search results processed per sync run"
  type        = number
  default     = 25

  validation {
    condition     = var.confluence_sync_limit >= 1
    error_message = "Must be at least 1."
  }
}

variable "github_kb_sync_enabled" {
  description = "Enable scheduled GitHub docs to Bedrock Knowledge Base sync"
  type        = bool
  default     = false
}

variable "github_kb_data_source_id" {
  description = "Optional Bedrock Knowledge Base data source ID for GitHub docs ingestion (falls back to bedrock_kb_data_source_id)"
  type        = string
  default     = ""
}

variable "github_kb_sync_schedule_expression" {
  description = "EventBridge schedule expression for GitHub docs sync job"
  type        = string
  default     = "rate(6 hours)"

  validation {
    condition     = can(regex("^(rate|cron)\\(", var.github_kb_sync_schedule_expression))
    error_message = "Must start with rate( or cron(."
  }
}

variable "github_kb_sync_s3_prefix" {
  description = "S3 prefix where normalized GitHub docs are written"
  type        = string
  default     = "github"
}

variable "github_kb_repos" {
  description = "List of GitHub repositories (owner/repo) to sync into the Knowledge Base"
  type        = list(string)
  default     = []
}

variable "github_kb_include_patterns" {
  description = "Glob-like file patterns to include for GitHub KB sync"
  type        = list(string)
  default     = ["README.md", "docs/**", "**/*.md"]
}

variable "github_kb_max_files_per_repo" {
  description = "Maximum number of files synced per repository run"
  type        = number
  default     = 200

  validation {
    condition     = var.github_kb_max_files_per_repo >= 1
    error_message = "Must be at least 1."
  }
}

variable "teams_adapter_enabled" {
  description = "Enable Microsoft Teams adapter endpoint"
  type        = bool
  default     = false
}

variable "teams_adapter_token" {
  description = "Optional shared token required in X-Teams-Adapter-Token header"
  type        = string
  default     = ""
  sensitive   = true
}

variable "chatbot_api_token" {
  description = "Optional shared API token required in X-Api-Token header for the chatbot endpoint"
  type        = string
  default     = ""
  sensitive   = true
}

variable "chatbot_auth_mode" {
  description = "Authentication mode for chatbot routes: token, jwt, or github_oauth"
  type        = string
  default     = "token"

  validation {
    condition     = contains(["token", "jwt", "github_oauth"], var.chatbot_auth_mode)
    error_message = "Must be one of: token, jwt, github_oauth."
  }
}

variable "chatbot_jwt_issuer" {
  description = "OIDC issuer URL for JWT authorizer when chatbot_auth_mode=jwt"
  type        = string
  default     = ""
}

variable "chatbot_jwt_audience" {
  description = "JWT audience values for chatbot JWT authorizer when chatbot_auth_mode=jwt"
  type        = list(string)
  default     = []
}

variable "github_oauth_allowed_orgs" {
  description = "Optional GitHub org allow-list for github_oauth auth mode. Empty means any authenticated GitHub user token."
  type        = list(string)
  default     = []
}

variable "webapp_default_chatbot_url" {
  description = "Optional default chatbot URL pre-filled in EC2-hosted web UI. When empty, defaults to this stack's /chatbot/query endpoint."
  type        = string
  default     = ""
}

variable "webapp_default_auth_mode" {
  description = "Default auth mode pre-filled in EC2-hosted web UI (token, bearer, or none)."
  type        = string
  default     = "bearer"

  validation {
    condition     = contains(["token", "bearer", "none"], var.webapp_default_auth_mode)
    error_message = "webapp_default_auth_mode must be one of: token, bearer, none."
  }
}

variable "webapp_default_github_oauth_base_url" {
  description = "Optional default GitHub OAuth base URL pre-filled in web UI (for device flow), e.g. https://github.company.mil"
  type        = string
  default     = ""
}

variable "webapp_default_github_client_id" {
  description = "Optional default GitHub OAuth app client ID pre-filled in web UI"
  type        = string
  default     = ""
}

variable "webapp_default_github_scope" {
  description = "Default GitHub OAuth scope pre-filled in web UI"
  type        = string
  default     = "read:user read:org"
}

variable "alarm_sns_topic_arn" {
  description = "Optional SNS topic ARN for CloudWatch alarm notifications. Alarms are created only when set."
  type        = string
  default     = ""
}

variable "release_notes_enabled" {
  description = "Enable the release notes generator Lambda and API route"
  type        = bool
  default     = false
}

variable "release_notes_model_id" {
  description = "Bedrock model ID for release notes generation (falls back to bedrock_model_id)"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Sprint Report Agent
# ---------------------------------------------------------------------------

variable "sprint_report_enabled" {
  description = "Enable the sprint/standup report generator Lambda and API route"
  type        = bool
  default     = false
}

variable "sprint_report_model_id" {
  description = "Bedrock model ID for sprint report generation (falls back to bedrock_model_id)"
  type        = string
  default     = ""
}

variable "sprint_report_schedule_enabled" {
  description = "Enable EventBridge scheduled sprint reports"
  type        = bool
  default     = false
}

variable "sprint_report_schedule_expression" {
  description = "EventBridge schedule expression for automated sprint reports"
  type        = string
  default     = "cron(0 9 ? * MON-FRI *)"

  validation {
    condition     = can(regex("^(rate|cron)\\(", var.sprint_report_schedule_expression))
    error_message = "Must start with rate( or cron(."
  }
}

variable "sprint_report_repo" {
  description = "Default repo (owner/repo) for scheduled sprint reports"
  type        = string
  default     = ""
}

variable "sprint_report_jira_project" {
  description = "Default Jira project key for scheduled sprint reports"
  type        = string
  default     = ""
}

variable "sprint_report_jql" {
  description = "Optional custom JQL for scheduled sprint reports (overrides default)"
  type        = string
  default     = ""
}

variable "sprint_report_type" {
  description = "Default report type: standup or sprint"
  type        = string
  default     = "standup"

  validation {
    condition     = contains(["standup", "sprint"], var.sprint_report_type)
    error_message = "Must be one of: standup, sprint."
  }
}

variable "sprint_report_days_back" {
  description = "Number of days to look back for activity in scheduled reports"
  type        = number
  default     = 1
}

# ---------------------------------------------------------------------------
# Test Generation Agent
# ---------------------------------------------------------------------------

variable "test_gen_enabled" {
  description = "Enable the test generation agent Lambda, SQS queue, and API route"
  type        = bool
  default     = false
}

variable "test_gen_model_id" {
  description = "Bedrock model ID for test generation (falls back to bedrock_model_id)"
  type        = string
  default     = ""
}

variable "test_gen_delivery_mode" {
  description = "How to deliver generated tests: comment or draft_pr"
  type        = string
  default     = "comment"

  validation {
    condition     = contains(["comment", "draft_pr"], var.test_gen_delivery_mode)
    error_message = "Must be one of: comment, draft_pr."
  }
}

variable "test_gen_max_files" {
  description = "Maximum number of files to generate tests for per PR"
  type        = number
  default     = 10
}

# ---------------------------------------------------------------------------
# PR Description Generator
# ---------------------------------------------------------------------------

variable "pr_description_enabled" {
  description = "Enable the PR description generator Lambda, SQS queue, and API route"
  type        = bool
  default     = false
}

variable "pr_description_model_id" {
  description = "Bedrock model ID for PR description generation (falls back to bedrock_model_id)"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Static Web App Hosting
# ---------------------------------------------------------------------------

variable "webapp_hosting_enabled" {
  description = "Enable Terraform-managed static chatbot webapp deployment"
  type        = bool
  default     = false
}

variable "webapp_hosting_mode" {
  description = "Hosting mode for static chatbot webapp: s3 or ec2_eip"
  type        = string
  default     = "s3"

  validation {
    condition     = contains(["s3", "ec2_eip"], var.webapp_hosting_mode)
    error_message = "Must be one of: s3, ec2_eip."
  }
}

variable "webapp_bucket_name" {
  description = "Optional explicit S3 bucket name for static webapp hosting (must be globally unique)"
  type        = string
  default     = ""
}

variable "webapp_ec2_subnet_id" {
  description = "Subnet ID for EC2 static webapp instance when webapp_hosting_mode=ec2_eip"
  type        = string
  default     = ""
}

variable "webapp_ec2_instance_type" {
  description = "EC2 instance type for static webapp hosting when webapp_hosting_mode=ec2_eip"
  type        = string
  default     = "t3.micro"
}

variable "webapp_ec2_allowed_cidrs" {
  description = "CIDR blocks allowed to reach EC2-hosted static webapp over HTTP"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "webapp_ec2_key_name" {
  description = "Optional EC2 key pair name for SSH access to webapp instance"
  type        = string
  default     = ""
}

variable "webapp_ec2_ami_id" {
  description = "Optional AMI ID override for EC2 static webapp hosting (defaults to latest Amazon Linux 2 x86_64)"
  type        = string
  default     = ""
}

variable "webapp_private_only" {
  description = "When true, deploy EC2-hosted webapp as private-only within VPC (no public IPs or Elastic IPs)"
  type        = bool
  default     = false
}

variable "webapp_tls_enabled" {
  description = "Enable HTTPS termination for EC2-hosted static webapp using an internet-facing NLB and ACM certificate"
  type        = bool
  default     = false
}

variable "webapp_tls_acm_certificate_arn" {
  description = "ACM certificate ARN for HTTPS listener when webapp_tls_enabled=true"
  type        = string
  default     = ""
}

variable "webapp_tls_subnet_ids" {
  description = "Public subnet IDs for NLB static-IP subnet mappings when webapp_tls_enabled=true"
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------
# Observability & Lambda guardrails
# ---------------------------------------------------------------------------

variable "lambda_tracing_enabled" {
  description = "Enable AWS X-Ray active tracing on all Lambda functions"
  type        = bool
  default     = true
}

variable "lambda_reserved_concurrency_worker" {
  description = "Reserved concurrent executions for SQS-triggered worker Lambdas (pr-review, test-gen, pr-description). Set to -1 for unreserved."
  type        = number
  default     = 10
}

variable "lambda_reserved_concurrency_chatbot" {
  description = "Reserved concurrent executions for chatbot Lambda. Set to -1 for unreserved."
  type        = number
  default     = 20
}

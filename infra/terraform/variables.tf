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

variable "chatbot_retrieval_mode" {
  description = "Chatbot retrieval mode: live, kb, or hybrid"
  type        = string
  default     = "hybrid"

  validation {
    condition     = contains(["live", "kb", "hybrid"], var.chatbot_retrieval_mode)
    error_message = "Must be one of: live, kb, hybrid."
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

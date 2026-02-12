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

variable "teams_adapter_enabled" {
  description = "Enable Microsoft Teams adapter endpoint"
  type        = bool
  default     = true
}

variable "teams_adapter_token" {
  description = "Optional shared token required in X-Teams-Adapter-Token header"
  type        = string
  default     = ""
  sensitive   = true
}

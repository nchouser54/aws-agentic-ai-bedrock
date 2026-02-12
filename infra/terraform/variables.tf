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

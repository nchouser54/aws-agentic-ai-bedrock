# ===========================================================================
# AI PR Reviewer — Private VPC Deployment Configuration
# ===========================================================================
# This is your REAL terraform.tfvars file for private VPC deployment.
# Simply fill in the <REPLACE_ME> placeholders with your actual values.
#
# Pre-configured for:
#   ✓ Private VPC (no public IPs)
#   ✓ Internal NLB with TLS (optional)
#   ✓ AWS GovCloud us-gov-west-1
#   ✓ Existing security groups
#   ✓ Safe dry_run mode enabled
# ===========================================================================

# ── Core Environment ──────────────────────────────────────────────────────
aws_region         = "us-gov-west-1"
project_name       = "ai-pr-reviewer"
environment        = "nonprod"              # Change to "prod" when ready
log_retention_days = 14

# ── GitHub Configuration ──────────────────────────────────────────────────
github_api_base = "https://<REPLACE_ME_GHES_HOST>/api/v3"  # Or https://api.github.com for public GitHub

github_allowed_repos = [
  # "your-org/your-repo",
  # Leave empty to allow all repos where the app is installed
]

# ── Bedrock AI Models (GovCloud FedRAMP/IL4/5 Authorized) ────────────────
# ✓ Available: Claude 3.5 Sonnet v1, Claude 3.7 Sonnet, Claude Sonnet 4.5, Titan models
# ✗ NOT in GovCloud: Claude 3 Sonnet, Claude 3 Haiku, Llama models
bedrock_model_id       = "anthropic.claude-3-5-sonnet-20240620-v1:0"
chatbot_model_id       = "anthropic.claude-3-5-sonnet-20240620-v1:0"
bedrock_agent_id       = ""  # Optional: Bedrock Agent ID
bedrock_agent_alias_id = ""  # Optional: Bedrock Agent Alias

# ── Safety & Testing ──────────────────────────────────────────────────────
dry_run = true  # KEEP TRUE for first deployment, then set false after verification

# ── Secrets Manager (Existing Secrets Only) ───────────────────────────────
create_secrets_manager_secrets = false

# REQUIRED: GitHub webhook secret (plain string)
existing_github_webhook_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# REQUIRED: GitHub App private key (PEM format with headers)
existing_github_app_private_key_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# REQUIRED: GitHub App IDs (JSON: {"app_id":"12345","installation_id":"67890"})
existing_github_app_ids_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# REQUIRED: Atlassian credentials (JSON with jira_base_url, confluence_base_url, email, api_token, platform)
existing_atlassian_credentials_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# REQUIRED if using chatbot_auth_mode="token" (plain string token)
existing_chatbot_api_token_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# OPTIONAL: Only needed if teams_adapter_enabled=true
existing_teams_adapter_token_secret_arn = ""

# ── Chatbot Configuration ─────────────────────────────────────────────────
chatbot_enabled                = true
chatbot_retrieval_mode         = "hybrid"        # live | kb | hybrid
chatbot_default_assistant_mode = "contextual"
chatbot_llm_provider           = "bedrock"

# Authentication mode: "token" is easiest to start, switch to "jwt" or "github_oauth" later
chatbot_auth_mode         = "token"
chatbot_jwt_issuer        = ""
chatbot_jwt_audience      = []
github_oauth_allowed_orgs = []

# Optional model allowlists (empty = allow all)
chatbot_allowed_llm_providers = ["bedrock"]
chatbot_allowed_model_ids     = []

# Image generation - WARNING: NOT AVAILABLE IN GOVCLOUD
# Amazon Titan Image, Nova Canvas, Stability AI are NOT in GovCloud
chatbot_image_enabled = false  # MUST be false for GovCloud

# ── Private Webapp Hosting (EC2 in VPC) ───────────────────────────────────
webapp_hosting_enabled = true
webapp_hosting_mode    = "ec2_eip"
webapp_private_only    = true  # No public IP/EIP

# REQUIRED: Subnet for EC2 webapp instance
webapp_ec2_subnet_id     = "subnet-<REPLACE_ME>"
webapp_ec2_private_ip    = "10.<REPLACE_ME>.<REPLACE_ME>.<REPLACE_ME>"  # Optional but recommended
webapp_ec2_instance_type = "t3.micro"
webapp_ec2_key_name      = ""  # Optional: SSH key pair name

# RECOMMENDED: Use your existing all-all security group
webapp_ec2_security_group_id = "sg-<REPLACE_ME>"

# Only used if webapp_ec2_security_group_id is empty (Terraform creates SG)
webapp_ec2_allowed_cidrs = [
  "10.0.0.0/8",
  "172.16.0.0/12",
  "192.168.0.0/16"
]

# Keep in sync with chatbot_auth_mode above
webapp_default_auth_mode = "token"

# ── Internal HTTPS/TLS Load Balancer (Uncomment to Enable) ───────────────
# Users will connect to HTTPS/443 on internal NLB, which forwards to EC2:80

# webapp_tls_enabled             = true
# webapp_tls_acm_certificate_arn = "arn:aws-us-gov:acm:us-gov-west-1:<ACCOUNT_ID>:certificate/<REPLACE_ME>"
# webapp_tls_subnet_ids = [
#   "subnet-<REPLACE_ME_A>",
#   "subnet-<REPLACE_ME_B>"
# ]

# Optional: Fixed internal NLB IPs for firewall allowlisting (1:1 with webapp_tls_subnet_ids)
# webapp_tls_private_ips = [
#   "10.<REPLACE_ME>.<REPLACE_ME>.<REPLACE_ME>",
#   "10.<REPLACE_ME>.<REPLACE_ME>.<REPLACE_ME>"
# ]

# ── PR Review Behavior ────────────────────────────────────────────────────
auto_pr_enabled       = false
auto_pr_max_files     = 5
auto_pr_branch_prefix = "ai-autofix"
review_comment_mode   = "inline_best_effort"

# ── Bedrock Guardrails (Optional) ─────────────────────────────────────────
bedrock_guardrail_id      = ""  # Global guardrail for PR reviews
bedrock_guardrail_version = ""  # Version number or "DRAFT"
bedrock_guardrail_trace   = "DISABLED"

chatbot_guardrail_id      = ""  # Chatbot-specific guardrail
chatbot_guardrail_version = ""
chatbot_guardrail_trace   = "disabled"

create_bedrock_guardrail_resources = false  # Set true if you want Terraform to create guardrails
create_chatbot_guardrail_resources = false

# ── Chatbot Advanced Settings ────────────────────────────────────────────
chatbot_atlassian_user_auth_enabled      = false
chatbot_atlassian_session_broker_enabled = false
chatbot_atlassian_session_ttl_seconds    = 3600
chatbot_quota_fail_open                  = false

# Response caching
chatbot_response_cache_enabled          = true
chatbot_response_cache_table            = ""
chatbot_response_cache_ttl_seconds      = 1200
chatbot_response_cache_min_query_length = 12
chatbot_response_cache_max_answer_chars = 16000

# Reranking & context
chatbot_rerank_enabled             = true
chatbot_rerank_top_k_per_source    = 3
chatbot_context_max_chars_per_source = 2500
chatbot_context_max_total_chars      = 8000

# Safety scanning
chatbot_prompt_safety_enabled         = true
chatbot_context_safety_block_request  = false
chatbot_safety_scan_char_limit        = 8000

# Budget controls (per conversation)
chatbot_budgets_enabled        = true
chatbot_budget_table           = ""
chatbot_budget_soft_limit_usd  = 0.25
chatbot_budget_hard_limit_usd  = 0.75
chatbot_budget_ttl_days        = 90

# Knowledge base limits
chatbot_jira_max_results       = 3
chatbot_confluence_max_results = 3

# Model routing (optional)
chatbot_router_low_cost_bedrock_model_id      = "amazon.nova-lite-v1:0"
chatbot_router_high_quality_bedrock_model_id = ""
chatbot_model_pricing_json                   = "{}"

# Image generation rate limits (not used in GovCloud)
chatbot_image_user_requests_per_minute         = 6
chatbot_image_conversation_requests_per_minute = 3

# ── Lambda Configuration ──────────────────────────────────────────────────
worker_lambda_architecture  = "arm64"
worker_lambda_memory_size   = 768
chatbot_lambda_architecture = "arm64"
chatbot_lambda_memory_size  = 384

lambda_tracing_enabled              = true
lambda_reserved_concurrency_worker  = 10
lambda_reserved_concurrency_chatbot = 20

# ── Knowledge Base (Optional) ─────────────────────────────────────────────
kb_sync_enabled = false

# If using existing Bedrock KB
bedrock_knowledge_base_id    = ""
bedrock_kb_data_source_id    = ""
kb_sync_s3_prefix            = "confluence-docs"
confluence_sync_cql          = "type=page order by lastmodified desc"
confluence_sync_limit        = 25
kb_sync_schedule_expression  = "rate(6 hours)"

# If creating managed Bedrock KB with Terraform
create_managed_bedrock_kb                      = false
managed_bedrock_kb_name                        = "pr-reviewer-kb"
create_managed_bedrock_kb_role                 = false
managed_bedrock_kb_role_arn                    = ""
managed_bedrock_kb_role_name                   = "bedrock-kb-service-role"
create_managed_bedrock_kb_opensearch_collection = false
managed_bedrock_kb_opensearch_collection_name   = "bedrock-kb"
managed_bedrock_kb_opensearch_allow_public      = false
managed_bedrock_kb_embedding_model_arn          = "arn:aws-us-gov:bedrock:us-gov-west-1::foundation-model/amazon.titan-embed-text-v2:0"
managed_bedrock_kb_opensearch_collection_arn    = ""
managed_bedrock_kb_opensearch_vector_index_name = "bedrock-kb-default-index"
managed_bedrock_kb_vector_field                 = "bedrock-knowledge-base-default-vector"
managed_bedrock_kb_text_field                   = "AMAZON_BEDROCK_TEXT_CHUNK"
managed_bedrock_kb_metadata_field               = "AMAZON_BEDROCK_METADATA"
managed_bedrock_kb_data_source_name             = "primary-s3"

# ── GitHub Knowledge Base (Optional) ──────────────────────────────────────
github_kb_sync_enabled             = false
github_kb_data_source_id           = ""
github_kb_repos                    = []
github_kb_include_patterns         = []
github_kb_max_files_per_repo       = 100
github_kb_sync_s3_prefix           = "github-docs"
github_kb_sync_schedule_expression = "rate(6 hours)"

# ── Optional Features (Enable as Needed) ──────────────────────────────────
teams_adapter_enabled  = false
release_notes_enabled  = false
sprint_report_enabled  = false
test_gen_enabled       = false
pr_description_enabled = false

# Release notes configuration
release_notes_model_id = ""
release_notes_repo     = ""

# Sprint report configuration
sprint_report_model_id   = ""
sprint_report_repo       = ""
sprint_report_jira_project = ""
sprint_report_jql          = ""
sprint_report_type         = "markdown"
sprint_report_days_back    = 14

# Test generation configuration
test_gen_model_id      = ""
test_gen_delivery_mode = "comment"
test_gen_max_files     = 5

# PR description configuration
pr_description_model_id = ""

# ===========================================================================
# Deployment Steps:
# 1. Fill in all <REPLACE_ME> values above
# 2. Run: terraform init
# 3. Run: terraform plan (review changes)
# 4. Run: terraform apply (with dry_run=true for first deploy)
# 5. Test the deployment
# 6. Set dry_run=false and run terraform apply again
# ===========================================================================

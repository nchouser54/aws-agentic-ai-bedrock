# ===============================================================
# REAL DEPLOYMENT INPUT FILE (single file to fill out)
# Path: infra/terraform/terraform.tfvars
# ===============================================================
# Fill every <REPLACE_ME> value and deploy.
# This configuration is opinionated for private VPC + internal HTTPS (443)
# and uses EXISTING Secrets Manager secrets only.

# -------------------------------
# Core environment
# -------------------------------
aws_region         = "us-gov-west-1"
project_name       = "ai-pr-reviewer"
environment        = "nonprod" # change to prod when ready
log_retention_days = 14

# -------------------------------
# GitHub / PR review core
# -------------------------------
github_api_base = "https://<REPLACE_ME_GHES_HOST>/api/v3" # or https://api.github.com
github_allowed_repos = [
  # "org/repo"
]

# -------------------------------
# Model settings
# -------------------------------
# GovCloud FedRAM/IL4/5 authorized models: Claude 3.5 Sonnet v1, Claude 3.7 Sonnet, Claude Sonnet 4.5, Titan models
# NOT available in GovCloud: Claude 3 Sonnet, Claude 3 Haiku, Llama models
bedrock_model_id       = "anthropic.claude-3-5-sonnet-20240620-v1:0"
bedrock_agent_id       = ""
bedrock_agent_alias_id = ""

dry_run = true # set false after nonprod verification

# -------------------------------
# EXISTING Secrets Manager only
# -------------------------------
create_secrets_manager_secrets = false

# REQUIRED: GitHub webhook secret string (plain string secret)
existing_github_webhook_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# REQUIRED: GitHub App private key PEM secret
# Secret value must include full PEM:
# -----BEGIN PRIVATE KEY-----
# ...
# -----END PRIVATE KEY-----
existing_github_app_private_key_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# REQUIRED: GitHub App IDs JSON secret
# Secret value JSON format:
# {"app_id":"12345","installation_id":"67890"}
existing_github_app_ids_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# REQUIRED: Atlassian credentials JSON secret
# Secret value JSON format:
# {
#   "jira_base_url": "https://jira.example.com",
#   "confluence_base_url": "https://confluence.example.com",
#   "email": "svc-account-or-email",
#   "api_token": "<token>",
#   "platform": "datacenter"
# }
# Use "platform": "cloud" for Atlassian Cloud.
existing_atlassian_credentials_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# REQUIRED because chatbot_auth_mode="token" below.
# Secret value is plain string token used in X-Api-Token.
existing_chatbot_api_token_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:<ACCOUNT_ID>:secret:<REPLACE_ME>"

# OPTIONAL: only needed when teams_adapter_enabled=true
existing_teams_adapter_token_secret_arn = ""

# -------------------------------
# Chatbot defaults (ON)
# -------------------------------
chatbot_enabled                = true
chatbot_model_id               = "anthropic.claude-3-5-sonnet-20240620-v1:0" # GovCloud FedRAMP/IL4/5 authorized
chatbot_retrieval_mode         = "hybrid"                                    # live | kb | hybrid
chatbot_default_assistant_mode = "contextual"
chatbot_llm_provider           = "bedrock"

chatbot_auth_mode         = "token" # easiest to start; switch to jwt/github_oauth later
chatbot_jwt_issuer        = ""
chatbot_jwt_audience      = []
github_oauth_allowed_orgs = []

# Keep UI auth aligned with chatbot_auth_mode to avoid 401/403.
webapp_default_auth_mode = "token"

# Optional model allowlists
chatbot_allowed_llm_providers = ["bedrock"]
chatbot_allowed_model_ids     = []

# -------------------------------
# Private webapp hosting (ON)
# -------------------------------
webapp_hosting_enabled = true
webapp_hosting_mode    = "ec2_eip"
webapp_private_only    = true

# REQUIRED: private subnet for EC2 webapp host
webapp_ec2_subnet_id     = "subnet-<REPLACE_ME>"
webapp_ec2_private_ip    = "10.<REPLACE_ME>.<REPLACE_ME>.<REPLACE_ME>" # optional but recommended if you need stable backend IP
webapp_ec2_instance_type = "t3.micro"
webapp_ec2_key_name      = ""
webapp_ec2_ami_id        = ""

# OPTIONAL: Use existing all-all security group instead of creating one
# Example: webapp_ec2_security_group_id = "sg-0123456789abcdef0"
webapp_ec2_security_group_id = ""

# Restrict to enterprise ranges / ingress path (only used if webapp_ec2_security_group_id is empty)
webapp_ec2_allowed_cidrs = [
  "10.0.0.0/8",
  "172.16.0.0/12",
  "192.168.0.0/16"
]

# Internal TLS front door (ON) => clients connect to internal LB on 443
webapp_tls_enabled             = true
webapp_tls_acm_certificate_arn = "arn:aws-us-gov:acm:us-gov-west-1:<ACCOUNT_ID>:certificate/<REPLACE_ME>"
webapp_tls_subnet_ids = [
  "subnet-<REPLACE_ME_A>",
  "subnet-<REPLACE_ME_B>"
]

# Optional fixed INTERNAL NLB private IPs for direct firewall allowlisting on HTTPS/443.
# If set, must be 1:1 with webapp_tls_subnet_ids above (same order).
webapp_tls_private_ips = [
  "10.<REPLACE_ME>.<REPLACE_ME>.<REPLACE_ME>",
  "10.<REPLACE_ME>.<REPLACE_ME>.<REPLACE_ME>"
]

# -------------------------------
# Feature toggles (core easy setup)
# -------------------------------
teams_adapter_enabled = false

kb_sync_enabled = false
# For chatbot_retrieval_mode="hybrid":
# - Set bedrock_knowledge_base_id to enable KB retrieval in hybrid mode.
# - If left empty, hybrid gracefully falls back to live retrieval.
# For kb_sync_enabled=true, BOTH values below are required.
bedrock_knowledge_base_id = ""
bedrock_kb_data_source_id = ""

# Optional: create Bedrock Knowledge Base + default S3 data source in Terraform.
# Leave false to use existing IDs above.
create_bedrock_kb_resources = false

# Optional: when create_bedrock_kb_resources=true, you can either provide existing
# role/collection ARNs OR let Terraform create them with the flags below.
create_managed_bedrock_kb_role = false
managed_bedrock_kb_role_arn    = ""
managed_bedrock_kb_role_name   = "bedrock-kb-service-role"

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
confluence_sync_cql                             = "type=page order by lastmodified desc"
confluence_sync_limit                           = 25
kb_sync_schedule_expression                     = "rate(6 hours)"

# Optional: create Bedrock Guardrails in Terraform.
# Leave false to use existing IDs (bedrock_guardrail_id / chatbot_guardrail_id).
create_bedrock_guardrail_resources = false
create_chatbot_guardrail_resources = false

github_kb_sync_enabled             = false
github_kb_data_source_id           = ""
github_kb_repos                    = []
github_kb_sync_schedule_expression = "rate(6 hours)"

release_notes_enabled  = false
sprint_report_enabled  = false
test_gen_enabled       = false
pr_description_enabled = false

# -------------------------------
# Suggested rollout
# -------------------------------
# 1) Keep dry_run=true for first apply + smoke tests
# 2) Validate chatbot and webapp path
# 3) Set dry_run=false

# Private VPC Webapp Deployment Runbook (Copy/Paste)

Use this runbook when your requirement is strict: **no public IPs, no public EIPs, no internet-facing webapp endpoint**.

Need the shortest version? Use `docs/private_vpc_operator_quick_card.md`.

## What this runbook deploys

- EC2-hosted chatbot web UI in a **private subnet**
- Optional **internal NLB + TLS** (ACM cert) for stable private endpoint inside VPC
- No public IP allocation for instance
- No public EIP allocation for instance or load balancer

## Prerequisites

- Terraform already initialized in `infra/terraform`
- Private subnet IDs available in your VPC
- (TLS option) ACM certificate issued in `us-gov-west-1`
- Access path from your users/network into the VPC (VPN, Direct Connect, Transit Gateway, etc.)

## 1) Copy this exact tfvars block (private-only, internal TLS)

Paste into `infra/terraform/terraform.tfvars` and replace placeholder values:

```hcl
# --- Private-only webapp hosting ---
webapp_hosting_enabled = true
webapp_hosting_mode    = "ec2_eip"
webapp_private_only    = true

# --- Existing Secrets Manager ARNs only (no Terraform secret creation) ---
create_secrets_manager_secrets         = false
existing_github_webhook_secret_arn         = "<GITHUB_WEBHOOK_SECRET_ARN>"
existing_github_app_private_key_secret_arn = "<GITHUB_APP_PRIVATE_KEY_SECRET_ARN>"
existing_github_app_ids_secret_arn         = "<GITHUB_APP_IDS_SECRET_ARN>"
existing_atlassian_credentials_secret_arn  = "<ATLASSIAN_CREDENTIALS_SECRET_ARN>"

# If chatbot_auth_mode="token", set existing token secret ARN and keep web UI auth mode as token.
# If chatbot_auth_mode="jwt" or "github_oauth", web UI auth mode should be bearer.
chatbot_auth_mode                    = "github_oauth"
existing_chatbot_api_token_secret_arn = ""
webapp_default_auth_mode             = "bearer"

# Webapp EC2 instance in private subnet
webapp_ec2_subnet_id     = "subnet-PRIVATE-WEBAPP"
webapp_ec2_instance_type = "t3.micro"
webapp_ec2_ami_id        = "" # optional override
webapp_ec2_key_name      = "" # optional, can remain empty

# Optional SG restriction for app port 80 inside private network
# (use your internal CIDRs only)
webapp_ec2_allowed_cidrs = [
  "10.0.0.0/8",
  "172.16.0.0/12",
  "192.168.0.0/16"
]

# Internal TLS front door (recommended)
webapp_tls_enabled             = true
webapp_tls_acm_certificate_arn = "arn:aws-us-gov:acm:us-gov-west-1:123456789012:certificate/REPLACE_ME"
webapp_tls_subnet_ids          = [
  "subnet-PRIVATE-NLB-A",
  "subnet-PRIVATE-NLB-B"
]
```

## 2) Deploy

From repository root, run:

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply
```

## 3) Expected outputs in private-only mode

After apply:

- `webapp_url` → private endpoint (instance private IP based)
- `webapp_https_url` → internal NLB DNS (if TLS enabled)
- `webapp_static_ip` → empty
- `webapp_tls_static_ips` → empty

These empty values for static public IP outputs are expected in private-only mode.

## 4) Internal DNS recommendation

For usability, create a private Route 53 record in your private hosted zone:

- Record name: `chatbot-ui.internal.example.com`
- Record target: `webapp_https_url` NLB DNS name (alias/CNAME per your DNS policy)

## 5) Validation checklist

- Webapp EC2 instance is in private subnet
- EC2 has no public IPv4 address
- No EIP resources created for webapp instance
- NLB (if enabled) is `internal`
- Webapp reachable only from approved private network paths
- If TLS enabled: clients reach **443** on internal NLB; NLB forwards to EC2 backend on port `80`

## 6) Troubleshooting

### Cannot reach `webapp_https_url` from workstation

- Confirm workstation path to VPC (VPN/DX/TGW)
- Confirm NLB subnets are routable from your source network
- Confirm security groups/NACLs allow required ports

### TLS listener fails to come up

- Confirm ACM certificate ARN is in `us-gov-west-1`
- Confirm certificate is valid and not expired

### App responds on HTTP but not HTTPS

- Verify `webapp_tls_enabled = true`
- Verify `webapp_tls_subnet_ids` are set and private-routable
- Verify internal DNS is pointing to NLB DNS name

### Chatbot returns 401/403

- `chatbot_auth_mode="token"` requires `X-Api-Token` header and `existing_chatbot_api_token_secret_arn`.
- `chatbot_auth_mode="jwt"`/`"github_oauth"` should use bearer auth in the UI.

### Chatbot returns 503

- Verify private network path from Lambda to required AWS APIs (Secrets Manager, DynamoDB, Bedrock).
- Verify `existing_atlassian_credentials_secret_arn` points to a valid secret with Jira + Confluence URLs and token.

## 7) Minimal non-TLS private mode (optional)

If you need private HTTP only (no internal NLB/TLS), use:

```hcl
webapp_hosting_enabled = true
webapp_hosting_mode    = "ec2_eip"
webapp_private_only    = true
webapp_ec2_subnet_id   = "subnet-PRIVATE-WEBAPP"
webapp_tls_enabled     = false
```

In this variant, use `webapp_url` (private IP) directly from inside the private network.

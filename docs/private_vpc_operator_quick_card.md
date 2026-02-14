# Private VPC Operator Quick Card (Copy/Paste)

Use this when you need the **fastest path** to deploy the chatbot web UI privately inside your VPC.

## 1) Paste into `infra/terraform/terraform.tfvars`

```hcl
# PRIVATE-ONLY WEBAPP
webapp_hosting_enabled = true
webapp_hosting_mode    = "ec2_eip"
webapp_private_only    = true

# REQUIRED: private subnet for EC2 webapp host
webapp_ec2_subnet_id = "subnet-REPLACE"

# Optional sizing/tuning
webapp_ec2_instance_type = "t3.micro"
webapp_ec2_ami_id        = ""
webapp_ec2_key_name      = ""

# Restrict ingress to internal ranges only
webapp_ec2_allowed_cidrs = [
  "10.0.0.0/8",
  "172.16.0.0/12",
  "192.168.0.0/16"
]

# If using EXISTING enterprise internal LB: keep false
webapp_tls_enabled = false

# If using MODULE-MANAGED internal TLS NLB instead, use:
# webapp_tls_enabled             = true
# webapp_tls_acm_certificate_arn = "arn:aws-us-gov:acm:us-gov-west-1:123456789012:certificate/REPLACE"
# webapp_tls_subnet_ids          = ["subnet-PRIVATE-A", "subnet-PRIVATE-B"]
```

## 2) Deploy

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply
```

## 3) Capture outputs for operations/LB team

```bash
cd infra/terraform
terraform output -raw webapp_instance_id
terraform output -raw webapp_private_ip
terraform output -raw webapp_url
terraform output -raw webapp_https_url
```

## 4) Expected private-only results

- EC2 has **no public IP**
- `webapp_static_ip` is empty
- `webapp_tls_static_ips` is empty
- `webapp_url` is private
- `webapp_https_url` is set only when `webapp_tls_enabled=true`

## 5) Which runbook to follow next

- Existing internal enterprise LB path: `docs/private_vpc_existing_lb_runbook.md`
- Module-managed internal NLB/TLS path: `docs/private_vpc_webapp_runbook.md`
- CloudFormation path (existing VPC only): `docs/cloudformation_private_vpc_quickstart.md`
- CloudFormation path (existing VPC + internal NLB TLS): `docs/cloudformation_private_vpc_internal_nlb_tls_quickstart.md`

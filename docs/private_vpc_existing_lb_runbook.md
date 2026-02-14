# Private VPC Webapp Behind Existing Internal Load Balancer (Copy/Paste)

Use this when your organization already has a standardized **internal** ALB/NLB and you must plug the chatbot UI into that existing LB path.

Need the shortest version? Use `docs/private_vpc_operator_quick_card.md`.

This runbook keeps everything private:

- No public IP on webapp EC2
- No new public EIPs
- No internet-facing endpoint

## What Terraform should manage in this pattern

Terraform manages the private webapp EC2 host only. Your platform/network team manages the existing internal LB and target group policy.

## 1) Copy this exact tfvars block

Paste into `infra/terraform/terraform.tfvars` and replace placeholders:

```hcl
# Private-only EC2-hosted webapp
webapp_hosting_enabled = true
webapp_hosting_mode    = "ec2_eip"
webapp_private_only    = true

# Private subnet for webapp host
webapp_ec2_subnet_id     = "subnet-PRIVATE-WEBAPP"
webapp_ec2_instance_type = "t3.micro"
webapp_ec2_ami_id        = "" # optional override
webapp_ec2_key_name      = "" # optional

# Restrict inbound to enterprise private CIDRs only
webapp_ec2_allowed_cidrs = [
  "10.0.0.0/8",
  "172.16.0.0/12",
  "192.168.0.0/16"
]

# IMPORTANT:
# Disable module-created NLB/TLS in this pattern.
# Your existing internal enterprise LB terminates/forwards traffic.
webapp_tls_enabled = false
```

## 2) Deploy Terraform

From repository root:

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply
```

## 3) Capture values for LB team (copy/paste)

After apply, run:

```bash
cd infra/terraform
terraform output -raw webapp_instance_id
terraform output -raw webapp_private_ip
terraform output -raw webapp_url
```

Expected behavior:

- `webapp_instance_id` has value
- `webapp_private_ip` has value
- `webapp_url` is private (HTTP)
- `webapp_static_ip` is empty
- `webapp_tls_static_ips` is empty

## 4) Existing internal LB integration

Give these values to your LB/platform team:

- Target type recommendation: `instance` (use `webapp_instance_id`) or `ip` (use `webapp_private_ip`)
- Backend port: `80`
- Health check path: `/`

If they use target-type `instance`, provide:

- `webapp_instance_id`

If they use target-type `ip`, provide:

- `webapp_private_ip`

## 5) Internal DNS mapping

Create/update private DNS to point to your existing internal LB hostname, for example:

- `chatbot-ui.internal.example.com` -> `internal-enterprise-alb-123.us-gov-west-1.elb.amazonaws.com`

## 6) Validation checklist

- Webapp instance in private subnet
- Webapp instance has no public IPv4
- Existing enterprise LB reaches backend target on port 80
- Health checks return healthy
- UI reachable only from approved private network path

## 7) Troubleshooting

### LB target unhealthy

- Confirm SG/NACL allows LB-to-instance traffic on `80`
- Confirm app responds at `/`
- Confirm target type (`instance` vs `ip`) matches what was registered

### Users cannot reach UI

- Confirm private DNS record exists and resolves internally
- Confirm user network has path to internal LB (VPN/DX/TGW)
- Confirm enterprise LB listener/routing policy includes webapp rule

### Need module-managed internal TLS instead of existing LB

If you want Terraform to create an internal NLB+TLS instead, use:

- `docs/private_vpc_webapp_runbook.md`

and set `webapp_tls_enabled = true` with private NLB subnets and ACM cert.

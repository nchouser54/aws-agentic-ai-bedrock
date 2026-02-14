# Day-1 Deployment Checklist (Private VPC, Existing Network)

Use this checklist for initial production/nonprod rollout with strict private-network constraints.

> Scope: full backend platform + private web UI access path.

## Change control metadata

- [ ] Change ticket ID: `________________`
- [ ] Environment: `dev / nonprod / prod`
- [ ] Planned window: `________________`
- [ ] On-call approver: `________________`
- [ ] Rollback owner: `________________`

## 0) Pre-flight access and tooling

- [ ] AWS account access verified in `us-gov-west-1`
- [ ] Terraform CLI available and authenticated
- [ ] Python venv available for repo checks
- [ ] Repo cloned and branch confirmed
- [ ] `make check` run successfully before deployment

Evidence:

- [ ] Attach terminal output or CI link

## 1) Network prerequisites (existing VPC only)

- [ ] Existing `VpcId` identified
- [ ] Private subnet(s) identified for app and/or internal NLB
- [ ] Private DNS strategy confirmed (Route 53 private hosted zone or enterprise DNS)
- [ ] Connectivity path verified from user network (VPN / DX / TGW)
- [ ] Security policy approved for allowed CIDRs

Evidence:

- [ ] VPC/Subnet IDs documented in change record

## 2) External integrations prerequisites

### GitHub App

- [ ] GitHub App created and installed on target repos
- [ ] Webhook secret generated
- [ ] App private key PEM available
- [ ] App ID + Installation ID recorded
- [ ] Required permissions confirmed (`PR write`, `Contents write`, `Metadata read`)

### Atlassian (if enabled)

- [ ] Jira/Confluence service account credentials validated
- [ ] Base URLs verified reachable from runtime environment

### Bedrock (if enabled)

- [ ] Target model(s) enabled in account/region
- [ ] KB ID/data source IDs ready (if using kb/hybrid modes)

## 3) Deploy backend platform (Terraform)

- [ ] `infra/terraform/terraform.tfvars` prepared
- [ ] `terraform init` complete
- [ ] `terraform plan` reviewed and approved
- [ ] `terraform apply` complete without errors

Post-apply outputs captured:

- [ ] `webhook_url`
- [ ] `chatbot_url` (if chatbot enabled)
- [ ] `chatbot_websocket_url` (if websocket enabled)

## 4) Populate AWS Secrets Manager values

- [ ] `github_webhook_secret` updated
- [ ] `github_app_private_key_pem` updated
- [ ] `github_app_ids` updated
- [ ] `atlassian_credentials` updated (if used)
- [ ] Optional auth/provider secrets updated as needed

## 5) Configure GitHub webhook

- [ ] GitHub App webhook URL set to Terraform `webhook_url`
- [ ] GitHub App webhook secret matches AWS secret value
- [ ] Event subscription includes `pull_request`
- [ ] Test delivery returns successful status

Evidence:

- [ ] Screenshot or delivery log ID attached

## 6) Deploy private web UI path (choose one)

### A) Existing enterprise internal LB

- [ ] Follow `docs/private_vpc_existing_lb_runbook.md`
- [ ] LB team received `webapp_instance_id` / `webapp_private_ip`
- [ ] Target health is healthy

### B) CloudFormation private EC2 (existing VPC)

- [ ] Follow `docs/cloudformation_private_vpc_quickstart.md`

### C) CloudFormation private EC2 + internal NLB TLS

- [ ] Follow `docs/cloudformation_private_vpc_internal_nlb_tls_quickstart.md`
- [ ] ACM certificate ARN validated in region

## 7) Private DNS and access validation

- [ ] Internal DNS record created/updated
- [ ] Endpoint resolves only in private network context
- [ ] Web UI loads from private path
- [ ] Chatbot API requests succeed from UI
- [ ] No public endpoint exposure detected

Validation commands/evidence:

- [ ] DNS resolution screenshot/log
- [ ] HTTP 200 health check evidence
- [ ] Functional query response evidence

## 8) Security validation

- [ ] EC2 has no public IP
- [ ] No public EIP allocated for private-only path
- [ ] Internal NLB only (if used)
- [ ] SG/NACL ingress limited to approved CIDRs
- [ ] Secrets are not placeholder values

## 9) Observability and alarms

- [ ] CloudWatch logs visible for webhook/worker/chatbot
- [ ] Custom chatbot metrics visible (if enabled)
- [ ] Alarm target SNS configured and tested (if enabled)
- [ ] Dashboard reachable (if enabled)

## 10) Functional smoke tests

- [ ] PR webhook ingestion works end-to-end
- [ ] Worker posts review (or dry-run logs expected behavior)
- [ ] Chatbot query endpoint returns valid response
- [ ] Optional features validated if enabled (release notes / sprint report / test gen / PR description / KB sync)

## 11) Rollback readiness

- [ ] Rollback command set prepared (`terraform apply` previous config / `cloudformation delete-stack` as applicable)
- [ ] Last known-good config reference recorded
- [ ] Owner and escalation path confirmed

## 12) Go-live signoff

- [ ] Platform owner signoff
- [ ] Security signoff
- [ ] Networking signoff
- [ ] Application owner signoff

Final notes:

- [ ] `____________________________________________________________`
- [ ] `____________________________________________________________`

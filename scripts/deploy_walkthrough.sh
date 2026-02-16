#!/usr/bin/env bash
# ===========================================================================
# AI PR Reviewer — Full Deployment Walkthrough
# ===========================================================================
# This script walks you through every step needed to deploy the platform.
# It checks prerequisites, validates config, deploys infra, and verifies.
#
# Usage:
#   chmod +x scripts/deploy_walkthrough.sh
#   ./scripts/deploy_walkthrough.sh
#
# The script will PAUSE at every step and tell you what to do.
# Nothing destructive runs without your explicit confirmation.
# ===========================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors and helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

step_num=0

step() {
  step_num=$((step_num + 1))
  echo ""
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BOLD}  STEP ${step_num}: $1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

info() {
  echo -e "${CYAN}  ℹ  $1${NC}"
}

warn() {
  echo -e "${YELLOW}  ⚠  $1${NC}"
}

ok() {
  echo -e "${GREEN}  ✓  $1${NC}"
}

fail() {
  echo -e "${RED}  ✗  $1${NC}"
}

pause() {
  echo ""
  echo -e "${YELLOW}  Press ENTER when ready to continue (Ctrl+C to abort)...${NC}"
  read -r
}

ask_yes_no() {
  while true; do
    echo -e "${YELLOW}  $1 [y/n]: ${NC}"
    read -r answer
    case "$answer" in
      [Yy]*) return 0;;
      [Nn]*) return 1;;
      *) echo "  Please answer y or n.";;
    esac
  done
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/infra/terraform"

INFRA_CLI=""
if command -v tofu &>/dev/null; then
  INFRA_CLI="tofu"
elif command -v terraform &>/dev/null; then
  INFRA_CLI="terraform"
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     AI PR Reviewer — Deployment Walkthrough                 ║${NC}"
echo -e "${BOLD}║     Private VPC · AWS GovCloud · No Public IPs              ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  This script walks you through every step of a full deployment."
echo "  It checks prerequisites, validates config, deploys, and verifies."
echo "  Time estimate: 30–60 minutes for first deployment."
echo ""
echo -e "  Repo root: ${CYAN}${REPO_ROOT}${NC}"

pause

# ===========================================================================
# PHASE 1: Prerequisites
# ===========================================================================

step "Check required tools"

errors=0

if [ -n "$INFRA_CLI" ]; then
  tf_version=$($INFRA_CLI version -json 2>/dev/null | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('terraform_version') or data.get('tofu_version') or 'unknown')" 2>/dev/null || $INFRA_CLI version | head -1)
  ok "IaC CLI installed (${INFRA_CLI}): ${tf_version}"
else
  fail "Neither OpenTofu ('tofu') nor Terraform is installed. Install one and re-run."
  errors=$((errors + 1))
fi

if command -v python3 &>/dev/null; then
  py_version=$(python3 --version 2>&1)
  ok "Python3 installed: ${py_version}"
else
  fail "Python3 not found."
  errors=$((errors + 1))
fi

if command -v aws &>/dev/null; then
  ok "AWS CLI installed"
else
  fail "AWS CLI not found. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
  errors=$((errors + 1))
fi

if command -v git &>/dev/null; then
  ok "Git installed"
else
  fail "Git not found."
  errors=$((errors + 1))
fi

if [ $errors -gt 0 ]; then
  fail "Missing $errors required tool(s). Install them and re-run."
  exit 1
fi

# ---------------------------------------------------------------------------
step "Verify AWS credentials and region"

info "Checking AWS identity..."
if aws sts get-caller-identity &>/dev/null; then
  ACCT=$(aws sts get-caller-identity --query Account --output text)
  REGION=$(aws configure get region 2>/dev/null || echo "not set")
  ok "AWS Account: ${ACCT}"
  ok "Configured region: ${REGION}"
  if [[ "$REGION" != *"gov"* ]]; then
    warn "Region '${REGION}' doesn't look like GovCloud. Expected us-gov-west-1."
    warn "If deploying to GovCloud, run: export AWS_DEFAULT_REGION=us-gov-west-1"
  fi
else
  fail "AWS credentials not configured or expired."
  echo "  Run: aws configure    or    export AWS_ACCESS_KEY_ID=... / AWS_SECRET_ACCESS_KEY=..."
  exit 1
fi

pause

# ---------------------------------------------------------------------------
step "Run code checks (lint + tests)"

info "Running: make check"
cd "$REPO_ROOT"

if [ -d ".venv" ]; then
  source .venv/bin/activate 2>/dev/null || true
fi

if make check; then
  ok "All lint and test checks passed."
else
  fail "make check failed. Fix errors above before deploying."
  exit 1
fi

pause

# ===========================================================================
# PHASE 2: Collect configuration values
# ===========================================================================

step "Gather deployment values"

echo ""
echo "  You need the following values. Write them down or have them ready:"
echo ""
echo -e "  ${BOLD}REQUIRED — Backend (IaC):${NC}"
echo "  ┌──────────────────────────────────────────────────────────────────┐"
echo "  │  1. GitHub API base URL                                         │"
echo "  │     github.com → https://api.github.com                         │"
echo "  │     GHE Server → https://<hostname>/api/v3                      │"
echo "  │                                                                  │"
echo "  │  2. GitHub App ID                                                │"
echo "  │  3. GitHub App Installation ID                                   │"
echo "  │  4. GitHub App private key PEM (file path)                       │"
echo "  │  5. GitHub webhook secret (random string you generate)           │"
echo "  │                                                                  │"
echo "  │  6. Bedrock model ID                                             │"
echo "  │     e.g. anthropic.claude-3-sonnet-20240229-v1:0                 │"
echo "  │                                                                  │"
echo "  │  7. Atlassian base URL + email + API token (if chatbot enabled)  │"
echo "  └──────────────────────────────────────────────────────────────────┘"
echo ""
echo -e "  ${BOLD}REQUIRED — Private Webapp (if deploying the web UI):${NC}"
echo "  ┌──────────────────────────────────────────────────────────────────┐"
echo "  │  8.  Existing VPC ID                                             │"
echo "  │  9.  Private subnet ID(s)                                        │"
echo "  │  10. EC2 key pair name (for SSH if needed)                       │"
echo "  │  11. ACM certificate ARN (if TLS enabled)                        │"
echo "  │  12. Allowed CIDRs (your internal network ranges)                │"
echo "  └──────────────────────────────────────────────────────────────────┘"
echo ""
info "Don't have all values yet? That's OK — your IaC CLI will prompt for required ones."

pause

# ===========================================================================
# PHASE 3: Prepare tfvars
# ===========================================================================

step "Prepare IaC variables file"

TFVARS="${TF_DIR}/terraform.tfvars"

if [ -f "$TFVARS" ]; then
  ok "terraform.tfvars already exists at: ${TFVARS}"
  info "Review it and update if needed."
else
  warn "No terraform.tfvars found."
  echo ""
  echo "  You have two options:"
  echo "    A) Copy the example and edit:  cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars"
  echo "    B) Create from scratch"
  echo ""
  if ask_yes_no "Copy the example file now?"; then
    cp "${TF_DIR}/terraform.tfvars.example" "$TFVARS"
    ok "Copied terraform.tfvars.example → terraform.tfvars"
    echo ""
    echo -e "  ${BOLD}EDIT THIS FILE NOW:${NC}  ${CYAN}${TFVARS}${NC}"
    echo ""
    echo "  Key fields to fill in:"
    echo "    • github_api_base"
    echo "    • bedrock_model_id"
    echo "    • dry_run = true          (keep true for first deploy)"
    echo "    • webapp_hosting_enabled  (true if you want the web UI)"
    echo "    • webapp_private_only = true"
    echo "    • webapp_ec2_subnet_id"
  else
    info "Create infra/terraform/terraform.tfvars manually before continuing."
  fi
fi

echo ""
info "Open and edit: ${TFVARS}"
info "Reference: infra/terraform/terraform.tfvars.example"
info "All variables documented in: infra/terraform/variables.tf"

pause

# ===========================================================================
# PHASE 4: IaC deploy
# ===========================================================================

step "Initialize IaC"

info "Running: ${INFRA_CLI} init"
cd "$TF_DIR"

if $INFRA_CLI init -input=false; then
  ok "Initialization completed successfully."
else
  fail "Initialization failed. Check backend configuration and provider credentials."
  exit 1
fi

pause

# ---------------------------------------------------------------------------
step "Plan infrastructure changes"

info "Running: ${INFRA_CLI} plan -out=tfplan"

if $INFRA_CLI plan -out=tfplan; then
  ok "Plan complete. Review the changes above carefully."
  echo ""
  echo -e "  ${BOLD}REVIEW CHECKLIST:${NC}"
  echo "  • Number of resources to add/change/destroy looks reasonable"
  echo "  • No unexpected destroys"
  echo "  • Lambda functions use the correct model IDs"
  echo "  • Existing secret ARNs in tfvars point to real values"
  echo "  • SQS queues and DynamoDB tables will be created"
else
  fail "Plan failed. Fix the errors above."
  exit 1
fi

echo ""
if ! ask_yes_no "Does the plan look correct? Ready to apply?"; then
  info "Aborting. Fix your tfvars and re-run."
  exit 0
fi

# ---------------------------------------------------------------------------
step "Apply infrastructure changes"

info "Running: ${INFRA_CLI} apply tfplan"

if $INFRA_CLI apply tfplan; then
  ok "Apply completed successfully!"
else
  fail "Apply failed. Check errors above."
  fail "Resources may be partially created. Run '${INFRA_CLI} plan' to see current state."
  exit 1
fi

echo ""
echo -e "  ${BOLD}CAPTURE THESE OUTPUTS:${NC}"
echo ""
$INFRA_CLI output -json | python3 -c "
import json, sys
outputs = json.load(sys.stdin)
for k, v in sorted(outputs.items()):
    val = v.get('value', '')
    if val:
        print(f'    {k} = {val}')
" 2>/dev/null || $INFRA_CLI output

pause

# ===========================================================================
# PHASE 5: Verify secrets
# ===========================================================================

step "Verify AWS Secrets Manager values"

echo ""
echo -e "  ${BOLD}Confirm the existing Secrets Manager values are populated.${NC}"
echo "  Default deployment mode uses existing secret ARNs from terraform.tfvars."
echo ""
echo "  Inspect effective secret ARNs from IaC outputs:"
echo ""
echo -e "  ${CYAN}${INFRA_CLI} output -json | python3 -c 'import json,sys; print(json.load(sys.stdin)["secret_arns"]["value"])'${NC}"
echo ""
echo "  If any payload is missing, update that secret ARN directly in Secrets Manager."
echo ""

info "After confirming secret payloads, continue."

pause

# ===========================================================================
# PHASE 6: Configure GitHub webhook
# ===========================================================================

step "Configure GitHub App webhook"

WEBHOOK_URL=$(cd "$TF_DIR" && $INFRA_CLI output -raw webhook_url 2>/dev/null || echo "<run ${INFRA_CLI} output -raw webhook_url>")

echo ""
echo "  Go to your GitHub App settings → Webhooks and set:"
echo ""
echo -e "  ${BOLD}Webhook URL:${NC}    ${CYAN}${WEBHOOK_URL}${NC}"
echo -e "  ${BOLD}Content type:${NC}   application/json"
echo -e "  ${BOLD}Secret:${NC}         (the same value you put in Secrets Manager)"
echo -e "  ${BOLD}Events:${NC}         Pull requests (at minimum)"
echo ""
echo "  After saving, click 'Redeliver' on a recent delivery to test."

pause

# ===========================================================================
# PHASE 7: Smoke test
# ===========================================================================

step "Smoke test the deployment"

echo ""
echo -e "  ${BOLD}Test 1: Webhook receiver${NC}"
echo "  Create or update a PR in a repo with the GitHub App installed."
echo "  Then check CloudWatch Logs:"
echo ""
echo -e "  ${CYAN}aws logs describe-log-groups --log-group-name-prefix '/aws/lambda/ai-pr-reviewer' --query 'logGroups[].logGroupName' --output table${NC}"
echo ""
echo -e "  ${BOLD}Test 2: Worker processing${NC}"
echo "  After the webhook fires, the worker should pick up the SQS message:"
echo ""
echo -e "  ${CYAN}aws logs tail /aws/lambda/ai-pr-reviewer-worker --since 5m${NC}"
echo ""

if ask_yes_no "Is dry_run=true? (Expected for first deployment)"; then
  info "With dry_run=true, the worker will log what it WOULD have posted but won't comment on the PR."
  info "Check worker logs for 'dry_run' entries to confirm it processed correctly."
else
  info "Live mode: the worker will post review comments on the PR."
  info "Watch the PR for AI review comments."
fi

pause

# ===========================================================================
# PHASE 8: Private webapp (optional)
# ===========================================================================

step "Deploy private web UI (optional)"

if ask_yes_no "Do you want to deploy the private web UI?"; then
  echo ""
  echo "  Choose your deployment path:"
  echo ""
  echo "    A) Terraform EC2 with internal NLB + TLS (already in your tfvars)"
  echo "       → Set webapp_hosting_enabled=true, webapp_private_only=true"
  echo "       → Re-run ${INFRA_CLI} plan/apply"
  echo ""
  echo "    B) CloudFormation — EC2 only (existing VPC)"
  echo "       → Follow: docs/cloudformation_private_vpc_quickstart.md"
  echo ""
  echo "    C) CloudFormation — EC2 + internal NLB + TLS (existing VPC)"
  echo "       → Follow: docs/cloudformation_private_vpc_internal_nlb_tls_quickstart.md"
  echo ""
  echo "    D) Existing enterprise internal LB"
  echo "       → Follow: docs/private_vpc_existing_lb_runbook.md"
  echo ""
  info "After deploying, verify the webapp loads over your private network."
else
  info "Skipping web UI deployment. You can add it later."
fi

pause

# ===========================================================================
# PHASE 9: Security validation
# ===========================================================================

step "Security validation"

echo ""
echo "  Verify these security controls:"
echo ""
echo "  [ ] No EC2 instances have public IPs:"
echo -e "      ${CYAN}aws ec2 describe-instances --filters 'Name=tag:Project,Values=ai-pr-reviewer' --query 'Reservations[].Instances[].[InstanceId,PublicIpAddress]' --output table${NC}"
echo ""
echo "  [ ] No Elastic IPs allocated (for private-only mode):"
echo -e "      ${CYAN}aws ec2 describe-addresses --filters 'Name=tag:Project,Values=ai-pr-reviewer' --output table${NC}"
echo ""
echo "  [ ] NLBs are internal only (if used):"
echo -e "      ${CYAN}aws elbv2 describe-load-balancers --query 'LoadBalancers[?Scheme==\`internal\`].[LoadBalancerName,DNSName]' --output table${NC}"
echo ""
echo "  [ ] Secrets are not placeholder values:"
echo -e "      ${CYAN}aws secretsmanager list-secrets --filters Key=tag-key,Values=Project Key=tag-value,Values=ai-pr-reviewer --query 'SecretList[].[Name]' --output table${NC}"
echo ""

pause

# ===========================================================================
# PHASE 10: Observability
# ===========================================================================

step "Verify observability"

echo ""
echo "  Check that logs are flowing:"
echo ""
echo -e "  ${CYAN}# List all log groups for this project${NC}"
echo -e "  ${CYAN}aws logs describe-log-groups --log-group-name-prefix '/aws/lambda/ai-pr-reviewer' --query 'logGroups[].logGroupName' --output table${NC}"
echo ""
echo "  Check X-Ray tracing (if enabled):"
echo -e "  ${CYAN}aws xray get-service-graph --start-time \$(date -u -v-1H +%s 2>/dev/null || date -u -d '1 hour ago' +%s) --end-time \$(date -u +%s) --query 'Services[].Name' --output table${NC}"
echo ""

pause

# ===========================================================================
# Done
# ===========================================================================

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  DEPLOYMENT WALKTHROUGH COMPLETE${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Summary of what was deployed:"
echo "    • Backend: Lambda functions, API Gateway, SQS, DynamoDB, Secrets"
echo "    • Observability: CloudWatch Logs, X-Ray tracing, custom metrics"
echo "    • Security: KMS encryption, IAM least-privilege, concurrency limits"
echo ""
echo "  Next steps:"
echo "    1. Monitor CloudWatch Logs for the first few PR reviews"
echo "    2. When confident, set dry_run = false in terraform.tfvars"
echo "    3. Re-run: ${INFRA_CLI} plan && ${INFRA_CLI} apply"
echo ""
echo "  Key docs:"
echo "    • Full Day-1 checklist:        docs/day1_deployment_checklist.md"
echo "    • Private VPC webapp runbook:   docs/private_vpc_webapp_runbook.md"
echo "    • Operator quick card:          docs/private_vpc_operator_quick_card.md"
echo ""
echo -e "  ${BOLD}Rollback:${NC} ${INFRA_CLI} destroy -auto-approve  (or targeted: ${INFRA_CLI} apply with previous tfvars)"
echo ""

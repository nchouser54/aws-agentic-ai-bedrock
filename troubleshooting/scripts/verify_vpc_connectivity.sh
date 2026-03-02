#!/usr/bin/env bash
# Same-Subnet VPC Connectivity Verification
# Run on your local machine with AWS CLI configured
# Usage: ./verify_vpc_connectivity.sh <RHEL8_INSTANCE_ID> <RHEL9_INSTANCE_ID> [--region us-gov-west-1]

set -euo pipefail

RHEL8_ID="${1:?Usage: $0 <RHEL8_INSTANCE_ID> <RHEL9_INSTANCE_ID> [--region us-gov-west-1]}"
RHEL9_ID="${2:?Usage: $0 <RHEL8_INSTANCE_ID> <RHEL9_INSTANCE_ID> [--region us-gov-west-1]}"
AWS_REGION="${3:---region}"
REGION_VAL="${4:-us-gov-west-1}"

if [ "$AWS_REGION" == "--region" ]; then
  AWS_REGION="$REGION_VAL"
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_step() { echo -e "${YELLOW}[*]${NC} $1"; }
log_pass() { echo -e "${GREEN}[✓]${NC} $1"; }
log_fail() { echo -e "${RED}[✗]${NC} $1"; }
log_info() { echo -e "${BLUE}[i]${NC} $1"; }

echo "========================================="
echo "VPC Same-Subnet Connectivity Verification"
echo "========================================="
echo "RHEL8 Instance: ${RHEL8_ID}"
echo "RHEL9 Instance: ${RHEL9_ID}"
echo "AWS Region: ${AWS_REGION}"
echo ""

# ============================================================
# 1. INSTANCE STATUS
# ============================================================

log_step "Checking instance status..."
echo ""

RHEL8_INFO=$(aws ec2 describe-instances \
  --instance-ids "$RHEL8_ID" \
  --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].[State.Name,InstanceType,VpcId,SubnetId,PrivateIpAddress,PrivateIpAddresses[0].NetworkInterfaceId,SecurityGroups[*].[GroupId,GroupName]]' \
  --output json)

RHEL9_INFO=$(aws ec2 describe-instances \
  --instance-ids "$RHEL9_ID" \
  --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].[State.Name,InstanceType,VpcId,SubnetId,PrivateIpAddress,PrivateIpAddresses[0].NetworkInterfaceId,SecurityGroups[*].[GroupId,GroupName]]' \
  --output json)

echo "RHEL8:"
echo "$RHEL8_INFO" | jq '.'
echo ""

echo "RHEL9:"
echo "$RHEL9_INFO" | jq '.'
echo ""

# Extract values
RHEL8_STATE=$(echo "$RHEL8_INFO" | jq -r '.[0]')
RHEL8_TYPE=$(echo "$RHEL8_INFO" | jq -r '.[1]')
RHEL8_VPC=$(echo "$RHEL8_INFO" | jq -r '.[2]')
RHEL8_SUBNET=$(echo "$RHEL8_INFO" | jq -r '.[3]')
RHEL8_IP=$(echo "$RHEL8_INFO" | jq -r '.[4]')
RHEL8_ENI=$(echo "$RHEL8_INFO" | jq -r '.[5]')

RHEL9_STATE=$(echo "$RHEL9_INFO" | jq -r '.[0]')
RHEL9_VPC=$(echo "$RHEL9_INFO" | jq -r '.[2]')
RHEL9_SUBNET=$(echo "$RHEL9_INFO" | jq -r '.[3]')
RHEL9_IP=$(echo "$RHEL9_INFO" | jq -r '.[4]')

# Check states
if [ "$RHEL8_STATE" == "running" ]; then
  log_pass "RHEL8 instance is running"
else
  log_fail "RHEL8 instance is ${RHEL8_STATE} (must be running)"
  exit 1
fi

if [ "$RHEL9_STATE" == "running" ]; then
  log_pass "RHEL9 instance is running"
else
  log_fail "RHEL9 instance is ${RHEL9_STATE} (must be running)"
  exit 1
fi
echo ""

# Check same VPC and subnet
if [ "$RHEL8_VPC" == "$RHEL9_VPC" ]; then
  log_pass "Both instances in same VPC: ${RHEL8_VPC}"
else
  log_fail "Instances in different VPCs! RHEL8: ${RHEL8_VPC}, RHEL9: ${RHEL9_VPC}"
  exit 1
fi

if [ "$RHEL8_SUBNET" == "$RHEL9_SUBNET" ]; then
  log_pass "Both instances in same subnet: ${RHEL8_SUBNET}"
else
  log_fail "Instances in different subnets! RHEL8: ${RHEL8_SUBNET}, RHEL9: ${RHEL9_SUBNET}"
  log_info "Note: Different subnets are OK if they're in same VPC, but requires route table entry"
fi
echo ""

# ============================================================
# 2. SECURITY GROUP VERIFICATION
# ============================================================

log_step "Checking security groups..."
echo ""

RHEL8_SGS=$(aws ec2 describe-instances \
  --instance-ids "$RHEL8_ID" \
  --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[*].GroupId' \
  --output text)

RHEL9_SGS=$(aws ec2 describe-instances \
  --instance-ids "$RHEL9_ID" \
  --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[*].GroupId' \
  --output text)

log_info "RHEL8 Security Groups: ${RHEL8_SGS}"
log_info "RHEL9 Security Groups: ${RHEL9_SGS}"
echo ""

# Check each RHEL8 SG for inbound rules allowing RHEL9 IP
log_info "Checking RHEL8 ingress rules (allowing RHEL9 ${RHEL9_IP})..."
for sg in ${RHEL8_SGS}; do
  RULES=$(aws ec2 describe-security-groups \
    --group-ids "$sg" \
    --region "$AWS_REGION" \
    --query 'SecurityGroups[0].IpPermissions[*].[IpProtocol,FromPort,ToPort,IpRanges[*].CidrIp,UserIdGroupPairs[*].GroupId]' \
    --output json)
  
  echo "  Security Group: $sg"
  echo "    Ingress Rules:"
  echo "$RULES" | jq '.' | sed 's/^/      /'
done
echo ""

# Check for all-traffic rule or RHEL9's SG ID
log_info "Checking if RHEL8 allows traffic from RHEL9..."
RHEL8_ALLOWS_RHEL9=false
for sg in ${RHEL8_SGS}; do
  # Check for 0.0.0.0/0 (all traffic)
  if aws ec2 describe-security-groups \
    --group-ids "$sg" \
    --region "$AWS_REGION" \
    --query 'SecurityGroups[0].IpPermissions[?IpProtocol==`-1`]' \
    --output text | grep -q "0.0.0.0/0"; then
    log_pass "RHEL8 SG $sg allows all inbound traffic (0.0.0.0/0)"
    RHEL8_ALLOWS_RHEL9=true
  fi
  
  # Check for RHEL9's SG ID
  for rhel9_sg in ${RHEL9_SGS}; do
    if aws ec2 describe-security-groups \
      --group-ids "$sg" \
      --region "$AWS_REGION" \
      --query "SecurityGroups[0].IpPermissions[?UserIdGroupPairs[?GroupId=='$rhel9_sg']]" \
      --output text 2>/dev/null | grep -q "$rhel9_sg"; then
      log_pass "RHEL8 SG $sg allows RHEL9 SG $rhel9_sg"
      RHEL8_ALLOWS_RHEL9=true
    fi
  done
  
  # Check for source IP CIDR
  if aws ec2 describe-security-groups \
    --group-ids "$sg" \
    --region "$AWS_REGION" \
    --query "SecurityGroups[0].IpPermissions[*].IpRanges[?CidrIp=='${RHEL9_IP}/32']" \
    --output text 2>/dev/null | grep -q "${RHEL9_IP}"; then
    log_pass "RHEL8 SG $sg allows ${RHEL9_IP}/32"
    RHEL8_ALLOWS_RHEL9=true
  fi
done

if [ "$RHEL8_ALLOWS_RHEL9" == false ]; then
  log_fail "RHEL8 security groups do NOT explicitly allow RHEL9 (${RHEL9_IP})"
  log_info "You need to add an ingress rule to RHEL8's SG:"
  log_info "  aws ec2 authorize-security-group-ingress --group-id <RHEL8_SG_ID> --protocol all --source-group <RHEL9_SG_ID>"
  log_info "  OR"
  log_info "  aws ec2 authorize-security-group-ingress --group-id <RHEL8_SG_ID> --cidr ${RHEL9_IP}/32 --protocol all"
fi
echo ""

# Check RHEL9 egress to RHEL8
log_info "Checking if RHEL9 allows egress to RHEL8..."
RHEL9_ALLOWS_EGRESS=false
for sg in ${RHEL9_SGS}; do
  # Check for 0.0.0.0/0 (all traffic)
  if aws ec2 describe-security-groups \
    --group-ids "$sg" \
    --region "$AWS_REGION" \
    --query 'SecurityGroups[0].IpPermissionsEgress[?IpProtocol==`-1`]' \
    --output text | grep -q "0.0.0.0/0"; then
    log_pass "RHEL9 SG $sg allows all outbound traffic (0.0.0.0/0)"
    RHEL9_ALLOWS_EGRESS=true
  fi
done

if [ "$RHEL9_ALLOWS_EGRESS" == false ]; then
  log_fail "RHEL9 may not allow egress to RHEL8 (check egress rules)"
fi
echo ""

# ============================================================
# 3. NETWORK ACL (NACL) VERIFICATION
# ============================================================

log_step "Checking Network ACLs..."
echo ""

RHEL8_NACL_ID=$(aws ec2 describe-network-acls \
  --region "$AWS_REGION" \
  --filters "Name=association.subnet-id,Values=${RHEL8_SUBNET}" \
  --query 'NetworkAcls[0].NetworkAclId' \
  --output text)

RHEL9_NACL_ID=$(aws ec2 describe-network-acls \
  --region "$AWS_REGION" \
  --filters "Name=association.subnet-id,Values=${RHEL9_SUBNET}" \
  --query 'NetworkAcls[0].NetworkAclId' \
  --output text)

log_pass "RHEL8 NACL: ${RHEL8_NACL_ID}"
log_pass "RHEL9 NACL: ${RHEL9_NACL_ID}"
echo ""

# Check for explicit DENY rules
log_info "Checking for DENY rules in RHEL8 NACL..."
DENIES=$(aws ec2 describe-network-acls \
  --network-acl-ids "$RHEL8_NACL_ID" \
  --region "$AWS_REGION" \
  --query 'NetworkAcls[0].Entries[?RuleAction==`deny`]' \
  --output json)

if echo "$DENIES" | jq -e 'length > 0' > /dev/null; then
  log_fail "Found DENY rules in RHEL8 NACL:"
  echo "$DENIES" | jq '.'
else
  log_pass "No DENY rules in RHEL8 NACL"
fi
echo ""

# ============================================================
# 4. ROUTING TABLE VERIFICATION
# ============================================================

log_step "Checking Route Tables..."
echo ""

RHEL8_RT=$(aws ec2 describe-route-tables \
  --region "$AWS_REGION" \
  --filters "Name=association.subnet-id,Values=${RHEL8_SUBNET}" \
  --query 'RouteTables[0]' \
  --output json)

RHEL9_RT=$(aws ec2 describe-route-tables \
  --region "$AWS_REGION" \
  --filters "Name=association.subnet-id,Values=${RHEL9_SUBNET}" \
  --query 'RouteTables[0]' \
  --output json)

log_info "RHEL8 Route Table:"
echo "$RHEL8_RT" | jq '.Routes[]' | sed 's/^/  /'
echo ""

log_info "RHEL9 Route Table:"
echo "$RHEL9_RT" | jq '.Routes[]' | sed 's/^/  /'
echo ""

# ============================================================
# 5. ENI (Network Interface) STATUS
# ============================================================

log_step "Checking ENI (Network Interface) Status..."
echo ""

RHEL8_ENI_STATUS=$(aws ec2 describe-network-interfaces \
  --network-interface-ids "$RHEL8_ENI" \
  --region "$AWS_REGION" \
  --query 'NetworkInterfaces[0].[Status,MacAddress,Groups[*].[GroupId,GroupName]]' \
  --output json)

log_info "RHEL8 ENI: ${RHEL8_ENI}"
echo "$RHEL8_ENI_STATUS" | jq '.'
echo ""

# ============================================================
# SUMMARY
# ============================================================

echo "========================================="
echo "AWS Infrastructure Summary"
echo "========================================="
echo ""
echo "✓ Both instances running"
echo "✓ Same VPC: ${RHEL8_VPC}"
echo ""
echo "RHEL8 IP: ${RHEL8_IP}"
echo "RHEL9 IP: ${RHEL9_IP}"
echo ""

if [ "$RHEL8_SUBNET" == "$RHEL9_SUBNET" ]; then
  echo "✓ Same Subnet: ${RHEL8_SUBNET}"
  echo ""
  echo "Next steps:"
  echo "  1. Verify security group allows RHEL8 ← RHEL9:"
  echo "     aws ec2 describe-security-groups --group-ids <RHEL8_SG_ID>"
  echo ""
  echo "  2. Test on RHEL8 instance:"
  echo "     ./verify_instance_networking.sh ${RHEL8_IP} ${RHEL9_IP} 8080"
  echo ""
  echo "  3. Test on RHEL9 instance:"
  echo "     ./verify_instance_networking.sh ${RHEL9_IP} ${RHEL8_IP} 8080"
else
  echo "⚠ Different Subnets: RHEL8=${RHEL8_SUBNET}, RHEL9=${RHEL9_SUBNET}"
  echo ""
  echo "Verify cross-subnet routing exists in route tables above"
fi
echo ""

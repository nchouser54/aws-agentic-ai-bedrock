#!/usr/bin/env bash
# Instance-level network verification
# Run ON RHEL8 or RHEL9 instance (via SSH)
# Usage: ./verify_instance_networking.sh <MY_IP> <TARGET_IP> [PORT]

set -euo pipefail

MY_IP="${1:?Usage: $0 <MY_IP> <TARGET_IP> [PORT]}"
TARGET_IP="${2:?Usage: $0 <MY_IP> <TARGET_IP> [PORT]}"
PORT="${3:-8080}"

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
echo "Instance-Level Network Verification"
echo "========================================="
echo "This instance IP: ${MY_IP}"
echo "Target instance IP: ${TARGET_IP}"
echo "Test port: ${PORT}"
echo ""

# ============================================================
# 1. LOCAL INTERFACE VERIFICATION
# ============================================================

log_step "Verifying local network configuration..."
echo ""

# Check if this IP is actually assigned to this instance
if ip addr show | grep -q "${MY_IP}"; then
  log_pass "IP ${MY_IP} is assigned to this instance"
else
  log_fail "IP ${MY_IP} is NOT assigned to this instance"
  log_info "Actual IPs on this instance:"
  ip addr show | grep "inet " | awk '{print $2}'
  exit 1
fi
echo ""

# Get interface info
IFACE=$(ip addr show | grep "${MY_IP}" | awk '{print $NF}')
log_info "Interface: ${IFACE}"

IFACE_INFO=$(ip addr show "$IFACE")
echo "$IFACE_INFO" | sed 's/^/  /'
echo ""

# Check interface is up
if ip link show "$IFACE" | grep -q "UP"; then
  log_pass "Interface ${IFACE} is UP"
else
  log_fail "Interface ${IFACE} is DOWN"
  exit 1
fi
echo ""

# ============================================================
# 2. ROUTING VERIFICATION
# ============================================================

log_step "Checking routing to target ${TARGET_IP}..."
echo ""

ROUTE=$(ip route get "$TARGET_IP")
log_pass "Route to ${TARGET_IP}:"
echo "$ROUTE" | sed 's/^/  /'
echo ""

# Verify route is reachable
if echo "$ROUTE" | grep -q "unreachable"; then
  log_fail "Target ${TARGET_IP} is unreachable (route shows 'unreachable')"
  exit 1
elif echo "$ROUTE" | grep -q "dev"; then
  log_pass "Route exists and target appears reachable"
else
  log_fail "Cannot determine route to ${TARGET_IP}"
fi
echo ""

# ============================================================
# 3. LAYER 2 (ARP) VERIFICATION
# ============================================================

log_step "Checking ARP (Layer 2 reachability)..."
echo ""

# Ping to populate ARP
ping -c 1 -W 2 "$TARGET_IP" &>/dev/null || true

ARP_ENTRY=$(arp -n | grep "$TARGET_IP" || echo "NOT_FOUND")
if [ "$ARP_ENTRY" != "NOT_FOUND" ]; then
  log_pass "ARP entry exists for ${TARGET_IP}:"
  echo "  $ARP_ENTRY"
else
  log_fail "No ARP entry for ${TARGET_IP}"
  log_info "Attempting to resolve via ping..."
  if timeout 5 ping -c 3 "$TARGET_IP" 2>&1 | tee /tmp/ping_test.log; then
    log_pass "Ping succeeded - instance is reachable"
    # Try ARP again
    arp -n | grep "$TARGET_IP" || log_fail "Still no ARP entry after ping"
  else
    log_fail "Ping failed - target not responding on ICMP"
    log_info "This could indicate:"
    log_info "  - Target instance is down"
    log_info "  - Security group blocks ICMP"
    log_info "  - Network ACL blocks ICMP"
  fi
fi
echo ""

# ============================================================
# 4. LAYER 3 (ICMP) VERIFICATION
# ============================================================

log_step "Testing Layer 3 (ICMP - Ping)..."
echo ""

if timeout 5 ping -c 3 "$TARGET_IP"; then
  log_pass "ICMP ping successful"
else
  log_fail "ICMP ping failed"
  log_info "Target may not respond to ICMP, trying TCP SYN test..."
fi
echo ""

# ============================================================
# 5. LAYER 4 (TCP) VERIFICATION
# ============================================================

log_step "Testing Layer 4 (TCP - Port ${PORT})..."
echo ""

# Try multiple test methods
if timeout 5 bash -c "echo > /dev/tcp/${TARGET_IP}/${PORT}" 2>/dev/null; then
  log_pass "TCP port ${PORT} is OPEN (SYN/ACK received)"
elif timeout 5 bash -c "cat < /dev/null > /dev/tcp/${TARGET_IP}/${PORT}" 2>/dev/null; then
  log_pass "TCP port ${PORT} is OPEN"
else
  # Try nc as backup
  if command -v nc &>/dev/null; then
    log_fail "TCP port ${PORT} test failed with /dev/tcp, trying nc..."
    if timeout 5 nc -zv "$TARGET_IP" "$PORT" 2>&1; then
      log_pass "nc: Port ${PORT} is OPEN"
    else
      log_fail "nc: Port ${PORT} is CLOSED or no response"
    fi
  else
    log_fail "TCP port ${PORT} test failed (cannot use /dev/tcp or nc)"
  fi
fi
echo ""

# ============================================================
# 6. FIREWALL VERIFICATION (LOCAL)
# ============================================================

log_step "Checking local firewall (this instance)..."
echo ""

# Check firewalld
if systemctl is-active --quiet firewalld 2>/dev/null; then
  log_pass "firewalld is running"
  log_info "Allowed ports:"
  firewall-cmd --list-ports
  log_info "Allowed services:"
  firewall-cmd --list-services
  
  # Check if we're blocking outbound to target
  if [ "$MY_IP" != "$TARGET_IP" ]; then
    log_info "Checking egress rules (you shouldn't block outbound by default on RHEL)..."
  fi
else
  log_info "firewalld not running"
fi
echo ""

# Check iptables
if command -v iptables &>/dev/null; then
  if ! systemctl is-active --quiet firewalld 2>/dev/null; then
    log_info "Checking iptables rules..."
    if iptables -L INPUT -n | grep -q "Chain INPUT"; then
      DENY_COUNT=$(iptables -L INPUT -n | grep -c "DROP\|REJECT" || echo "0")
      if [ "$DENY_COUNT" -gt 0 ]; then
        log_fail "iptables has ${DENY_COUNT} DROP/REJECT rules"
        iptables -L INPUT -n | grep "DROP\|REJECT" || true
      else
        log_pass "No DROP/REJECT rules in iptables INPUT"
      fi
    fi
  fi
else
  log_info "iptables not found"
fi
echo ""

# ============================================================
# 7. SELINUX VERIFICATION
# ============================================================

log_step "Checking SELinux..."
echo ""

if command -v getenforce &>/dev/null; then
  SE_STATUS=$(getenforce)
  log_info "SELinux status: ${SE_STATUS}"
  
  if [ "$SE_STATUS" == "Disabled" ]; then
    log_pass "SELinux disabled - not blocking traffic"
  elif [ "$SE_STATUS" == "Permissive" ]; then
    log_pass "SELinux in permissive mode - logging but not blocking"
  else
    log_fail "SELinux is Enforcing - may block traffic on port ${PORT}"
    if command -v semanage &>/dev/null; then
      log_info "Checking port ${PORT} in SELinux policy..."
      semanage port -l | grep "${PORT}" || log_fail "Port ${PORT} not in SELinux policy"
    fi
  fi
else
  log_pass "SELinux tools not found (likely disabled or not installed)"
fi
echo ""

# ============================================================
# 8. SERVICE STATUS ON LOCAL INSTANCE
# ============================================================

log_step "Checking for services listening on port ${PORT}..."
echo ""

if ss -tlnp | grep -q ":${PORT}"; then
  log_pass "Something is listening on port ${PORT}:"
  ss -tlnp | grep ":${PORT}"
else
  log_fail "Nothing listening on port ${PORT}"
  log_info "All listening ports on this instance:"
  ss -tlnp || netstat -tlnp
fi
echo ""

# ============================================================
# 9. MTU VERIFICATION
# ============================================================

log_step "Checking MTU (packet size)..."
echo ""

MTU=$(ip link show "$IFACE" | grep mtu | awk '{print $5}')
log_pass "Interface MTU: ${MTU}"

if [ "$MTU" -lt 1500 ]; then
  log_fail "MTU is ${MTU} (standard is 1500, small MTU may cause issues)"
else
  log_pass "MTU is standard size"
fi
echo ""

# ============================================================
# 10. PACKET CAPTURE TEST
# ============================================================

log_step "Optional: Packet capture for debugging..."
echo ""

if command -v tcpdump &>/dev/null; then
  log_info "To capture traffic between instances, run:"
  log_info "  sudo tcpdump -i any -n 'host ${TARGET_IP}' -v"
  log_info ""
  log_info "Then from other instance, try to connect:"
  log_info "  curl http://${MY_IP}:${PORT}/"
  log_info "  echo > /dev/tcp/${MY_IP}/${PORT}"
else
  log_info "tcpdump not installed - cannot capture"
fi
echo ""

# ============================================================
# SUMMARY
# ============================================================

echo "========================================="
echo "Network Verification Summary"
echo "========================================="
echo ""

# Determine key status
ICMP_PASS=false
TCP_PASS=false
ROUTE_PASS=false

if timeout 3 ping -c 1 "$TARGET_IP" &>/dev/null; then ICMP_PASS=true; fi
if timeout 3 bash -c "echo > /dev/tcp/${TARGET_IP}/${PORT}" 2>/dev/null; then TCP_PASS=true; fi
if ip route get "$TARGET_IP" | grep -q "dev"; then ROUTE_PASS=true; fi

echo "Status Summary:"
echo "  Routing to ${TARGET_IP}: $([ "$ROUTE_PASS" == "true" ] && echo "✓ PASS" || echo "✗ FAIL")"
echo "  ICMP (Ping): $([ "$ICMP_PASS" == "true" ] && echo "✓ PASS" || echo "✗ FAIL")"
echo "  TCP Port ${PORT}: $([ "$TCP_PASS" == "true" ] && echo "✓ PASS" || echo "✗ FAIL (service not listening)")"
echo ""

if [ "$ROUTE_PASS" == "false" ]; then
  echo "→ Routing Problem: Check VPC route tables and internet gateway"
elif [ "$ICMP_PASS" == "false" ]; then
  echo "→ Network Level Problem: Firewall blocking ICMP (check AWS Security Groups + NACLs)"
elif [ "$TCP_PASS" == "false" ]; then
  echo "→ Service Level Problem: Port ${PORT} not listening or firewall blocking TCP"
else
  echo "→ All systems GO! Instances can communicate"
fi
echo ""

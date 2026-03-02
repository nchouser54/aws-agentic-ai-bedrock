#!/usr/bin/env bash
# Test container-to-RHEL8 connectivity
# Run FROM the RHEL9 container
# Usage: ./test_container_rhel_connectivity.sh <RHEL8_IP> <PORT> [SERVICE_NAME]

set -euo pipefail

RHEL8_IP="${1:?Usage: $0 <RHEL8_IP> <PORT> [SERVICE_NAME]}"
PORT="${2:?Usage: $0 <RHEL8_IP> <PORT> [SERVICE_NAME]}"
SERVICE_NAME="${3:-unknown}"
TIMEOUT=5

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_step() {
  echo -e "${YELLOW}[*]${NC} $1"
}

log_pass() {
  echo -e "${GREEN}[✓]${NC} $1"
}

log_fail() {
  echo -e "${RED}[✗]${NC} $1"
}

echo "========================================="
echo "Container → RHEL8 Connectivity Diagnostic"
echo "========================================="
echo "Target: ${RHEL8_IP}:${PORT} (${SERVICE_NAME})"
echo ""

# 1. Network connectivity (ICMP)
log_step "Testing ICMP (ping)..."
if timeout $TIMEOUT ping -c 1 "${RHEL8_IP}" &>/dev/null; then
  log_pass "ICMP reachable"
else
  log_fail "ICMP unreachable (network layer issue)"
  exit 1
fi
echo ""

# 2. Layer 4 connectivity (TCP)
log_step "Testing TCP connection to ${RHEL8_IP}:${PORT}..."
if timeout $TIMEOUT bash -c "echo > /dev/tcp/${RHEL8_IP}/${PORT}" 2>/dev/null; then
  log_pass "TCP port ${PORT} open (SYN ACK received)"
else
  log_fail "TCP port ${PORT} closed or not responding to new connections"
  # Try nc for more detail
  if command -v nc &>/dev/null; then
    echo "  Attempting nc diagnostic..."
    bash -c "nc -zv -w $TIMEOUT ${RHEL8_IP} ${PORT} 2>&1" || true
  fi
fi
echo ""

# 3. DNS check
log_step "Checking DNS resolution..."
if host "${RHEL8_IP}" &>/dev/null || nslookup "${RHEL8_IP}" &>/dev/null; then
  log_pass "DNS resolution OK"
else
  log_pass "No DNS entry (using IP directly is fine)"
fi
echo ""

# 4. Routing check
log_step "Checking routing to ${RHEL8_IP}..."
if ip route get "${RHEL8_IP}" &>/dev/null; then
  ROUTE=$(ip route get "${RHEL8_IP}")
  log_pass "Route exists: ${ROUTE}"
else
  log_fail "No route to ${RHEL8_IP}"
fi
echo ""

# 5. Check local firewall rules
log_step "Checking container firewall (iptables)..."
if command -v iptables &>/dev/null; then
  # Check for DROP rules
  if iptables -L -n | grep -q DROP; then
    log_fail "iptables has DROP rules, may be blocking traffic"
    echo "  Rules:"
    iptables -L -n | grep -E "(DROP|REJECT)" || true
  else
    log_pass "No obvious DROP/REJECT rules found"
  fi
else
  log_pass "iptables not available (likely not an issue in container)"
fi
echo ""

# 6. Check SELinux context
log_step "Checking SELinux context..."
if command -v getenforce &>/dev/null; then
  SE_STATUS=$(getenforce 2>/dev/null || echo "Disabled")
  if [ "$SE_STATUS" != "Disabled" ]; then
    log_fail "SELinux is ${SE_STATUS} — may block traffic"
    echo "  Run on RHEL8: 'semanage port -l | grep ${PORT}' to check port context"
  else
    log_pass "SELinux disabled"
  fi
else
  log_pass "SELinux tools not in container"
fi
echo ""

# 7. Try application-level connection with timeout
log_step "Attempting application-level connection on ${PORT}..."
echo ""

# HTTP test (port 80/443)
if [ "$PORT" == "80" ] || [ "$PORT" == "8080" ]; then
  echo "  Testing HTTP GET..."
  if command -v curl &>/dev/null; then
    if timeout $TIMEOUT curl -v "http://${RHEL8_IP}:${PORT}/" 2>&1 | head -20; then
      log_pass "HTTP connection successful"
    else
      log_fail "HTTP connection failed or no response"
    fi
  fi
elif [ "$PORT" == "443" ] || [ "$PORT" == "8443" ]; then
  echo "  Testing HTTPS..."
  if command -v curl &>/dev/null; then
    if timeout $TIMEOUT curl -v -k "https://${RHEL8_IP}:${PORT}/" 2>&1 | head -20; then
      log_pass "HTTPS connection successful"
    else
      log_fail "HTTPS connection failed"
    fi
  fi
else
  echo "  Custom port ${PORT} — using nc for raw test..."
  if command -v nc &>/dev/null; then
    echo "quit" | timeout $TIMEOUT nc -v "${RHEL8_IP}" "${PORT}" 2>&1 || log_fail "No response from port ${PORT}"
  else
    log_fail "nc not found, cannot test application protocol on port ${PORT}"
  fi
fi
echo ""

# Summary
echo "========================================="
echo "Diagnostic Summary:"
echo "========================================="
echo "If ICMP + TCP both pass but application fails:"
echo "  1. SSH to RHEL8 and check: ss -tlnp | grep ${PORT}"
echo "  2. Verify the service is running: systemctl status <service>"
echo "  3. Check RHEL8 firewall:"
echo "     - firewall-cmd --list-ports"
echo "     - firewall-cmd --list-services"
echo "  4. Check RHEL8 SELinux:"
echo "     - getenforce"
echo "     - semanage port -l | grep ${PORT}"
echo "  5. Check RHEL8 iptables (if firewalld not used):"
echo "     - iptables -L -n -v"
echo ""
echo "If TCP fails but ICMP passes:"
echo "  1. Verify RHEL8 has a listener on port ${PORT}"
echo "  2. Check RHEL8 firewall rules: firewall-cmd --list-all"
echo "  3. Check security groups / network ACLs (if in VPC)"
echo ""

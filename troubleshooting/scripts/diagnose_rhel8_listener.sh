#!/usr/bin/env bash
# Diagnostic script to run on RHEL8 to debug why connections are arriving but failing
# Run FROM RHEL8 (host side)
# Usage: ./diagnose_rhel8_listener.sh <PORT> [SERVICE_NAME]

set -euo pipefail

PORT="${1:?Usage: $0 <PORT> [SERVICE_NAME]}"
SERVICE_NAME="${2:-unknown}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_step() {
  echo -e "${YELLOW}[*]${NC} $1"
}

log_pass() {
  echo -e "${GREEN}[✓]${NC} $1"
}

log_fail() {
  echo -e "${RED}[✗]${NC} $1"
}

log_info() {
  echo -e "${BLUE}[i]${NC} $1"
}

echo "========================================="
echo "RHEL8 Service Listener Diagnostic"
echo "========================================="
echo "Port: ${PORT}"
echo "Service: ${SERVICE_NAME}"
echo ""

# 1. Check if port is listening
log_step "Checking if port ${PORT} is listening..."
echo ""

if command -v ss &>/dev/null; then
  echo "  Using ss (modern):"
  ss -tlnp | grep ":${PORT}" || {
    log_fail "Port ${PORT} not found in ss output"
    echo ""
    echo "  All listening ports:"
    ss -tlnp || true
    echo ""
  }
elif command -v netstat &>/dev/null; then
  echo "  Using netstat (legacy):"
  netstat -tlnp | grep ":${PORT}" || {
    log_fail "Port ${PORT} not found in netstat output"
  }
else
  log_fail "Neither ss nor netstat available"
fi
echo ""

# 2. Check firewall (firewalld)
log_step "Checking firewalld (preferred on RHEL)..."
if systemctl is-active --quiet firewalld; then
  log_pass "firewalld is active"
  echo ""
  echo "  Allowed ports:"
  firewall-cmd --list-ports || echo "  (no specific ports listed)"
  echo ""
  echo "  Allowed services:"
  firewall-cmd --list-services || echo "  (no services listed)"
  echo ""
  
  if firewall-cmd --query-port="${PORT}/tcp" &>/dev/null; then
    log_pass "Port ${PORT}/tcp is explicitly allowed in firewalld"
  else
    log_fail "Port ${PORT}/tcp is NOT explicitly allowed in firewalld"
    echo "  Fix with: sudo firewall-cmd --permanent --add-port=${PORT}/tcp && sudo firewall-cmd --reload"
  fi
else
  log_info "firewalld is not active"
fi
echo ""

# 3. Check iptables (if firewalld not used)
log_step "Checking iptables rules..."
if command -v iptables &>/dev/null; then
  if ! systemctl is-active --quiet firewalld; then
    echo "  Firewalld not running, checking raw iptables..."
    echo ""
    
    # Check INPUT chain for port
    if iptables -L INPUT -n -v | grep -q "${PORT}"; then
      log_pass "Port ${PORT} found in iptables INPUT chain"
    else
      log_fail "Port ${PORT} NOT found in iptables INPUT chain"
      echo ""
      echo "  Current INPUT rules:"
      iptables -L INPUT -n -v || true
    fi
  else
    log_info "firewalld is active, iptables may be managed by it"
  fi
else
  log_fail "iptables not available"
fi
echo ""

# 4. Check SELinux port context
log_step "Checking SELinux context for port ${PORT}..."
if command -v getenforce &>/dev/null; then
  SE_STATUS=$(getenforce 2>/dev/null || echo "Disabled")
  echo "  SELinux status: ${SE_STATUS}"
  
  if [ "$SE_STATUS" != "Disabled" ]; then
    if command -v semanage &>/dev/null; then
      echo ""
      echo "  Checking port ${PORT} in SELinux policy..."
      semanage port -l | grep "${PORT}" || {
        log_fail "Port ${PORT} not defined in SELinux policy"
        echo "  This may be the issue! Fix with:"
        echo "    sudo semanage port -a -t http_port_t -p tcp ${PORT}"
        echo "  Or check the service-specific port type:"
        echo "    sudo semanage port -l | grep <service_name>"
      }
    else
      log_fail "semanage not available, cannot check SELinux port policy"
    fi
  else
    log_pass "SELinux disabled"
  fi
else
  log_pass "SELinux tools not available"
fi
echo ""

# 5. Check if service is running
log_step "Checking if service '${SERVICE_NAME}' is running..."
if [ "$SERVICE_NAME" != "unknown" ]; then
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    log_pass "Service ${SERVICE_NAME} is running"
    echo ""
    systemctl status "${SERVICE_NAME}" || true
  else
    log_fail "Service ${SERVICE_NAME} is NOT running"
    echo "  Start with: sudo systemctl start ${SERVICE_NAME}"
  fi
else
  log_info "Service name not provided, cannot check status"
fi
echo ""

# 6. Test local connection
log_step "Testing localhost connection to port ${PORT}..."
if timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/${PORT}" 2>/dev/null; then
  log_pass "localhost:${PORT} accepts connections"
else
  log_fail "localhost:${PORT} does NOT accept connections"
  log_fail "The service may not be bound to all interfaces or responding"
fi
echo ""

# 7. Check all network interfaces
log_step "Checking which interfaces service is bound to..."
if command -v ss &>/dev/null; then
  ss -tlnp | grep "LISTEN" || true
else
  netstat -tln | grep "LISTEN" || true
fi
echo ""

# 8. Capture traffic to see SYN/RST
log_step "Ready to capture traffic for debugging..."
echo ""
echo "  If you want to see inbound SYN packets being RST'd:"
echo "    sudo tcpdump -i any -n 'tcp port ${PORT}' -v"
echo ""
echo "  Or monitor the service logs:"
echo "    sudo journalctl -u ${SERVICE_NAME} -f"
echo "    tail -f /var/log/<service>.log"
echo ""

# 9. Summary
echo "========================================="
echo "Next Steps if Connection Still Fails:"
echo "========================================="
echo ""
echo "Priority 1 (most likely):"
echo "  ✓ Verify port is in ss/netstat output (must show LISTEN state)"
echo "  ✓ Check firewalld: firewall-cmd --list-ports"
echo "  ✓ Check SELinux: getenforce + semanage port -l"
echo ""
echo "Priority 2 (if service is running):"
echo "  ✓ Check service logs: journalctl -u ${SERVICE_NAME} -n 50"
echo "  ✓ Verify service config binds to 0.0.0.0 or specific IP"
echo "  ✓ Check /etc/hosts or DNS if hostname resolution involved"
echo ""
echo "Priority 3 (network-level):"
echo "  ✓ Verify container can reach RHEL8: ping from container"
echo "  ✓ Verify RHEL8 can route back: check routing tables"
echo "  ✓ Check security groups / network ACLs if in cloud"
echo ""

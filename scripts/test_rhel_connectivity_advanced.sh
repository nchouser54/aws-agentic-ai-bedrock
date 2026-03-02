#!/usr/bin/env bash
# Advanced troubleshooting script for container → RHEL8 connectivity issues
# Run FROM container or RHEL9 dev box
# This script attempts connections at different layers and captures diagnostics

set -euo pipefail

RHEL8_IP="${1:?Usage: $0 <RHEL8_IP> <PORT> [PROTOCOL]}"
PORT="${2:?Usage: $0 <RHEL8_IP> <PORT> [PROTOCOL]}"
PROTOCOL="${3:-tcp}"  # tcp, http, https
TIMEOUT=5

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Create temp dir for captures
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

log_step() { echo -e "${YELLOW}[*]${NC} $1"; }
log_pass() { echo -e "${GREEN}[✓]${NC} $1"; }
log_fail() { echo -e "${RED}[✗]${NC} $1"; }
log_info() { echo -e "${BLUE}[i]${NC} $1"; }

echo "=============================================================="
echo "Container → RHEL8 Advanced Connectivity Troubleshooting"
echo "=============================================================="
echo "Target: ${RHEL8_IP}:${PORT} (Protocol: ${PROTOCOL})"
echo "Capture directory: ${TMPDIR}"
echo ""

# ============================================================
# LAYER 2-3: Network Connectivity
# ============================================================

log_step "LAYER 2-3: Network Connectivity"
echo ""

# Check ARP (if Linux)
if command -v arp &>/dev/null; then
  log_info "ARP cache for ${RHEL8_IP}:"
  arp -n | grep "${RHEL8_IP}" || log_fail "Target not in ARP cache (not critical)"
  echo ""
fi

# ICMP test with capture
if command -v timeout &>/dev/null && command -v ping &>/dev/null; then
  log_info "Testing ICMP connectivity..."
  if timeout 3 ping -c 3 "${RHEL8_IP}" 2>&1 | tee "${TMPDIR}/ping.log"; then
    log_pass "ICMP reachable"
  else
    log_fail "ICMP not reachable"
  fi
  echo ""
fi

# ============================================================
# LAYER 4: TCP SYN/ACK
# ============================================================

log_step "LAYER 4: TCP SYN/ACK Test"
echo ""

# TCP test with verbose output
if [ "$PROTOCOL" == "http" ] && ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
  PROTOCOL="tcp"
fi

case "$PROTOCOL" in
  tcp|raw)
    log_info "Testing TCP SYN to ${RHEL8_IP}:${PORT}..."
    if timeout $TIMEOUT bash -c "echo > /dev/tcp/${RHEL8_IP}/${PORT}" 2>"${TMPDIR}/tcp_test.err"; then
      log_pass "TCP SYN/ACK received (port open)"
    else
      log_fail "TCP failed; checking with nc for more info..."
      if command -v nc &>/dev/null; then
        nc -zv -w $TIMEOUT "${RHEL8_IP}" "${PORT}" 2>&1 | tee "${TMPDIR}/nc_test.log" || true
      fi
    fi
    ;;
  http)
    log_info "Testing HTTP connection..."
    if command -v curl &>/dev/null; then
      if timeout $TIMEOUT curl -v -w "\nHTTP Status: %{http_code}\n" \
        "http://${RHEL8_IP}:${PORT}/" 2>&1 | tee "${TMPDIR}/http_test.log"; then
        log_pass "HTTP connection successful"
      else
        log_fail "HTTP request failed"
      fi
    elif command -v wget &>/dev/null; then
      if timeout $TIMEOUT wget -v -O- "http://${RHEL8_IP}:${PORT}/" 2>&1 | tee "${TMPDIR}/http_test.log"; then
        log_pass "HTTP connection successful"
      else
        log_fail "HTTP request failed"
      fi
    else
      log_fail "curl/wget not found, cannot test HTTP"
    fi
    ;;
  https)
    log_info "Testing HTTPS connection (insecure)..."
    if command -v curl &>/dev/null; then
      if timeout $TIMEOUT curl -v -k "https://${RHEL8_IP}:${PORT}/" 2>&1 | tee "${TMPDIR}/https_test.log"; then
        log_pass "HTTPS connection successful"
      else
        log_fail "HTTPS request failed"
      fi
    else
      log_fail "curl not found, cannot test HTTPS"
    fi
    ;;
esac
echo ""

# ============================================================
# Packet Capture (requires elevated privileges)
# ============================================================

log_step "PACKET CAPTURE (tcpdump)"
echo ""

if command -v tcpdump &>/dev/null; then
  log_info "Attempting to capture traffic (may need sudo)..."
  
  # Try to capture (won't fail if no permission)
  if timeout 3 tcpdump -i any -n "host ${RHEL8_IP} and port ${PORT}" -c 10 -w "${TMPDIR}/traffic.pcap" 2>/dev/null || true; then
    if [ -f "${TMPDIR}/traffic.pcap" ] && [ -s "${TMPDIR}/traffic.pcap" ]; then
      log_pass "Captured packets to traffic.pcap"
      # Decode pcap
      if command -v tcpdump &>/dev/null; then
        echo ""
        echo "  Packet summary:"
        tcpdump -r "${TMPDIR}/traffic.pcap" -n 2>/dev/null || true
      fi
    fi
  else
    log_fail "Could not capture (may need sudo: sudo tcpdump -i any -n 'host ${RHEL8_IP} and port ${PORT}' -v)"
  fi
else
  log_fail "tcpdump not installed"
fi
echo ""

# ============================================================
# DNS & Hostname Resolution
# ============================================================

log_step "DNS & Hostname Resolution"
echo ""

if command -v nslookup &>/dev/null; then
  if nslookup "${RHEL8_IP}" &>/dev/null 2>&1; then
    log_pass "${RHEL8_IP} resolves"
  else
    log_info "${RHEL8_IP} does not resolve (IP address used directly)"
  fi
fi

if [ -f /etc/hosts ]; then
  if grep -q "${RHEL8_IP}" /etc/hosts; then
    log_pass "Found in /etc/hosts:"
    grep "${RHEL8_IP}" /etc/hosts
  fi
fi
echo ""

# ============================================================
# Local Environment
# ============================================================

log_step "LOCAL ENVIRONMENT"
echo ""

log_info "Network interfaces:"
if command -v ip &>/dev/null; then
  ip addr | grep "inet" || true
else
  ifconfig 2>/dev/null | grep "inet" || true
fi
echo ""

log_info "Routing to ${RHEL8_IP}:"
if command -v ip &>/dev/null; then
  ip route get "${RHEL8_IP}" 2>/dev/null || echo "  No route found"
else
  route -n | grep "${RHEL8_IP}" || echo "  No route found"
fi
echo ""

log_info "Local firewall rules (iptables):"
if command -v iptables &>/dev/null; then
  iptables -L -n | grep -E "(DROP|REJECT|${PORT})" || echo "  No DROP/REJECT rules visible"
fi
echo ""

log_info "Container network namespace:"
if [ -f /proc/net/tcp ]; then
  # Check if port is listening locally
  if cat /proc/net/tcp | awk '{print $2}' | grep -q "$(printf '%X' $PORT)"; then
    log_pass "Port ${PORT} is listening locally in this container"
  fi
fi
echo ""

# ============================================================
# DIAGNOSIS SUMMARY
# ============================================================

echo "=============================================================="
echo "DIAGNOSIS SUMMARY"
echo "=============================================================="
echo ""

# Create summary based on test results
if grep -q "tcp open\|LISTEN\|SYN_RECV" "${TMPDIR}"/*.log 2>/dev/null || \
   timeout $TIMEOUT bash -c "echo > /dev/tcp/${RHEL8_IP}/${PORT}" 2>/dev/null; then
  echo "✓ Network connectivity: PASS"
  echo "✓ TCP layer: PASS"
  echo ""
  echo "→ Application layer issue likely. On RHEL8, verify:"
  echo "  1. ps aux | grep -i <service>"
  echo "  2. ss -tlnp | grep ${PORT}"
  echo "  3. sudo firewall-cmd --list-all"
  echo "  4. sudo semanage port -l | grep ${PORT}"
else
  echo "✗ Network connectivity: FAIL"
  echo ""
  echo "→ Possible causes:"
  echo "  1. RHEL8 not listening on port ${PORT}"
  echo "  2. RHEL8 firewall blocking port ${PORT}"
  echo "  3. Network connectivity issue"
  echo ""
  echo "→ Next steps:"
  echo "  1. SSH to RHEL8 and run: ./diagnose_rhel8_listener.sh ${PORT}"
  echo "  2. Or check: firewall-cmd --list-ports"
fi

echo ""
echo "Full diagnostic logs saved to: ${TMPDIR}"
echo "  - ping.log: ICMP test results"
echo "  - tcp_test.err: TCP connection error"
echo "  - nc_test.log: netcat verbose output (if TCP failed)"
echo "  - http_test.log: HTTP test results (if applicable)"
echo "  - traffic.pcap: Packet capture (if tcpdump available)"
echo ""

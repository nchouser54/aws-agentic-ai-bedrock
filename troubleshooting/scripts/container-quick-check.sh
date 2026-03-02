#!/usr/bin/env bash
# Ultra-fast container->RHEL8 connectivity check (30 sec)
# Run INSIDE container
# Usage: ./container-quick-check.sh <RHEL8_IP> <PORT>
# Exit code: 0=all reachable, 1=network fail, 2=partial/warnings

set -euo pipefail

TARGET="${1:?Usage: $0 <RHEL8_IP> <PORT>}"
PORT="${2:-443}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_pass() { echo -e "${GREEN}[✓]${NC} $1"; }
log_fail() { echo -e "${RED}[✗]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }

PASS=0
FAIL=0
WARN=0

# Resolve target
TARGET_IP="$TARGET"
if ! [[ "$TARGET" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  if command -v getent >/dev/null 2>&1; then
    TARGET_IP=$(getent ahostsv4 "$TARGET" 2>/dev/null | awk 'NR==1{print $1}' || echo "$TARGET")
  fi
fi

echo "Quick connectivity check: ${TARGET}:${PORT}"
echo ""

# Test 1: TCP connect
if timeout 3 bash -c "</dev/tcp/${TARGET_IP}/${PORT}" 2>/dev/null; then
  log_pass "TCP connect successful"
  PASS=$((PASS + 1))
else
  log_fail "TCP connect FAILED"
  FAIL=$((FAIL + 1))
fi

# Test 2: nc if available
if command -v nc >/dev/null 2>&1; then
  if nc -z -w 2 "$TARGET_IP" "$PORT" >/dev/null 2>&1; then
    log_pass "nc connectivity check passed"
    PASS=$((PASS + 1))
  else
    log_warn "nc check failed (may be network or firewall)"
    WARN=$((PASS + 1))
  fi
fi

# Test 3: DNS (if hostname given)
if ! [[ "$TARGET" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  if [[ "$TARGET_IP" != "$TARGET" ]]; then
    log_pass "DNS resolved ${TARGET} -> ${TARGET_IP}"
    PASS=$((PASS + 1))
  else
    log_fail "DNS failed for ${TARGET}"
    FAIL=$((FAIL + 1))
  fi
fi

echo ""
if (( FAIL > 0 )); then
  echo "RESULT: FAILED - Check RHEL8 listener/firewall/SG"
  exit 1
elif (( WARN > 0 )); then
  echo "RESULT: PARTIAL - Some warnings; may still work"
  exit 2
else
  echo "RESULT: SUCCESS - RHEL8 is reachable"
  exit 0
fi

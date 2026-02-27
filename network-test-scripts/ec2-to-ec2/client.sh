#!/usr/bin/env bash
# client.sh - Test TCP connectivity from this EC2 to a remote host/port.
# Run this on the SENDER EC2.
#
# Usage: ./client.sh <HOST> [PORT] [TIMEOUT_SECS]
#   HOST          IP or hostname of the remote EC2
#   PORT          Port to connect to (default: 8080)
#   TIMEOUT_SECS  Connection timeout in seconds (default: 5)
#
# Example:
#   ./client.sh 10.0.1.50 21240
#   ./client.sh 10.0.1.50 21240 10

set -euo pipefail

# ── Load shared config (network-test-scripts/test.env) ──────────────────────
_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/test.env"
# shellcheck source=/dev/null
[[ -f "${_CFG}" ]] && source "${_CFG}"

HOST="${1:-${RHEL9_IP:-}}"
PORT="${2:-${TEST_PORT:-8080}}"
TIMEOUT="${3:-${TIMEOUT_SECS:-5}}"

if [[ -z "${HOST}" ]]; then
    echo "Usage: $0 <HOST> [PORT] [TIMEOUT_SECS]"
    exit 1
fi

echo "============================================="
echo " EC2 NC CLIENT TEST"
echo "============================================="
echo " Target  : ${HOST}:${PORT}"
echo " Timeout : ${TIMEOUT}s"
echo " From    : $(hostname) ($(hostname -I | awk '{print $1}'))"
echo " Time    : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================="
echo ""

# ---------- DNS check ----------
echo "[STEP 1] DNS / reachability pre-check"
if command -v ping &>/dev/null; then
    if ping -c 2 -W 2 "${HOST}" &>/dev/null; then
        echo "  [OK ] ping to ${HOST} succeeded"
    else
        echo "  [WARN] ping to ${HOST} failed (ICMP may be blocked — continuing)"
    fi
fi

# ---------- nc connect test ----------
echo ""
echo "[STEP 2] nc TCP connect test  (${HOST}:${PORT}, timeout=${TIMEOUT}s)"
if nc -vz -w "${TIMEOUT}" "${HOST}" "${PORT}" 2>&1; then
    echo ""
    echo "[RESULT] SUCCESS — port ${PORT} is open and accepting connections."
else
    echo ""
    echo "[RESULT] FAILURE — could not connect to ${HOST}:${PORT} within ${TIMEOUT}s."
    echo ""
    echo "Common causes:"
    echo "  1. firewalld/iptables is blocking the port on the receiver"
    echo "  2. AWS Security Group does not allow inbound on port ${PORT}"
    echo "  3. nc server is not running (or bound to 127.0.0.1 only)"
    echo "  4. If source is a Podman container: masquerade / port-publish issue"
    echo ""
    echo "Run diagnostics/full_diagnostic.sh on both hosts for details."
    exit 1
fi

# ---------- send test payload ----------
echo ""
echo "[STEP 3] Sending test payload over connection..."
echo "HELLO_FROM_$(hostname)_AT_$(date -u '+%H:%M:%SZ')" | \
    nc -w "${TIMEOUT}" "${HOST}" "${PORT}" 2>&1 && \
    echo "  [OK ] Payload sent." || \
    echo "  [WARN] Payload send failed (server may not be in persistent mode)"

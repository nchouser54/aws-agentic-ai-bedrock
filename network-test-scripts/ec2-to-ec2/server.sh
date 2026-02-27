#!/usr/bin/env bash
# server.sh - Start an nc listener on a specified port for EC2-to-EC2 testing.
# Run this on the RECEIVER EC2 (RHEL8).
#
# Usage: ./server.sh [PORT] [BIND_ADDR]
#   PORT        Port to listen on (default: 8080)
#   BIND_ADDR   Address to bind to (default: 0.0.0.0 = all interfaces)
#
# Example:
#   ./server.sh 21240
#   ./server.sh 21240 0.0.0.0

set -euo pipefail

# ── Load shared config (network-test-scripts/test.env) ──────────────────────
_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/test.env"
# shellcheck source=/dev/null
[[ -f "${_CFG}" ]] && source "${_CFG}"

PORT="${1:-${TEST_PORT:-8080}}"
BIND_ADDR="${2:-0.0.0.0}"

echo "============================================="
echo " EC2 NC LISTENER"
echo "============================================="
echo " Listening on : ${BIND_ADDR}:${PORT}"
echo " Timestamp    : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo " Hostname     : $(hostname -f 2>/dev/null || hostname)"
echo " Kernel       : $(uname -r)"
echo "============================================="
echo ""
echo "[INFO] If nc receives a connection you will see data below."
echo "[INFO] Press Ctrl+C to stop."
echo ""

# Detect nc flavour (ncat vs traditional netcat)
if nc --version 2>&1 | grep -qi ncat; then
    # ncat (nmap package) – preferred on RHEL
    exec nc -lvk --source-port "${PORT}" -s "${BIND_ADDR}" 2>&1
else
    # Traditional netcat (may not support -s)
    exec nc -lvp "${PORT}" 2>&1
fi

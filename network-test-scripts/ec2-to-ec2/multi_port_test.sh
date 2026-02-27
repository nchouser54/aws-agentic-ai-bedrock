#!/usr/bin/env bash
# multi_port_test.sh - Scan a list of ports against a remote host.
# Useful for quickly finding which ports are open vs blocked.
# Run this on the SENDER EC2.
#
# Usage: ./multi_port_test.sh <HOST> [PORT_LIST] [TIMEOUT_SECS]
#   HOST        Target IP or hostname
#   PORT_LIST   Comma-separated ports (default: 21240,80,443,8080,8443,9000,9090,5000,6000)
#   TIMEOUT     Per-port timeout in seconds (default: 3)
#
# Example:
#   ./multi_port_test.sh 10.0.1.50
#   ./multi_port_test.sh 10.0.1.50 9000,9001,9002
#   ./multi_port_test.sh 10.0.1.50 8080,9000,5432 5

set -euo pipefail

# ── Load shared config (network-test-scripts/test.env) ──────────────────────
_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/test.env"
# shellcheck source=/dev/null
[[ -f "${_CFG}" ]] && source "${_CFG}"

HOST="${1:-${RHEL9_IP:-}}"
PORT_LIST="${2:-${TEST_PORT:-21240},80,443,8080,8443,9000,9090,5000,6000}"
TIMEOUT="${3:-${TIMEOUT_SECS:-3}}"

if [[ -z "${HOST}" ]]; then
    echo "Usage: $0 <HOST> [PORT_LIST] [TIMEOUT_SECS]"
    exit 1
fi

IFS=',' read -ra PORTS <<< "${PORT_LIST}"

echo "============================================="
echo " MULTI-PORT TCP SCAN"
echo "============================================="
echo " Target  : ${HOST}"
echo " Ports   : ${PORT_LIST}"
echo " Timeout : ${TIMEOUT}s / port"
echo " Time    : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================="
echo ""

OPEN=()
CLOSED=()

for PORT in "${PORTS[@]}"; do
    PORT="${PORT// /}"  # strip spaces
    printf "  Testing port %-6s ... " "${PORT}"
    if nc -z -w "${TIMEOUT}" "${HOST}" "${PORT}" 2>/dev/null; then
        echo "OPEN"
        OPEN+=("${PORT}")
    else
        echo "CLOSED / FILTERED"
        CLOSED+=("${PORT}")
    fi
done

echo ""
echo "============================================="
echo " SUMMARY"
echo "============================================="
echo " OPEN   (${#OPEN[@]}): ${OPEN[*]:-none}"
echo " CLOSED (${#CLOSED[@]}): ${CLOSED[*]:-none}"
echo ""

if [[ ${#CLOSED[@]} -gt 0 ]]; then
    echo "[ACTION] For each closed port on the receiver EC2, check:"
    echo "  firewall-cmd --list-all"
    echo "  iptables -L -n -v | grep <PORT>"
    echo "  Also verify AWS Security Group inbound rules."
fi

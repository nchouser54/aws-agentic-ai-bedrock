#!/usr/bin/env bash
# check_tcp_wrappers.sh - Check TCP Wrappers (hosts.allow / hosts.deny).
#
# TCP Wrappers is a legacy access control layer that operates INDEPENDENTLY
# of firewalld and iptables. On custom RHEL8 builds it is sometimes still
# active and can silently reject connections that pass the firewall.
#
# How it works:
#   1. /etc/hosts.allow is checked first  → if matched, connection is ALLOWED
#   2. /etc/hosts.deny  is checked second → if matched, connection is DENIED
#   3. If neither file matches            → connection is ALLOWED (default)
#
# A deny rule drops the connection silently — tcpdump sees the SYN arriving
# but nc on the receiver never gets it. The sender eventually times out.
#
# Run on the RHEL8 receiver EC2.
#
# Usage: ./check_tcp_wrappers.sh [SENDER_IP]
#   SENDER_IP  IP of the RHEL9 Podman host — used to check if it would be denied

set -uo pipefail

# ── Load shared config (network-test-scripts/test.env) ──────────────────────
_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/test.env"
# shellcheck source=/dev/null
[[ -f "${_CFG}" ]] && source "${_CFG}"

SENDER_IP="${1:-${RHEL9_IP:-}}"

echo "============================================="
echo " TCP WRAPPERS CHECK (hosts.allow / hosts.deny)"
echo "============================================="
echo " Host      : $(hostname)"
echo " Sender IP : ${SENDER_IP:-<not specified>}"
echo "============================================="
echo ""

# ── Is TCP Wrappers active? ───────────────────────────────────────────────────
echo "── Is TCP Wrappers in use? ─────────────────"

WRAPPED=false

for daemon in sshd nc ncat in.telnetd xinetd vsftpd; do
    if command -v "${daemon}" &>/dev/null; then
        if ldd "$(which ${daemon} 2>/dev/null)" 2>/dev/null | grep -q libwrap; then
            echo "  [WARN] ${daemon} is linked with libwrap — TCP Wrappers IS active for it."
            WRAPPED=true
        fi
    fi
done

if systemctl is-active --quiet xinetd 2>/dev/null; then
    echo "  [WARN] xinetd is running — services it manages use TCP Wrappers."
    WRAPPED=true
fi

if rpm -q tcp_wrappers 2>/dev/null | grep -qv 'not installed'; then
    echo "  [INFO] tcp_wrappers RPM is installed."
    WRAPPED=true
fi

if [[ "${WRAPPED}" == "false" ]]; then
    echo "  [OK ] No evidence TCP Wrappers is active for nc/ncat."
else
    echo ""
    echo "  [ACTION] TCP Wrappers is active — review hosts.allow/deny below."
fi

echo ""

# ── /etc/hosts.allow ─────────────────────────────────────────────────────────
echo "── /etc/hosts.allow ────────────────────────"
if [[ -f /etc/hosts.allow ]]; then
    cat -n /etc/hosts.allow | sed 's/^/  /'
else
    echo "  /etc/hosts.allow not found."
fi

echo ""

# ── /etc/hosts.deny ──────────────────────────────────────────────────────────
echo "── /etc/hosts.deny ─────────────────────────"
if [[ -f /etc/hosts.deny ]]; then
    cat -n /etc/hosts.deny | sed 's/^/  /'

    if grep -q 'ALL[[:space:]]*:[[:space:]]*ALL' /etc/hosts.deny; then
        echo ""
        echo "  [CRITICAL] hosts.deny contains 'ALL:ALL' — denies EVERYTHING"
        echo "  not explicitly allowed in hosts.allow."
        echo "  Fix: add to /etc/hosts.allow:"
        echo "    ALL: ${SENDER_IP:-<RHEL9_IP>}"
        echo "    OR: ALL: 10.0.0.0/8  (entire VPC CIDR)"
    fi
else
    echo "  /etc/hosts.deny not found."
fi

echo ""

# ── Sender IP check ───────────────────────────────────────────────────────────
if [[ -n "${SENDER_IP}" ]]; then
    echo "── Sender IP ${SENDER_IP} access check ───────"
    if command -v tcpdmatch &>/dev/null; then
        echo "  tcpdmatch result:"
        tcpdmatch ALL "${SENDER_IP}" 2>/dev/null | sed 's/^/  /'
    else
        echo "  tcpdmatch not available — manual check:"
        if [[ -f /etc/hosts.allow ]]; then
            grep -n -E "ALL|${SENDER_IP}" /etc/hosts.allow | grep -v '^#' | sed 's/^/    ALLOW match: /' || true
        fi
        if [[ -f /etc/hosts.deny ]]; then
            grep -n -E "ALL|${SENDER_IP}" /etc/hosts.deny | grep -v '^#' | sed 's/^/    DENY  match: /' || true
        fi
    fi
fi

echo ""
echo "── Fix: Allow RHEL9 traffic ────────────────"
echo "  Add to /etc/hosts.allow (takes effect immediately, no restart):"
echo ""
if [[ -n "${SENDER_IP}" ]]; then
    echo "    ALL: ${SENDER_IP}"
else
    echo "    ALL: <RHEL9_HOST_IP>"
fi
echo "    ALL: 10.0.0.0/255.0.0.0    # entire VPC private range"
echo "============================================="

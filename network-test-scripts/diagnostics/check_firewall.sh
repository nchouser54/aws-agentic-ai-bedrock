#!/usr/bin/env bash
# check_firewall.sh - Inspect firewalld, iptables, and nftables rules for a
# specific port. Shows exactly which rules would block or allow traffic.
# Run on EITHER host.
#
# Usage: ./check_firewall.sh [PORT] [PROTOCOL]
#   PORT      Port to check (default: 21240)
#   PROTOCOL  tcp or udp (default: tcp)

set -uo pipefail

# ── Load shared config (network-test-scripts/test.env) ──────────────────────
_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/test.env"
# shellcheck source=/dev/null
[[ -f "${_CFG}" ]] && source "${_CFG}"

PORT="${1:-${TEST_PORT:-21240}}"
PROTO="${2:-tcp}"

echo "============================================="
echo " FIREWALL RULE CHECK FOR PORT ${PORT}/${PROTO}"
echo "============================================="
echo " Host : $(hostname) / $(hostname -I | awk '{print $1}')"
echo " OS   : $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')"
echo "============================================="
echo ""

# ---------- firewalld ----------
echo "── firewalld ───────────────────────────────"
if systemctl is-active --quiet firewalld 2>/dev/null; then
    echo "  Status  : ACTIVE"
    echo "  Backend : $(firewall-cmd --info-service=firewalld 2>/dev/null | grep 'backend' || firewall-cmd --state)"

    DEFAULT_ZONE=$(firewall-cmd --get-default-zone 2>/dev/null)
    echo "  Default zone: ${DEFAULT_ZONE}"
    echo ""
    echo "  Active zones:"
    firewall-cmd --get-active-zones 2>/dev/null | sed 's/^/    /'

    echo ""
    echo "  Port ${PORT}/${PROTO} in zone '${DEFAULT_ZONE}':"
    if firewall-cmd --zone="${DEFAULT_ZONE}" --query-port="${PORT}/${PROTO}" 2>/dev/null; then
        echo "    [OK ] Port ${PORT}/${PROTO} is ALLOWED in firewalld"
    else
        echo "    [BLOCKED] Port ${PORT}/${PROTO} is NOT allowed in firewalld"
        echo "    Fix: firewall-cmd --zone=${DEFAULT_ZONE} --add-port=${PORT}/${PROTO} --permanent"
        echo "         firewall-cmd --reload"
    fi

    echo ""
    echo "  Masquerade in zone '${DEFAULT_ZONE}':"
    if firewall-cmd --zone="${DEFAULT_ZONE}" --query-masquerade 2>/dev/null; then
        echo "    [OK ] Masquerade is ENABLED (required for Podman -> external)"
    else
        echo "    [WARN] Masquerade is DISABLED"
        echo "    Fix (needed for Podman outbound): firewall-cmd --zone=${DEFAULT_ZONE} --add-masquerade --permanent && firewall-cmd --reload"
    fi

    echo ""
    echo "  Full zone listing for '${DEFAULT_ZONE}':"
    firewall-cmd --zone="${DEFAULT_ZONE}" --list-all 2>/dev/null | sed 's/^/    /'

    # Check all zones for the port
    echo ""
    echo "  Checking port ${PORT} across ALL zones:"
    for zone in $(firewall-cmd --get-zones 2>/dev/null); do
        if firewall-cmd --zone="${zone}" --query-port="${PORT}/${PROTO}" 2>/dev/null; then
            echo "    Zone '${zone}': ALLOWED"
        fi
    done

else
    echo "  Status: INACTIVE (firewalld not running)"
fi

echo ""

# ---------- iptables ----------
echo "── iptables ────────────────────────────────"
if command -v iptables &>/dev/null; then
    echo "  iptables version: $(iptables --version 2>/dev/null)"
    echo ""
    echo "  Rules matching port ${PORT} (INPUT chain):"
    iptables -L INPUT -n -v --line-numbers 2>/dev/null | \
        grep -E "port ${PORT}|dpt:${PORT}|spt:${PORT}|ACCEPT|DROP|REJECT|RETURN|policy" | \
        head -30 | sed 's/^/    /' || echo "    (no matching rules or iptables unavailable)"

    echo ""
    echo "  Rules matching port ${PORT} (FORWARD chain):"
    iptables -L FORWARD -n -v --line-numbers 2>/dev/null | \
        grep -E "port ${PORT}|dpt:${PORT}|ACCEPT|DROP|REJECT|RETURN|policy" | \
        head -30 | sed 's/^/    /' || echo "    (no matching rules)"

    echo ""
    echo "  NAT rules (PREROUTING — port forwarding/DNAT):"
    iptables -t nat -L PREROUTING -n -v --line-numbers 2>/dev/null | \
        grep -E "port ${PORT}|dpt:${PORT}|DNAT|MASQUERADE" | \
        head -20 | sed 's/^/    /' || echo "    (no DNAT rules)"

    echo ""
    echo "  NAT rules (POSTROUTING — masquerade):"
    iptables -t nat -L POSTROUTING -n -v --line-numbers 2>/dev/null | \
        grep -E "MASQUERADE|SNAT" | head -20 | sed 's/^/    /' || \
        echo "    (no masquerade/SNAT rules)"

    # Check Podman-specific chains
    echo ""
    echo "  Podman-specific iptables chains:"
    iptables -L -n 2>/dev/null | grep -E "Chain PODMAN|CNI" | sed 's/^/    /' || \
        echo "    (no Podman chains found)"
else
    echo "  iptables not available"
fi

echo ""

# ---------- nftables ----------
echo "── nftables ────────────────────────────────"
if command -v nft &>/dev/null; then
    echo "  nftables ruleset (rules mentioning port ${PORT}):"
    nft list ruleset 2>/dev/null | grep -E -A2 -B2 "${PORT}|podman|cni|FORWARD|INPUT" | \
        head -60 | sed 's/^/    /' || echo "    (no nftables rules or access denied)"
else
    echo "  nft not available"
fi

echo ""

# ---------- Summary ----------
echo "============================================="
echo " SUMMARY FOR PORT ${PORT}/${PROTO}"
echo "============================================="

BLOCKED=false

# firewalld check
if systemctl is-active --quiet firewalld 2>/dev/null; then
    DEFAULT_ZONE=$(firewall-cmd --get-default-zone 2>/dev/null)
    if ! firewall-cmd --zone="${DEFAULT_ZONE}" --query-port="${PORT}/${PROTO}" 2>/dev/null; then
        echo " [!] firewalld is BLOCKING port ${PORT} in zone '${DEFAULT_ZONE}'"
        BLOCKED=true
    fi
fi

if [[ "${BLOCKED}" == "false" ]]; then
    echo " [OK] No obvious firewall blocks detected for port ${PORT}"
    echo " If nc still fails, check:"
    echo "   1. AWS Security Group inbound rules"
    echo "   2. SELinux: run diagnostics/check_selinux.sh"
    echo "   3. nc binding to wrong interface: run diagnostics/check_iptables.sh"
fi
echo "============================================="

#!/usr/bin/env bash
# check_iptables.sh - Show full iptables/nftables ruleset with focus on
# Podman-created chains and any rules that could drop/reject traffic.
# Run on the RHEL9 host running Podman.
#
# Usage: ./check_iptables.sh [PORT]

set -uo pipefail

PORT="${1:-9000}"

echo "============================================="
echo " IPTABLES / NFTABLES DEEP INSPECTION"
echo "============================================="
echo " Host : $(hostname)"
echo " Port : ${PORT}"
echo "============================================="
echo ""

# ---------- iptables full dump ----------
echo "── iptables -L (filter table) ──────────────"
if command -v iptables &>/dev/null; then
    iptables -L -n -v --line-numbers 2>/dev/null | sed 's/^/  /' | head -100
else
    echo "  iptables not available"
fi

echo ""
echo "── iptables NAT table ──────────────────────"
iptables -t nat -L -n -v --line-numbers 2>/dev/null | sed 's/^/  /' | head -80 || echo "  (unavailable)"

echo ""
echo "── iptables MANGLE table ───────────────────"
iptables -t mangle -L -n -v --line-numbers 2>/dev/null | sed 's/^/  /' | head -40 || echo "  (unavailable)"

echo ""

# ---------- Podman-specific chains ----------
echo "── Podman / CNI iptables chains ────────────"
PODMAN_CHAINS=$(iptables -L -n 2>/dev/null | grep -E '^Chain (PODMAN|CNI|NETAVARK)' || true)
if [[ -n "${PODMAN_CHAINS}" ]]; then
    echo "  Found Podman chains:"
    echo "${PODMAN_CHAINS}" | sed 's/^/  /'
    echo ""
    # Dump each Podman chain
    while IFS= read -r line; do
        CHAIN=$(echo "${line}" | awk '{print $2}')
        echo "  --- Chain: ${CHAIN} ---"
        iptables -L "${CHAIN}" -n -v 2>/dev/null | sed 's/^/    /' || true
    done <<< "${PODMAN_CHAINS}"
else
    echo "  No Podman/CNI chains found in iptables."
    echo "  (RHEL9 with Podman 4+ uses Netavark + nftables instead)"
fi

echo ""

# ---------- nftables ----------
echo "── nftables full ruleset ───────────────────"
if command -v nft &>/dev/null; then
    nft list ruleset 2>/dev/null | sed 's/^/  /' || echo "  (nftables empty or access denied)"
    echo ""
    echo "── nftables: rules matching port ${PORT} ──"
    nft list ruleset 2>/dev/null | grep -E -B3 -A3 "${PORT}" | sed 's/^/  /' || \
        echo "  (no rules mentioning port ${PORT})"
else
    echo "  nft command not available."
fi

echo ""

# ---------- FORWARD policy ----------
echo "── FORWARD chain policy ────────────────────"
FWD_POLICY=$(iptables -L FORWARD -n 2>/dev/null | head -1)
echo "  ${FWD_POLICY}"
if echo "${FWD_POLICY}" | grep -q "DROP"; then
    echo "  [WARN] FORWARD policy is DROP — this can block container traffic."
    echo "  Fix:   iptables -P FORWARD ACCEPT"
    echo "         (Podman usually adds ACCEPT rules, but check above chains)"
elif echo "${FWD_POLICY}" | grep -q "ACCEPT"; then
    echo "  [OK ] FORWARD policy is ACCEPT."
fi

echo ""

# ---------- RHEL9 Netavark check ----------
echo "── Netavark (RHEL9 Podman 4+ network backend) ──"
if command -v netavark &>/dev/null; then
    echo "  netavark found: $(which netavark)"
    # Netavark uses nftables under the hood
    echo "  Check nftables ruleset above for Netavark rules."
else
    echo "  netavark not in PATH (may be bundled with Podman)"
fi

# Check for Netavark state files
NETAVARK_STATE_DIRS=(
    "/run/netavark"
    "${HOME}/.local/share/containers/storage/networks"
    "/var/lib/containers/storage/networks"
)
for dir in "${NETAVARK_STATE_DIRS[@]}"; do
    if [[ -d "${dir}" ]]; then
        echo "  Netavark state dir: ${dir}"
        ls -la "${dir}" 2>/dev/null | sed 's/^/    /'
    fi
done

echo ""

# ---------- RHEL9 specific: check nftables backend for firewalld ----------
echo "── firewalld nftables backend ───────────────"
if command -v firewall-cmd &>/dev/null && systemctl is-active --quiet firewalld 2>/dev/null; then
    FW_BACKEND=$(firewall-cmd --info-service=firewalld 2>/dev/null | grep -i backend || \
                 grep -r 'FirewallBackend' /etc/firewalld/ 2>/dev/null | head -1 || \
                 echo "iptables (default for RHEL8) or nftables (RHEL9)")
    echo "  ${FW_BACKEND}"
    echo ""
    echo "  [INFO] On RHEL9, firewalld uses nftables backend by default."
    echo "         Podman (Netavark) also uses nftables."
    echo "         Conflicts between the two can drop container traffic."
    echo "  Fix:   See fixes/fix_podman_firewall.sh for the correct approach."
fi

echo ""
echo "============================================="
echo " Done."
echo "============================================="

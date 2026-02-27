#!/usr/bin/env bash
# check_conntrack.sh - Inspect the kernel connection tracking (conntrack) table.
#
# Why this matters for the "tcpdump sees traffic but nc times out" problem:
#   If the conntrack table is FULL, the kernel silently drops new connection
#   attempts even though packets arrive at the NIC. tcpdump captures at the
#   NIC level BEFORE conntrack, so it sees the SYN — but the kernel drops it
#   immediately without sending a RST or logging it in firewalld.
#
#   A conntrack table full of stale Podman NAT entries is a common cause
#   of intermittent failures when containers are restarted frequently.
#
# Run on EITHER host (especially the receiver RHEL8 and the RHEL9 Podman host).
#
# Usage: ./check_conntrack.sh [PORT]
#   PORT  Specific port to search in conntrack table (default: 21240)

set -uo pipefail

PORT="${1:-21240}"

echo "============================================="
echo " CONNTRACK (Connection Tracking) CHECK"
echo "============================================="
echo " Host : $(hostname) / $(hostname -I | awk '{print $1}')"
echo " Port : ${PORT}"
echo " Time : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================="
echo ""

SUDO=""; [[ "${EUID}" -ne 0 ]] && SUDO="sudo"

# ── Table size vs current usage ───────────────────────────────────────────────
echo "── Conntrack Table Capacity ────────────────"
MAX=$(${SUDO} sysctl -n net.netfilter.nf_conntrack_max 2>/dev/null || cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null || echo "unknown")
CURRENT=$(${SUDO} sysctl -n net.netfilter.nf_conntrack_count 2>/dev/null || cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || echo "unknown")

echo "  nf_conntrack_max   (max entries) : ${MAX}"
echo "  nf_conntrack_count (current)     : ${CURRENT}"

if [[ "${MAX}" != "unknown" && "${CURRENT}" != "unknown" ]]; then
    PCT=$(awk "BEGIN{printf \"%.1f\", (${CURRENT}/${MAX})*100}")
    echo "  Usage                            : ${PCT}%"
    if awk "BEGIN{exit (${CURRENT}/${MAX} < 0.80)}"; then
        echo ""
        echo "  [WARN] Conntrack table is over 80% full!"
        echo "  When the table is full, new connections are SILENTLY DROPPED."
        echo "  tcpdump will see the SYN but nc will never receive it."
        echo "  Fix: run fixes/fix_conntrack.sh"
    elif awk "BEGIN{exit (${CURRENT}/${MAX} < 0.50)}"; then
        echo "  [NOTICE] Table is over 50% full — monitor this."
    else
        echo "  [OK ] Table usage is within normal range."
    fi
fi

echo ""

# ── Conntrack timeouts (stale entries) ────────────────────────────────────────
echo "── TCP Conntrack Timeouts ──────────────────"
echo "  (Long timeouts leave stale entries that consume table space)"
for key in \
    net.netfilter.nf_conntrack_tcp_timeout_established \
    net.netfilter.nf_conntrack_tcp_timeout_time_wait \
    net.netfilter.nf_conntrack_tcp_timeout_close_wait \
    net.netfilter.nf_conntrack_tcp_timeout_fin_wait \
    net.netfilter.nf_conntrack_tcp_timeout_syn_sent \
    net.netfilter.nf_conntrack_tcp_timeout_syn_recv; do
    VAL=$(${SUDO} sysctl -n "${key}" 2>/dev/null || echo "N/A")
    SHORT=$(echo "${key}" | sed 's/net.netfilter.nf_conntrack_tcp_//;s/timeout_//')
    printf "  %-30s : %s sec\n" "${SHORT}" "${VAL}"
done

echo ""

# ── Conntrack entries for our port ────────────────────────────────────────────
echo "── Conntrack Entries for Port ${PORT} ──────"
if command -v conntrack &>/dev/null || ${SUDO} conntrack --version &>/dev/null 2>&1; then
    ENTRIES=$(${SUDO} conntrack -L 2>/dev/null | grep -E ":${PORT}\b|dport=${PORT}\b" || true)
    if [[ -n "${ENTRIES}" ]]; then
        echo "  Found conntrack entries:"
        echo "${ENTRIES}" | head -30 | sed 's/^/  /'
        echo ""
        echo "  Entry states:"
        echo "${ENTRIES}" | awk '{for(i=1;i<=NF;i++){if($i~/^[A-Z]+$/){print $i}}}' | sort | uniq -c | sed 's/^/    /'
    else
        echo "  No conntrack entries for port ${PORT}."
        echo "  (Expected if no connections have been attempted yet)"
    fi
else
    echo "  conntrack tool not installed."
    echo "  Install: dnf install conntrack-tools  (RHEL) or apt install conntrack (Debian)"
    echo ""
    echo "  Fallback — reading /proc/net/nf_conntrack directly:"
    if [[ -f /proc/net/nf_conntrack ]]; then
        ${SUDO} grep -E "dport=${PORT}|sport=${PORT}" /proc/net/nf_conntrack 2>/dev/null | head -20 | sed 's/^/  /' || \
            echo "  (no entries or access denied)"
    fi
fi

echo ""

# ── INVALID state entries ─────────────────────────────────────────────────────
echo "── INVALID State Entries (these cause drops) ──"
if command -v conntrack &>/dev/null || ${SUDO} conntrack --version &>/dev/null 2>&1; then
    INVALID=$(${SUDO} conntrack -L 2>/dev/null | grep -c INVALID || echo 0)
    echo "  INVALID conntrack entries: ${INVALID}"
    if [[ "${INVALID}" -gt 0 ]]; then
        echo "  [WARN] INVALID entries cause iptables to drop packets."
        echo "  Common after container restarts that leave stale NAT state."
        echo "  Fix: ${SUDO} conntrack -D --state INVALID"
        ${SUDO} conntrack -L 2>/dev/null | grep INVALID | head -10 | sed 's/^/  /'
    else
        echo "  [OK ] No INVALID entries."
    fi
fi

echo ""

# ── Kernel messages about conntrack ──────────────────────────────────────────
echo "── Recent Kernel Conntrack Messages ────────"
${SUDO} dmesg --since "1 hour ago" 2>/dev/null | grep -iE 'nf_conntrack|conntrack|table full' | \
    tail -20 | sed 's/^/  /' || \
    ${SUDO} dmesg 2>/dev/null | grep -iE 'nf_conntrack|conntrack|table full' | \
    tail -20 | sed 's/^/  /' || \
    echo "  (no conntrack kernel messages or dmesg not accessible)"

echo ""

# ── Podman NAT entries ────────────────────────────────────────────────────────
echo "── Podman NAT Conntrack Entries ────────────"
if command -v conntrack &>/dev/null || ${SUDO} conntrack --version &>/dev/null 2>&1; then
    PODMAN_ENTRIES=$(${SUDO} conntrack -L 2>/dev/null | grep -E '10\.88\.' | wc -l || echo 0)
    echo "  Entries from Podman subnet (10.88.x.x): ${PODMAN_ENTRIES}"
    if [[ "${PODMAN_ENTRIES}" -gt 100 ]]; then
        echo "  [WARN] Large number of Podman NAT entries."
        echo "  Stale entries after container restart can block new connections."
        echo "  Fix: ${SUDO} conntrack -F  # flush all (brief connectivity gap)"
    fi
fi

echo ""
echo "============================================="
echo " SUMMARY"
echo "============================================="
if [[ "${MAX}" != "unknown" && "${CURRENT}" != "unknown" ]]; then
    if awk "BEGIN{exit (${CURRENT}/${MAX} < 0.80)}"; then
        echo " [ACTION REQUIRED] Conntrack table nearly full — run fixes/fix_conntrack.sh"
    else
        echo " [OK] Conntrack table usage is normal."
        echo " If you still see drops, the issue is likely firewalld or SELinux."
        echo " Check: diagnostics/check_firewall.sh ${PORT}"
        echo "        diagnostics/check_selinux.sh ${PORT}"
    fi
fi
echo "============================================="

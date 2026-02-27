#!/usr/bin/env bash
# fix_conntrack.sh - Fix connection tracking (conntrack) issues that silently
# drop connections even though tcpdump sees the packets arriving.
#
# Fixes:
#   - Conntrack table full → new SYNs silently dropped
#   - INVALID state entries from stale Podman NAT → mid-stream drops
#   - rp_filter strict mode → drops NAT/container traffic
#   - Undersized nf_conntrack_max
#
# Run on EITHER or BOTH hosts.
#
# Usage: ./fix_conntrack.sh [MODE] [MAX_ENTRIES]
#   MODE         'flush' | 'tune' | 'all' (default: all)
#   MAX_ENTRIES  Override the calculated conntrack max

set -uo pipefail

MODE="${1:-all}"
CUSTOM_MAX="${2:-}"

echo "============================================="
echo " CONNTRACK FIX"
echo "============================================="
echo " Host : $(hostname)"
echo " Mode : ${MODE}"
echo "============================================="
echo ""

SUDO=""; [[ "${EUID}" -ne 0 ]] && SUDO="sudo"
CHANGES=()

CURRENT_MAX=$(${SUDO} sysctl -n net.netfilter.nf_conntrack_max 2>/dev/null || echo "65536")
CURRENT_COUNT=$(${SUDO} sysctl -n net.netfilter.nf_conntrack_count 2>/dev/null || echo "0")
PCT=$(awk "BEGIN{printf \"%.1f\", (${CURRENT_COUNT}/${CURRENT_MAX})*100}" 2>/dev/null || echo "?")
echo "Current: max=${CURRENT_MAX}, count=${CURRENT_COUNT} (${PCT}% full)"
echo ""

# ── Flush ─────────────────────────────────────────────────────────────────────
if [[ "${MODE}" == "flush" || "${MODE}" == "all" ]]; then
    echo "── Flushing stale entries ──────────────────"
    if command -v conntrack &>/dev/null || ${SUDO} conntrack --version &>/dev/null 2>&1; then
        INVALID=$(${SUDO} conntrack -L 2>/dev/null | grep -c INVALID || echo 0)
        if [[ "${INVALID}" -gt 0 ]]; then
            ${SUDO} conntrack -D --state INVALID 2>/dev/null && \
                echo "  [OK ] Removed ${INVALID} INVALID entries." || true
            CHANGES+=("removed ${INVALID} INVALID conntrack entries")
        else
            echo "  [OK ] No INVALID entries."
        fi

        TW=$(${SUDO} conntrack -L 2>/dev/null | grep -c TIME_WAIT || echo 0)
        if [[ "${TW}" -gt 1000 ]]; then
            ${SUDO} conntrack -D --state TIME_WAIT 2>/dev/null && \
                echo "  [OK ] Flushed ${TW} TIME_WAIT entries." || true
            CHANGES+=("flushed ${TW} TIME_WAIT entries")
        fi

        NEW_PCT=$(awk "BEGIN{
            c=$(${SUDO} sysctl -n net.netfilter.nf_conntrack_count 2>/dev/null || echo 0)
            printf \"%.0f\", (c/${CURRENT_MAX})*100
        }" 2>/dev/null || echo 0)
        if [[ "${NEW_PCT}" -gt 90 ]]; then
            echo "  Table still ${NEW_PCT}% full. Performing FULL flush (brief gap)..."
            ${SUDO} conntrack -F 2>/dev/null && echo "  [OK ] Full flush done." || true
            CHANGES+=("full conntrack flush")
        fi
    else
        echo "  conntrack not installed. Run: dnf install conntrack-tools"
    fi
fi

echo ""

# ── Tune ──────────────────────────────────────────────────────────────────────
if [[ "${MODE}" == "tune" || "${MODE}" == "all" ]]; then
    echo "── Tuning limits ───────────────────────────"
    RAM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 2097152)
    RECOMMENDED=$(awk "BEGIN{printf \"%d\", (${RAM_KB} * 1024 * 0.10) / 350}")
    [[ "${RECOMMENDED}" -lt 65536 ]] && RECOMMENDED=65536
    [[ "${RECOMMENDED}" -gt 2097152 ]] && RECOMMENDED=2097152
    NEW_MAX="${CUSTOM_MAX:-${RECOMMENDED}}"

    echo "  RAM: $((RAM_KB/1024))MB | current max: ${CURRENT_MAX} | recommended: ${NEW_MAX}"

    if [[ "${NEW_MAX}" -gt "${CURRENT_MAX}" ]]; then
        ${SUDO} sysctl -w net.netfilter.nf_conntrack_max="${NEW_MAX}"
        CONF="/etc/sysctl.d/99-conntrack.conf"
        ${SUDO} tee "${CONF}" > /dev/null <<EOF
net.netfilter.nf_conntrack_max = ${NEW_MAX}
net.netfilter.nf_conntrack_tcp_timeout_established = 1800
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
EOF
        echo "  [OK ] Written to ${CONF}"
        CHANGES+=("nf_conntrack_max → ${NEW_MAX}")
    else
        echo "  [OK ] Current max is already sufficient."
    fi

    ${SUDO} sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=1800 2>/dev/null && \
        echo "  [OK ] established timeout → 1800s" || true
    ${SUDO} sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30 2>/dev/null && \
        echo "  [OK ] time_wait timeout   → 30s" || true
    CHANGES+=("reduced TCP conntrack timeouts")
fi

echo ""

# ── rp_filter ─────────────────────────────────────────────────────────────────
echo "── rp_filter ───────────────────────────────"
RP=$(cat /proc/sys/net/ipv4/conf/all/rp_filter 2>/dev/null || echo 0)
echo "  Current net.ipv4.conf.all.rp_filter: ${RP}"
if [[ "${RP}" == "1" ]]; then
    ${SUDO} sysctl -w net.ipv4.conf.all.rp_filter=2 2>/dev/null
    ${SUDO} sysctl -w net.ipv4.conf.default.rp_filter=2 2>/dev/null || true
    for iface in $(ls /proc/sys/net/ipv4/conf/ 2>/dev/null | grep -vE 'all|default|lo'); do
        ${SUDO} sysctl -w "net.ipv4.conf.${iface}.rp_filter=2" 2>/dev/null || true
    done
    CONF="/etc/sysctl.d/99-conntrack.conf"
    ${SUDO} grep -q rp_filter "${CONF}" 2>/dev/null || \
        echo -e "net.ipv4.conf.all.rp_filter = 2\nnet.ipv4.conf.default.rp_filter = 2" | ${SUDO} tee -a "${CONF}" > /dev/null
    echo "  [OK ] rp_filter changed strict(1) → loose(2)"
    CHANGES+=("rp_filter 1→2 (loose)")
else
    echo "  [OK ] rp_filter already 0 or loose."
fi

echo ""
echo "============================================="
echo " CHANGES"
echo "============================================="
[[ ${#CHANGES[@]} -eq 0 ]] && echo " None needed." || \
    for c in "${CHANGES[@]}"; do echo "  [+] ${c}"; done
echo ""
echo " Next: ec2-to-podman/client_test.sh <RHEL9_IP> 21240"
echo "============================================="

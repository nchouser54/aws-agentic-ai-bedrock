#!/usr/bin/env bash
# full_diagnostic.sh - Run all network diagnostics for EC2 <-> Podman issues.
# Run this on BOTH hosts and compare output.
#
# Usage: ./full_diagnostic.sh [TARGET_IP] [PORT] [CONTAINER_NAME]
#   TARGET_IP       Remote host IP for connectivity checks (optional)
#   PORT            Port to check specifically (optional, default: 21240)
#   CONTAINER_NAME  Podman container for Debian pod check (optional, default: dev-pod)
#
# Output is written to a timestamped log file for easy sharing.

set -uo pipefail

# ── Load shared config (network-test-scripts/test.env) ──────────────────────
_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/test.env"
# shellcheck source=/dev/null
[[ -f "${_CFG}" ]] && source "${_CFG}"

TARGET_IP="${1:-${RHEL8_IP:-}}"
PORT="${2:-${TEST_PORT:-21240}}"
CONTAINER_NAME="${3:-${CONTAINER_NAME:-dev-pod}}"
LOGFILE="/tmp/network_diag_$(hostname -s)_$(date +%Y%m%d_%H%M%S).log"

# Resolve sibling script directories relative to this file's location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

run_section() {
    local title="$1"
    local cmd="$2"
    echo ""
    echo "══════════════════════════════════════════════"
    echo " ${title}"
    echo "══════════════════════════════════════════════"
    eval "${cmd}" 2>&1 || true
}

{
echo "############################################"
echo " FULL NETWORK DIAGNOSTIC REPORT"
echo " Host    : $(hostname -f 2>/dev/null || hostname)"
echo " IPs     : $(hostname -I)"
echo " OS      : $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')"
echo " Kernel  : $(uname -r)"
echo " User    : $(id)"
echo " Target  : ${TARGET_IP:-<not specified>}"
echo " Port    : ${PORT}"
echo " Time    : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "############################################"

# ── System basics ──────────────────────────────
run_section "NETWORK INTERFACES" "ip addr show"
run_section "ROUTING TABLE" "ip route show"
run_section "IP FORWARDING" "sysctl net.ipv4.ip_forward net.ipv4.conf.all.forwarding 2>/dev/null || cat /proc/sys/net/ipv4/ip_forward"

# ── Listening ports ────────────────────────────
run_section "LISTENING SOCKETS (ss)" "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null"

# ── Firewalld ──────────────────────────────────
if systemctl is-active --quiet firewalld 2>/dev/null; then
    run_section "FIREWALLD STATUS" "firewall-cmd --state && firewall-cmd --list-all"
    run_section "FIREWALLD ALL ZONES" "firewall-cmd --list-all-zones 2>/dev/null"
    run_section "FIREWALLD MASQUERADE" "firewall-cmd --zone=public --query-masquerade 2>/dev/null && echo 'masquerade: ENABLED' || echo 'masquerade: DISABLED'"
else
    echo ""
    echo "══ FIREWALLD: not active on this host ══"
fi

# ── iptables ───────────────────────────────────
run_section "IPTABLES FILTER" "iptables -L -n -v --line-numbers 2>/dev/null || echo 'iptables not available'"
run_section "IPTABLES NAT" "iptables -t nat -L -n -v 2>/dev/null || echo 'iptables nat not available'"
run_section "NFTABLES" "nft list ruleset 2>/dev/null || echo 'nftables not available or no rules'"

# ── Port-specific check ────────────────────────
run_section "PORT ${PORT} FIREWALL RULES" "
iptables -L -n -v 2>/dev/null | grep -E ':${PORT}|dpt:${PORT}|ACCEPT|DROP|REJECT' | head -30 || true
nft list ruleset 2>/dev/null | grep -E '${PORT}' | head -30 || true
"

# ── SELinux ────────────────────────────────────
run_section "SELINUX STATUS" "sestatus 2>/dev/null || echo 'SELinux not installed'"
run_section "SELINUX RECENT DENIALS" "
if command -v ausearch &>/dev/null; then
    ausearch -m avc -ts recent 2>/dev/null | tail -40 || echo 'No recent AVC denials'
elif [ -f /var/log/audit/audit.log ]; then
    grep 'type=AVC' /var/log/audit/audit.log | tail -20
else
    echo 'audit log not accessible'
fi"
run_section "SELINUX PORT LABELS (${PORT})" "
semanage port -l 2>/dev/null | grep -E \"^Name|${PORT}\" | head -20 || echo 'semanage not available'"

# ── Podman (if present) ────────────────────────
if command -v podman &>/dev/null; then
    run_section "PODMAN VERSION & INFO" "podman version && echo '---' && podman info | grep -E 'network|rootless|cgroupManager|Backend|version'"
    run_section "PODMAN RUNNING CONTAINERS" "podman ps -a"
    run_section "PODMAN PORT MAPPINGS" "
for c in \$(podman ps --format '{{.Names}}' 2>/dev/null); do
    echo \"Container: \$c\"
    podman port \"\$c\" 2>/dev/null | sed 's/^/  /' || echo '  (no ports)'
done"
    run_section "PODMAN NETWORKS" "podman network ls && echo '---' && podman network inspect --all 2>/dev/null | python3 -m json.tool 2>/dev/null | head -80"
    run_section "PODMAN CONTAINER LOGS (last 30 lines each)" "
for c in \$(podman ps --format '{{.Names}}' 2>/dev/null); do
    echo \"=== \$c ===\"
    podman logs --tail 30 \"\$c\" 2>&1 || true
done"
    run_section "SLIRP4NETNS / PASTA PROCESSES" "
ps aux | grep -E 'slirp4netns|pasta|passt' | grep -v grep || echo 'Not running'"
else
    echo ""
    echo "══ PODMAN: not installed on this host ══"
fi

# ── Connectivity test to target ────────────────
if [[ -n "${TARGET_IP}" ]]; then
    run_section "PING TO TARGET ${TARGET_IP}" "ping -c 3 -W 2 ${TARGET_IP} 2>&1 || echo 'ping failed (ICMP may be blocked)'"
    run_section "NC CONNECT TO ${TARGET_IP}:${PORT}" "nc -zv -w 5 ${TARGET_IP} ${PORT} 2>&1 && echo 'PORT OPEN' || echo 'PORT CLOSED/FILTERED'"
    run_section "TRACEROUTE TO ${TARGET_IP}" "
if command -v traceroute &>/dev/null; then
    traceroute -m 10 ${TARGET_IP} 2>&1
elif command -v tracepath &>/dev/null; then
    tracepath ${TARGET_IP} 2>&1
else
    echo 'traceroute/tracepath not available'
fi"
fi

echo ""

# ── Specialized sub-script: conntrack ──────────────────────────────────────────
run_section "CONNTRACK (connection tracking)" \
    "\"${SCRIPT_DIR}/check_conntrack.sh\" \"${PORT}\" 2>/dev/null || true"

# ── Specialized sub-script: firewall detail ────────────────────────────────────
run_section "FIREWALL DETAIL (firewalld/iptables/nftables)" \
    "\"${SCRIPT_DIR}/check_firewall.sh\" \"${PORT}\" tcp 2>/dev/null || true"

# ── Specialized sub-script: SELinux detail ─────────────────────────────────────
run_section "SELINUX DETAIL" \
    "\"${SCRIPT_DIR}/check_selinux.sh\" \"${PORT}\" 2>/dev/null || true"

# ── Specialized sub-script: iptables/nftables deep dive ───────────────────────
run_section "IPTABLES / NFTABLES DEEP" \
    "\"${SCRIPT_DIR}/check_iptables.sh\" \"${PORT}\" 2>/dev/null || true"

# ── Specialized sub-script: TCP Wrappers (run on RHEL8 receiver) ───────────────
run_section "TCP WRAPPERS (hosts.allow / hosts.deny)" \
    "\"${SCRIPT_DIR}/check_tcp_wrappers.sh\" \"${TARGET_IP:-}\" 2>/dev/null || true"

# ── Specialized sub-script: custom RHEL8 hardening ────────────────────────────
run_section "CUSTOM RHEL8 HARDENING (fail2ban, ipset, rp_filter, EDR, eBPF, VPN)" \
    "\"${SCRIPT_DIR}/check_custom_rhel8.sh\" \"${TARGET_IP:-}\" \"${PORT}\" 2>/dev/null || true"

# ── Specialized sub-script: Podman config ─────────────────────────────────────
if command -v podman &>/dev/null; then
    run_section "PODMAN CONFIG (aardvark-dns, Docker conflict, CNI)" \
        "\"${REPO_ROOT}/ec2-to-podman/check_podman_config.sh\" 2>/dev/null || true"

    # Only attempt Debian pod check if the container is running
    if podman ps --format '{{.Names}}' 2>/dev/null | grep -q "${CONTAINER_NAME}"; then
        run_section "DEBIAN DEVELOPER POD (AppArmor, iptables variant, DNS)" \
            "\"${SCRIPT_DIR}/check_debian_pod.sh\" \"${CONTAINER_NAME}\" \"${PORT}\" \"${TARGET_IP:-}\" 2>/dev/null || true"
    else
        echo ""
        echo "══ DEBIAN POD CHECK: container '${CONTAINER_NAME}' not running — skipped ══"
        echo "   Re-run with container name as 3rd arg, or start the container first."
    fi
fi

echo ""
echo "############################################"
echo " END OF REPORT"
echo " Saved to: ${LOGFILE}"
echo "############################################"

} 2>&1 | tee "${LOGFILE}"

echo ""
echo "Full report saved to: ${LOGFILE}"
echo "Share this file with your team for remote debugging."

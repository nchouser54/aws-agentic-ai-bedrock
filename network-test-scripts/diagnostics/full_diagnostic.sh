#!/usr/bin/env bash
# full_diagnostic.sh - Run all network diagnostics for EC2 <-> Podman issues.
# Run this on BOTH hosts and compare output.
#
# Usage: ./full_diagnostic.sh [TARGET_IP] [PORT]
#   TARGET_IP  Remote host IP to include in connectivity checks (optional)
#   PORT       Port to check specifically (optional, default: 9000)
#
# Output is written to a timestamped log file for easy sharing.

set -uo pipefail

TARGET_IP="${1:-}"
PORT="${2:-9000}"
LOGFILE="/tmp/network_diag_$(hostname -s)_$(date +%Y%m%d_%H%M%S).log"

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
echo "############################################"
echo " END OF REPORT"
echo " Saved to: ${LOGFILE}"
echo "############################################"

} 2>&1 | tee "${LOGFILE}"

echo ""
echo "Full report saved to: ${LOGFILE}"
echo "Share this file with your team for remote debugging."

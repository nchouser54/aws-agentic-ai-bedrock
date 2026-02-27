#!/usr/bin/env bash
# check_custom_rhel8.sh - Checks specific to custom/hardened RHEL8 builds.
#
# Custom RHEL8 images (government, enterprise, STIG-hardened, etc.) often add
# security layers standard RHEL8 does not have. Checks:
#
#   1.  fail2ban       - bans IPs after repeated connection failures
#   2.  Custom iptables chains outside firewalld control
#   3.  ipset          - IP blocklists via iptables/nftables
#   4.  rp_filter      - reverse path filtering drops asymmetric/NAT packets
#   5.  NetworkManager firewall zone (can override firewalld defaults)
#   6.  Custom sysctl  - tcp_syncookies, somaxconn, ip_forward, etc.
#   7.  MTU mismatch   - Podman bridge vs host jumbo frames
#   8.  PAM access.conf - network access control
#   9.  ip_unprivileged_port_start - rootless Podman bind restriction
#   10. FIPS mode
#   11. Loaded netfilter / security kernel modules
#   12. auditd rules watching network syscalls
#   13. EDR / security agents (CrowdStrike, Carbon Black, Wazuh, etc.)
#
# Run on the RHEL8 receiver EC2.
#
# Usage: ./check_custom_rhel8.sh [SENDER_IP] [PORT]
#   SENDER_IP  IP of RHEL9/Podman host
#   PORT       Port under test (default: 21240)

set -uo pipefail

SENDER_IP="${1:-}"
PORT="${2:-21240}"

echo "============================================="
echo " CUSTOM RHEL8 HARDENING CHECKS"
echo "============================================="
echo " Host      : $(hostname)"
echo " OS        : $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')"
echo " Kernel    : $(uname -r)"
echo " Sender IP : ${SENDER_IP:-<not specified>}"
echo " Port      : ${PORT}"
echo " Time      : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================="
echo ""

SUDO=""; [[ "${EUID}" -ne 0 ]] && SUDO="sudo"
ISSUES=()

# ── 1. fail2ban ───────────────────────────────────────────────────────────────
echo "── [1] fail2ban ────────────────────────────"
if systemctl is-active --quiet fail2ban 2>/dev/null; then
    echo "  [WARN] fail2ban is RUNNING."
    echo "  After a few failed nc attempts it may have banned the RHEL9 host IP."
    echo ""
    ${SUDO} fail2ban-client status 2>/dev/null | sed 's/^/  /'
    echo ""
    if [[ -n "${SENDER_IP}" ]]; then
        echo "  Checking if ${SENDER_IP} is banned:"
        for jail in $(${SUDO} fail2ban-client status 2>/dev/null | grep 'Jail list:' | sed 's/.*Jail list://;s/,//g'); do
            if ${SUDO} fail2ban-client status "${jail}" 2>/dev/null | grep -q "${SENDER_IP}"; then
                echo "  [CRITICAL] ${SENDER_IP} is BANNED in jail '${jail}'!"
                echo "  Fix: ${SUDO} fail2ban-client set ${jail} unbanip ${SENDER_IP}"
                ISSUES+=("fail2ban has banned ${SENDER_IP} in jail ${jail}")
            else
                echo "  Jail '${jail}': ${SENDER_IP} not banned."
            fi
        done
    fi
    echo ""
    ${SUDO} tail -10 /var/log/fail2ban.log 2>/dev/null | sed 's/^/  /' || true
else
    echo "  [OK ] fail2ban is not running."
fi

echo ""

# ── 2. Custom iptables chains ─────────────────────────────────────────────────
echo "── [2] Custom iptables chains ──────────────"
CUSTOM=$(${SUDO} iptables -L -n 2>/dev/null | grep '^Chain ' | \
    grep -vE 'Chain (INPUT|OUTPUT|FORWARD|POSTROUTING|PREROUTING) ' || true)
if [[ -n "${CUSTOM}" ]]; then
    echo "  Custom chains (may contain DROP rules outside firewalld):"
    echo "${CUSTOM}" | sed 's/^/    /'
    DROP_RULES=$(${SUDO} iptables -L -n 2>/dev/null | grep -E "DROP|REJECT" | \
        grep -E ":${PORT}|dpt:${PORT}" || true)
    if [[ -n "${DROP_RULES}" ]]; then
        echo "  [CRITICAL] DROP/REJECT rules for port ${PORT}:"
        echo "${DROP_RULES}" | sed 's/^/    /'
        ISSUES+=("Custom iptables DROP rule for port ${PORT}")
    fi
else
    echo "  [OK ] No unexpected custom iptables chains."
fi

echo ""

# ── 3. ipset ──────────────────────────────────────────────────────────────────
echo "── [3] ipset blocklists ────────────────────"
if command -v ipset &>/dev/null; then
    SETS=$(${SUDO} ipset list -n 2>/dev/null || echo "")
    if [[ -n "${SETS}" ]]; then
        echo "  ipset sets: ${SETS}"
        if [[ -n "${SENDER_IP}" ]]; then
            for set in ${SETS}; do
                if ${SUDO} ipset test "${set}" "${SENDER_IP}" 2>/dev/null; then
                    echo "  [WARN] ${SENDER_IP} found in ipset '${set}'"
                    ISSUES+=("${SENDER_IP} in ipset ${set}")
                fi
            done
        fi
        IPSET_DROP=$(${SUDO} iptables -L -n 2>/dev/null | grep -i 'match-set' | \
            grep -E 'DROP|REJECT' || true)
        if [[ -n "${IPSET_DROP}" ]]; then
            echo "  [WARN] iptables uses ipsets to DROP traffic:"
            echo "${IPSET_DROP}" | sed 's/^/    /'
            ISSUES+=("ipset-based DROP rules in iptables")
        fi
    else
        echo "  [OK ] No ipset sets configured."
    fi
else
    echo "  ipset not installed."
fi

echo ""

# ── 4. rp_filter ─────────────────────────────────────────────────────────────
echo "── [4] rp_filter (reverse path filtering) ──"
echo "  rp_filter=1 drops packets where return route doesn't match source."
echo "  Podman NAT traffic may arrive with a source IP that fails this check."
RP_ALL=$(cat /proc/sys/net/ipv4/conf/all/rp_filter 2>/dev/null || echo 0)
for iface in $(ls /proc/sys/net/ipv4/conf/ 2>/dev/null); do
    VAL=$(cat "/proc/sys/net/ipv4/conf/${iface}/rp_filter" 2>/dev/null || echo "N/A")
    [[ "${VAL}" =~ ^[12]$ ]] && printf "  %-20s : %s%s\n" "${iface}" "${VAL}" \
        "$([[ "${VAL}" == "1" ]] && echo " (strict)" || echo " (loose)")"
done
if [[ "${RP_ALL}" == "1" ]]; then
    echo "  [WARN] rp_filter=1 strict — may drop Podman/NAT traffic."
    echo "  Fix: sysctl -w net.ipv4.conf.all.rp_filter=2"
    ISSUES+=("rp_filter=1 strict mode")
else
    echo "  [OK ] rp_filter is 0 or loose."
fi

echo ""

# ── 5. NetworkManager firewall zone ───────────────────────────────────────────
echo "── [5] NetworkManager firewall zone ────────"
if command -v nmcli &>/dev/null; then
    nmcli -f NAME,TYPE,DEVICE,CONNECTION.ZONE con show --active 2>/dev/null | sed 's/^/  /' || \
        nmcli con show --active 2>/dev/null | sed 's/^/  /'
    echo "  [INFO] If interface is in 'internal' or 'drop' zone, external traffic is blocked."
    echo "  Fix:   nmcli con mod <name> connection.zone public && nmcli con up <name>"
else
    echo "  nmcli not available."
fi

echo ""

# ── 6. sysctl hardening ───────────────────────────────────────────────────────
echo "── [6] Key sysctl values ───────────────────"
for key in \
    net.ipv4.ip_forward \
    net.ipv4.tcp_syncookies \
    net.ipv4.tcp_max_syn_backlog \
    net.core.somaxconn \
    net.ipv4.conf.all.rp_filter \
    net.ipv4.tcp_fin_timeout; do
    VAL=$(${SUDO} sysctl -n "${key}" 2>/dev/null || echo "N/A")
    printf "  %-45s : %s\n" "${key}" "${VAL}"
    if [[ "${key}" == "net.ipv4.ip_forward" && "${VAL}" == "0" ]]; then
        echo "    [CRITICAL] ip_forward=0 — container/Podman routing will fail"
        ISSUES+=("net.ipv4.ip_forward=0")
    fi
done

echo ""

# ── 7. MTU mismatch ──────────────────────────────────────────────────────────
echo "── [7] MTU check ───────────────────────────"
ip link show 2>/dev/null | awk '/^[0-9]+:/{iface=$2} /mtu/{for(i=1;i<=NF;i++) if($i=="mtu") printf "  %-20s mtu=%s\n", iface, $(i+1)}' | sed 's/:$//'
PODMAN_MTU=$(ip link show 2>/dev/null | grep -A2 'podman\|cni' | grep -oP 'mtu \K[0-9]+' | head -1 || true)
ETH_MTU=$(ip route show default 2>/dev/null | awk '{print $5}' | head -1 | xargs -I{} ip link show {} 2>/dev/null | grep -oP 'mtu \K[0-9]+' || echo "1500")
if [[ -n "${PODMAN_MTU}" && "${PODMAN_MTU}" != "${ETH_MTU}" ]]; then
    echo "  [WARN] MTU mismatch: host=${ETH_MTU}, Podman bridge=${PODMAN_MTU}"
    ISSUES+=("MTU mismatch host=${ETH_MTU} vs Podman=${PODMAN_MTU}")
fi

echo ""

# ── 8. PAM access.conf ────────────────────────────────────────────────────────
echo "── [8] PAM access control ──────────────────"
if [[ -f /etc/security/access.conf ]]; then
    ACTIVE=$(grep -v '^#' /etc/security/access.conf | grep -v '^[[:space:]]*$' || true)
    [[ -n "${ACTIVE}" ]] && echo "${ACTIVE}" | sed 's/^/  /' || echo "  [OK ] access.conf is empty."
else
    echo "  /etc/security/access.conf not found."
fi

echo ""

# ── 9. ip_unprivileged_port_start ────────────────────────────────────────────
echo "── [9] ip_unprivileged_port_start ──────────"
UNPRIV=$(cat /proc/sys/net/ipv4/ip_unprivileged_port_start 2>/dev/null || echo "N/A")
echo "  ip_unprivileged_port_start: ${UNPRIV}"
if [[ "${UNPRIV}" != "N/A" ]] && awk "BEGIN{exit (${PORT} >= ${UNPRIV})}"; then
    echo "  [WARN] Port ${PORT} < ip_unprivileged_port_start (${UNPRIV})"
    echo "         Rootless Podman containers cannot bind port ${PORT}."
    echo "  Fix:   sysctl -w net.ipv4.ip_unprivileged_port_start=1024"
    ISSUES+=("Port ${PORT} blocked for rootless Podman (ip_unprivileged_port_start=${UNPRIV})")
else
    echo "  [OK ] Port ${PORT} is in unprivileged range."
fi

echo ""

# ── 10. FIPS mode ────────────────────────────────────────────────────────────
echo "── [10] FIPS mode ──────────────────────────"
FIPS=$(cat /proc/sys/crypto/fips_enabled 2>/dev/null || echo "0")
echo "  FIPS enabled: ${FIPS}"
[[ "${FIPS}" == "1" ]] && echo "  [INFO] FIPS mode on. Custom security wrappers may enforce cipher requirements."

echo ""

# ── 11. Netfilter kernel modules ─────────────────────────────────────────────
echo "── [11] Loaded netfilter / security modules ──"
${SUDO} lsmod 2>/dev/null | grep -E '^(nf_|xt_|ipt_|ebt_|ip6t_)' | \
    awk '{printf "  %-35s used=%s\n", $1, $3}' | head -20 || echo "  (lsmod unavailable)"

echo ""

# ── 12. auditd network syscall rules ─────────────────────────────────────────
echo "── [12] auditd network syscall rules ───────"
if command -v auditctl &>/dev/null; then
    ${SUDO} auditctl -l 2>/dev/null | grep -E 'connect|bind|accept|socket' | \
        sed 's/^/  /' || echo "  No network syscall audit rules."
else
    echo "  auditctl not available."
fi

echo ""

# ── 13. EDR / security agents ────────────────────────────────────────────────
echo "── [13] Security agents / EDR ─────────────"
declare -A AGENTS=(
    ["falcon-sensor"]="CrowdStrike Falcon"
    ["cbdaemon"]="Carbon Black"
    ["ds_agent"]="Trend Micro"
    ["clamd"]="ClamAV"
    ["wazuh-agentd"]="Wazuh HIDS"
    ["ossec"]="OSSEC HIDS"
    ["fireeye"]="FireEye"
    ["cylancesvc"]="Cylance"
    ["sentineld"]="SentinelOne"
)
FOUND=false
for proc in "${!AGENTS[@]}"; do
    if pgrep -x "${proc}" &>/dev/null 2>&1 || systemctl is-active --quiet "${proc}" 2>/dev/null; then
        echo "  [INFO] ${AGENTS[$proc]} (${proc}) is running — may intercept connections."
        ISSUES+=("EDR agent: ${AGENTS[$proc]}")
        FOUND=true
    fi
done
[[ "${FOUND}" == "false" ]] && echo "  [OK ] No known EDR agents detected."

echo ""

# ── 14. tc (traffic control) queuing disciplines ──────────────────────────────
echo "── [14] Traffic control (tc) filters ───────"
echo "  [INFO] tc/qdisc filters can rate-limit or drop traffic outside iptables."
echo "         Enterprise/STIG builds sometimes add ingress policers."
TC_FILTERS=false
for iface in $(ip link show 2>/dev/null | awk -F': ' '/^[0-9]+:/{print $2}' | tr -d '@' | cut -d' ' -f1); do
    # Only inspect lines that start with "qdisc" to avoid matching statistics lines
    # (e.g. "Sent N bytes..." which would always fail the -v pattern check)
    TC_OUT=$(tc qdisc show dev "${iface}" 2>/dev/null | grep '^qdisc ' || true)
    if echo "${TC_OUT}" | grep -qvE '^qdisc (noqueue|mq|fq_codel|pfifo_fast|pfifo|ingress) '; then
        echo "  [WARN] Non-default qdisc on ${iface}:"
        echo "${TC_OUT}" | sed 's/^/    /'
        TC_INGRESS=$(tc filter show dev "${iface}" ingress 2>/dev/null || true)
        if [[ -n "${TC_INGRESS}" ]]; then
            echo "  [WARN] Ingress filter on ${iface} — may DROP packets before iptables:"
            echo "${TC_INGRESS}" | head -10 | sed 's/^/    /'
            ISSUES+=("tc ingress filter on ${iface}")
        fi
        TC_FILTERS=true
    fi
done
[[ "${TC_FILTERS}" == "false" ]] && echo "  [OK ] No unusual tc queuing disciplines found."

echo ""

# ── 15. eBPF programs attached to interfaces ──────────────────────────────────
echo "── [15] eBPF programs (XDP / TC BPF) ──────"
echo "  [INFO] XDP or TC BPF programs can drop packets before iptables even sees them."
if command -v bpftool &>/dev/null || ${SUDO} bpftool --version &>/dev/null 2>&1; then
    EBPF_PROGS=$(${SUDO} bpftool net list 2>/dev/null || true)
    if [[ -n "${EBPF_PROGS}" ]]; then
        echo "  eBPF programs attached to network interfaces:"
        echo "${EBPF_PROGS}" | grep -E 'xdp|tc' | sed 's/^/    /' || echo "    (none attached to xdp/tc)"
        XDP_PROGS=$(echo "${EBPF_PROGS}" | grep -c xdp || echo 0)
        if [[ "${XDP_PROGS}" -gt 0 ]]; then
            echo "  [WARN] XDP programs found — these can silently drop packets!"
            ISSUES+=("XDP eBPF program(s) attached to interface(s)")
        fi
    else
        echo "  [OK ] No eBPF programs attached to network interfaces."
    fi
elif ${SUDO} ip link show 2>/dev/null | grep -q 'xdp'; then
    echo "  [WARN] XDP program detected via ip link show:"
    ${SUDO} ip link show 2>/dev/null | grep -A1 'xdp' | sed 's/^/    /'
    ISSUES+=("XDP program visible in ip link show")
else
    echo "  bpftool not available. Manual check: ip link show | grep xdp"
fi

echo ""

# ── 16. VPN clients / routing table interference ──────────────────────────────
echo "── [16] VPN / overlay routing interference ─"
echo "  [INFO] VPN clients add routes that may redirect container traffic."
VPN_FOUND=false
declare -A VPN_DAEMONS=(
    ["openvpn"]="OpenVPN"
    ["wireguard"]="WireGuard"
    ["vpnagentd"]="Cisco AnyConnect"
    ["GlobalProtect"]="Palo Alto GlobalProtect"
    ["fortivpn"]="FortiVPN"
)
for proc in "${!VPN_DAEMONS[@]}"; do
    if pgrep -x "${proc}" &>/dev/null 2>&1 || systemctl is-active --quiet "${proc}" 2>/dev/null; then
        echo "  [WARN] ${VPN_DAEMONS[$proc]} (${proc}) is running."
        VPN_FOUND=true
        ISSUES+=("VPN client running: ${VPN_DAEMONS[$proc]}")
    fi
done
# Check for WireGuard interfaces
WG_IFACES=$(ip link show type wireguard 2>/dev/null | grep -c wg || echo 0)
if [[ "${WG_IFACES}" -gt 0 ]]; then
    echo "  [WARN] WireGuard interfaces active (wg*):"
    ip link show type wireguard 2>/dev/null | sed 's/^/    /'
    VPN_FOUND=true
    ISSUES+=("WireGuard interface active")
fi
# Check for OpenVPN tun interfaces
TUN_IFACES=$(ip link show 2>/dev/null | grep -E '^[0-9]+: tun[0-9]+' || true)
if [[ -n "${TUN_IFACES}" ]]; then
    echo "  [WARN] TUN interface(s) present — VPN may be routing your traffic:"
    echo "${TUN_IFACES}" | sed 's/^/    /'
    VPN_FOUND=true
    ISSUES+=("TUN interface active (likely VPN)")
fi
# Show default route and any policy routes
echo ""
echo "  Default route:"
ip route show default 2>/dev/null | sed 's/^/    /' || echo "    (none)"
echo ""
echo "  Policy routing rules (ip rule):"
ip rule list 2>/dev/null | grep -v 'from all lookup main' | grep -v 'from all lookup default' | \
    sed 's/^/    /' || echo "    (none)"
[[ "${VPN_FOUND}" == "false" ]] && echo "  [OK ] No VPN/overlay routing interference detected."

echo ""
echo "============================================="
echo " SUMMARY — ${#ISSUES[@]} issue(s) found"
echo "============================================="
if [[ ${#ISSUES[@]} -eq 0 ]]; then
    echo " [OK] No custom RHEL8 hardening issues found."
    echo " Next: diagnostics/check_tcp_wrappers.sh ${SENDER_IP:-<RHEL9_IP>}"
    echo "       diagnostics/check_conntrack.sh ${PORT}"
else
    for issue in "${ISSUES[@]}"; do echo "  [!] ${issue}"; done
fi
echo "============================================="

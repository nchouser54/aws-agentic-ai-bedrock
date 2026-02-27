#!/usr/bin/env bash
# check_debian_pod.sh - Inspect the Debian developer pod from inside via
# podman exec. Checks ufw, internal iptables, nc flavour, listening ports,
# and runs an outbound connectivity test from inside the container.
#
# Run on the RHEL9 EC2 that hosts the Podman container.
#
# Usage: ./check_debian_pod.sh [CONTAINER_NAME] [PORT] [TARGET_RHEL8_IP]
#   CONTAINER_NAME   Name or ID of the Debian container (default: dev-pod)
#   PORT             Port under test (default: 21240)
#   TARGET_RHEL8_IP  IP of the RHEL8 EC2 for outbound test

set -uo pipefail

# ── Load shared config (network-test-scripts/test.env) ──────────────────────
_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/test.env"
# shellcheck source=/dev/null
[[ -f "${_CFG}" ]] && source "${_CFG}"

CONTAINER="${1:-${CONTAINER_NAME:-dev-pod}}"
PORT="${2:-${TEST_PORT:-21240}}"
RHEL8_IP="${3:-${RHEL8_IP:-}}"

echo "============================================="
echo " DEBIAN DEVELOPER POD DIAGNOSTIC"
echo "============================================="
echo " Container    : ${CONTAINER}"
echo " Port         : ${PORT}"
echo " Target RHEL8 : ${RHEL8_IP:-<not specified>}"
echo " RHEL9 Host   : $(hostname)"
echo " Podman ver   : $(podman --version)"
echo "============================================="
echo ""

SUDO=""; [[ "${EUID}" -ne 0 ]] && SUDO="sudo"

# ── Is the container running? ─────────────────────────────────────────────────
echo "── Container Status ────────────────────────"
CONTAINER_ID=$(${SUDO} podman ps --filter "name=${CONTAINER}" --format "{{.ID}}" 2>/dev/null || \
               podman ps --filter "name=${CONTAINER}" --format "{{.ID}}" 2>/dev/null || true)

if [[ -z "${CONTAINER_ID}" ]]; then
    echo "  [ERROR] Container '${CONTAINER}' is not running."
    echo "  Running containers:"
    ${SUDO} podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | sed 's/^/    /'
    exit 1
fi
echo "  [OK ] Container '${CONTAINER}' running (ID: ${CONTAINER_ID:0:12})"

EXEC="${SUDO} podman exec ${CONTAINER}"

echo ""

# ── Network inside container ──────────────────────────────────────────────────
echo "── Container Network ───────────────────────"
${EXEC} ip addr show 2>/dev/null | sed 's/^/  /' || \
    ${EXEC} ifconfig 2>/dev/null | sed 's/^/  /' || \
    echo "  (ip/ifconfig not available)"

echo ""
echo "── Container Default Route ─────────────────"
${EXEC} ip route show 2>/dev/null | sed 's/^/  /' || \
    ${EXEC} route -n 2>/dev/null | sed 's/^/  /'
echo "  [INFO] Gateway should be the Podman bridge (e.g. 10.88.0.1)"

echo ""

# ── ufw ───────────────────────────────────────────────────────────────────────
echo "── ufw (Uncomplicated Firewall) ────────────"
if ${EXEC} which ufw &>/dev/null 2>&1; then
    UFW_STATUS=$(${EXEC} ufw status 2>/dev/null || echo "unknown")
    echo "  ${UFW_STATUS}"
    if echo "${UFW_STATUS}" | grep -qi "active"; then
        echo "  [WARN] ufw is ACTIVE inside the container."
        echo "  Fix:   podman exec ${CONTAINER} ufw allow out ${PORT}/tcp"
        echo "         OR: podman exec ${CONTAINER} ufw disable"
    else
        echo "  [OK ] ufw inactive."
    fi
else
    echo "  ufw not found in container."
fi

echo ""

# ── iptables inside container ─────────────────────────────────────────────────
echo "── iptables inside container ────────────────"
CT_IPTA=$(${EXEC} iptables -L -n 2>/dev/null || true)
if [[ -n "${CT_IPTA}" ]]; then
    echo "${CT_IPTA}" | head -40 | sed 's/^/  /'
    if echo "${CT_IPTA}" | grep -q "DROP\|REJECT"; then
        echo "  [WARN] DROP/REJECT rules inside the container!"
    fi
else
    echo "  iptables empty or unavailable (normal for rootless containers)."
fi

echo ""

# ── nc flavour inside container ───────────────────────────────────────────────
echo "── nc inside container ─────────────────────"
echo "  [INFO] Debian uses netcat-openbsd by default — flags differ from ncat."
echo "         openbsd nc: -l (listen), no -p flag, use -l PORT directly"
echo "         ncat:       -l -p PORT"
for cmd in nc ncat netcat socat; do
    if ${EXEC} which "${cmd}" &>/dev/null 2>&1; then
        echo "  Found: ${cmd} → $(${EXEC} which ${cmd} 2>/dev/null)"
        NC_VER=$(${EXEC} ${cmd} --version 2>&1 | head -1 || ${EXEC} ${cmd} -h 2>&1 | head -1 || true)
        echo "    ${NC_VER}"
    fi
done

echo ""

# ── Listening ports inside container ─────────────────────────────────────────
echo "── Listening ports inside container ─────────"
${EXEC} ss -tlnp 2>/dev/null | sed 's/^/  /' || \
    ${EXEC} netstat -tlnp 2>/dev/null | sed 's/^/  /' || \
    echo "  (ss/netstat not available)"
echo ""
echo "  Port ${PORT} specifically:"
${EXEC} ss -tlnp 2>/dev/null | grep ":${PORT}" | sed 's/^/    /' || \
    echo "    Not listening on ${PORT} inside container."

echo ""

# ── Outbound test from inside container ──────────────────────────────────────
echo "── Outbound connectivity from container ─────"
if [[ -n "${RHEL8_IP}" ]]; then
    echo "  Testing nc from container → RHEL8 (${RHEL8_IP}:${PORT})..."
    if ${EXEC} sh -c "nc -z -w 5 ${RHEL8_IP} ${PORT}" 2>/dev/null; then
        echo "  [OK ] Container can reach RHEL8:${PORT}"
    else
        echo "  [FAIL] Container cannot reach ${RHEL8_IP}:${PORT}"
        ${EXEC} ping -c 2 -W 2 "${RHEL8_IP}" 2>/dev/null | tail -3 | sed 's/^/    /' || \
            echo "    (ping unavailable)"
    fi
    echo ""
    echo "  Testing internet reachability (8.8.8.8:53):"
    ${EXEC} nc -z -w 3 8.8.8.8 53 2>/dev/null && \
        echo "  [OK ] Container can reach internet." || \
        echo "  [FAIL] Container cannot reach internet — possible network isolation."
else
    echo "  Specify TARGET_RHEL8_IP as 3rd argument to run outbound tests."
fi

echo ""

# ── Podman port bindings and network mode ─────────────────────────────────────
echo "── Podman port bindings ─────────────────────"
${SUDO} podman port "${CONTAINER}" 2>/dev/null | sed 's/^/  /' || \
    podman port "${CONTAINER}" 2>/dev/null | sed 's/^/  /' || \
    echo "  (no published ports)"

echo ""
${SUDO} podman inspect "${CONTAINER}" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)[0]
ns = d.get('NetworkSettings', {})
print(f\"  IP      : {ns.get('IPAddress', 'N/A')}\")
print(f\"  Gateway : {ns.get('Gateway', 'N/A')}\")
hc = d.get('HostConfig', {})
print(f\"  NetMode : {hc.get('NetworkMode', 'N/A')}\")
pb = hc.get('PortBindings', {})
for k, v in (pb or {}).items():
    for b in (v or []):
        print(f\"  Port    : {k} -> {b.get('HostIp','0.0.0.0')}:{b.get('HostPort','?')}\")
" 2>/dev/null | sed 's/^/  /' || true

echo ""

# ── Container logs ────────────────────────────────────────────────────────────
echo "── Recent container logs (last 20) ─────────"
${SUDO} podman logs --tail 20 "${CONTAINER}" 2>&1 | sed 's/^/  /' || \
    podman logs --tail 20 "${CONTAINER}" 2>&1 | sed 's/^/  /'

echo ""

# ── AppArmor inside container ─────────────────────────────────────────────────
echo "── AppArmor (Debian default MAC) ────────────"
if ${EXEC} which aa-status &>/dev/null 2>&1 || test -f /sys/kernel/security/apparmor/profiles 2>/dev/null; then
    AA_STATUS=$(${EXEC} sh -c 'aa-status 2>/dev/null || cat /sys/kernel/security/apparmor/profiles 2>/dev/null | head -20' || true)
    if [[ -n "${AA_STATUS}" ]]; then
        echo "  [WARN] AppArmor is present inside the container:"
        echo "${AA_STATUS}" | sed 's/^/  /'
        echo ""
        echo "  Check if nc/ncat has a restricting profile:"
        ${EXEC} sh -c 'aa-status 2>/dev/null | grep -iE "nc|ncat|netcat" || echo "  (none found)"' | sed 's/^/  /'
        echo ""
        echo "  Denials in container syslog (if available):"
        ${EXEC} sh -c 'grep "apparmor=\"DENIED\"" /var/log/syslog 2>/dev/null | tail -10 || dmesg 2>/dev/null | grep -i apparmor | tail -10 || echo "  (no apparmor denials visible)"' | sed 's/^/  /'
        echo ""
        echo "  Fix options:"
        echo "    podman exec ${CONTAINER} aa-complain /usr/bin/nc.openbsd"
        echo "    OR launch container with --security-opt apparmor=unconfined"
    else
        echo "  [OK ] AppArmor not active inside the container."
    fi
else
    echo "  AppArmor tools not found inside container (may still be enforced by host)."
    # Check if host AppArmor is confining the container
    CONTAINER_PROF=$(cat /sys/kernel/security/apparmor/profiles 2>/dev/null | grep -i 'container\|podman' | head -5 || true)
    if [[ -n "${CONTAINER_PROF}" ]]; then
        echo "  [WARN] Host AppArmor profiles for containers:"
        echo "${CONTAINER_PROF}" | sed 's/^/    /'
    fi
fi

echo ""

# ── iptables-legacy vs iptables-nft inside container ─────────────────────────
echo "── iptables variant inside container ────────"
echo "  [INFO] Debian/Ubuntu may have both iptables-legacy and iptables-nft."
echo "         Rules written with one are invisible to the other."
if ${EXEC} which update-alternatives &>/dev/null 2>&1; then
    ${EXEC} sh -c 'update-alternatives --query iptables 2>/dev/null | grep -E "Value:|Status:" || echo "  (update-alternatives not configured)"' | sed 's/^/  /'
fi
if ${EXEC} which iptables &>/dev/null 2>&1; then
    CT_IPTVER=$(${EXEC} iptables --version 2>/dev/null || true)
    echo "  Container iptables: ${CT_IPTVER}"
    if echo "${CT_IPTVER}" | grep -qi 'nf_tables\|nft'; then
        echo "  [INFO] Container uses iptables-nft. Check nftables too:"
        ${EXEC} nft list ruleset 2>/dev/null | grep -E 'DROP|REJECT' | sed 's/^/    /' || \
            echo "    (nft not available or no DROP/REJECT rules)"
    elif echo "${CT_IPTVER}" | grep -qi 'legacy'; then
        echo "  [INFO] Container uses iptables-legacy."
    fi
fi

echo ""

# ── DNS resolution from inside container ──────────────────────────────────────
echo "── DNS Resolution inside container ──────────"
echo "  Checking /etc/resolv.conf:"
${EXEC} cat /etc/resolv.conf 2>/dev/null | sed 's/^/  /' || echo "  (not readable)"
echo ""
echo "  DNS lookup test (google.com):"
if ${EXEC} which nslookup &>/dev/null 2>&1; then
    ${EXEC} sh -c 'nslookup google.com 2>&1 | tail -5' | sed 's/^/    /' || echo "    [FAIL] nslookup failed"
elif ${EXEC} which dig &>/dev/null 2>&1; then
    ${EXEC} sh -c 'dig +short google.com 2>&1 | head -3' | sed 's/^/    /' || echo "    [FAIL] dig failed"
elif ${EXEC} which getent &>/dev/null 2>&1; then
    ${EXEC} sh -c 'getent hosts google.com 2>&1' | sed 's/^/    /' || echo "    [FAIL] getent failed"
else
    ${EXEC} sh -c 'cat /etc/hosts | grep -v "^#" | head -10' 2>/dev/null | sed 's/^    /  /' || true
    echo "    (no DNS tools available — checking /etc/hosts only)"
fi
echo ""
if [[ -n "${RHEL8_IP}" ]]; then
    echo "  Reverse lookup of RHEL8 IP ${RHEL8_IP}:"
    ${EXEC} sh -c "nslookup ${RHEL8_IP} 2>&1 | tail -4 || host ${RHEL8_IP} 2>&1 | tail -2 || echo '  (reverse lookup failed — use IP directly)'" | sed 's/^/    /'
fi

echo ""
echo "============================================="
echo " If container cannot reach RHEL8:${PORT}:"
echo "  1. Check ufw/iptables above"
echo "  2. Check AppArmor — launch with: --security-opt apparmor=unconfined"
echo "  3. Check RHEL8 firewall: check_firewall.sh ${PORT}"
echo "  4. Check RHEL8 custom layers: check_custom_rhel8.sh ${RHEL8_IP:-<IP>} ${PORT}"
echo "  5. Re-launch with correct nc syntax for Debian:"
echo "     podman exec ${CONTAINER} nc -l ${PORT}   # openbsd nc"
echo "     podman exec ${CONTAINER} ncat -lvk -p ${PORT}   # ncat"
echo "============================================="

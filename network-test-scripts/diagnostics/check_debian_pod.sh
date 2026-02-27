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

CONTAINER="${1:-dev-pod}"
PORT="${2:-21240}"
RHEL8_IP="${3:-}"

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
echo "============================================="
echo " If container cannot reach RHEL8:${PORT}:"
echo "  1. Check ufw/iptables above"
echo "  2. Check RHEL8 firewall: check_firewall.sh ${PORT}"
echo "  3. Check RHEL8 custom layers: check_custom_rhel8.sh ${RHEL8_IP:-<IP>} ${PORT}"
echo "  4. Re-launch with correct nc syntax for Debian:"
echo "     podman exec ${CONTAINER} nc -l ${PORT}   # openbsd nc"
echo "     podman exec ${CONTAINER} ncat -lvk -p ${PORT}   # ncat"
echo "============================================="

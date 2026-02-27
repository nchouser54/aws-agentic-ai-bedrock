#!/usr/bin/env bash
# restart_podman_network.sh - Restart Podman networking cleanly to recover
# from a state where port mappings or firewall rules are broken/stale.
# Run on the RHEL9 EC2 (Podman host).
#
# This script:
#   1. Stops and removes the test container
#   2. Resets Podman's network state (if needed)
#   3. Restarts firewalld
#   4. Re-launches the container with correct port binding
#
# Usage: ./restart_podman_network.sh [CONTAINER_NAME] [HOST_PORT] [CONTAINER_PORT]

set -uo pipefail

# ── Load shared config (network-test-scripts/test.env) ──────────────────────
_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/test.env"
# shellcheck source=/dev/null
[[ -f "${_CFG}" ]] && source "${_CFG}"

CONTAINER="${1:-${CONTAINER_NAME:-nc-test-server}}"
HOST_PORT="${2:-${TEST_PORT:-21240}}"
CONTAINER_PORT="${3:-${CONTAINER_PORT:-21240}}"

echo "============================================="
echo " PODMAN NETWORK RESTART"
echo "============================================="
echo " Container     : ${CONTAINER}"
echo " Host port     : ${HOST_PORT}"
echo " Container port: ${CONTAINER_PORT}"
echo " Host          : $(hostname)"
echo "============================================="
echo ""

if [[ "${EUID}" -ne 0 ]]; then
    SUDO="sudo"
else
    SUDO=""
fi

# ── Step 1: Stop the container ────────────────────────────────────────────────
echo "[STEP 1] Stopping container '${CONTAINER}'..."
${SUDO} podman stop "${CONTAINER}" 2>/dev/null && echo "  [OK ] Stopped." || echo "  [INFO] Container was not running."
${SUDO} podman rm "${CONTAINER}" 2>/dev/null && echo "  [OK ] Removed." || echo "  [INFO] Container did not exist."

# Also clean up any stopped containers with the same port
echo "  Checking for other containers using port ${HOST_PORT}..."
CONFLICTING=$(${SUDO} podman ps -a --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep ":${HOST_PORT}" | awk '{print $1}' || true)
if [[ -n "${CONFLICTING}" ]]; then
    for c in ${CONFLICTING}; do
        echo "  Removing conflicting container: ${c}"
        ${SUDO} podman rm -f "${c}" 2>/dev/null || true
    done
fi

echo ""

# ── Step 2: Verify no stale process holds the port ────────────────────────────
echo "[STEP 2] Check for stale processes on port ${HOST_PORT}..."
STALE=$(${SUDO} ss -tlnp 2>/dev/null | grep ":${HOST_PORT}" || true)
if [[ -n "${STALE}" ]]; then
    echo "  [WARN] Something is still listening on port ${HOST_PORT}:"
    echo "${STALE}" | sed 's/^/    /'
    PID=$(${SUDO} ss -tlnp 2>/dev/null | grep ":${HOST_PORT}" | grep -oP 'pid=\K[0-9]+' | head -1 || true)
    if [[ -n "${PID}" ]]; then
        echo "  PID holding the port: ${PID} ($(${SUDO} ps -p "${PID}" -o comm= 2>/dev/null || echo 'unknown'))"
        echo "  Kill with: kill ${PID}"
    fi
else
    echo "  [OK ] Port ${HOST_PORT} is free."
fi

echo ""

# ── Step 3: Reload firewalld ──────────────────────────────────────────────────
echo "[STEP 3] Reloading firewalld..."
if systemctl is-active --quiet firewalld 2>/dev/null; then
    ${SUDO} firewall-cmd --reload && echo "  [OK ] firewalld reloaded." || echo "  [WARN] firewall-cmd reload failed."
else
    echo "  [INFO] firewalld not active."
fi

echo ""

# ── Step 4: Verify IP forwarding ──────────────────────────────────────────────
echo "[STEP 4] Verify IP forwarding..."
FWD=$(cat /proc/sys/net/ipv4/ip_forward)
if [[ "${FWD}" != "1" ]]; then
    echo "  [WARN] IP forwarding was off. Enabling..."
    ${SUDO} sysctl -w net.ipv4.ip_forward=1
    echo "  [OK ] Enabled."
else
    echo "  [OK ] IP forwarding is already on."
fi

echo ""

# ── Step 5: Prune Podman network state ────────────────────────────────────────
echo "[STEP 5] Pruning stale Podman network resources..."
${SUDO} podman network prune -f 2>/dev/null && echo "  [OK ] Network prune done." || echo "  [INFO] Network prune skipped."

echo ""

# ── Step 6: Re-run the container server ───────────────────────────────────────
echo "[STEP 6] Re-launching test container..."
echo "  Delegating to ec2-to-podman/podman_server_setup.sh ..."
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/../ec2-to-podman/podman_server_setup.sh" ]]; then
    bash "${SCRIPT_DIR}/../ec2-to-podman/podman_server_setup.sh" "${HOST_PORT}" "${CONTAINER_PORT}"
else
    echo "  [WARN] podman_server_setup.sh not found. Launch the container manually:"
    echo "    podman run -d --name ${CONTAINER} \\"
    echo "      -p 0.0.0.0:${HOST_PORT}:${CONTAINER_PORT}/tcp \\"
    echo "      registry.access.redhat.com/ubi9/ubi-minimal \\"
    echo "      sh -c 'ncat -lvk -p ${CONTAINER_PORT}'"
fi

echo ""
echo "============================================="
echo " RESTART COMPLETE"
echo " Test from RHEL8: ec2-to-podman/client_test.sh <RHEL9_IP> ${HOST_PORT}"
echo "============================================="

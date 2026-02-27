#!/usr/bin/env bash
# podman_server_setup.sh - Launch a lightweight test container on the RHEL9 EC2
# that runs an nc listener so external hosts can connect to it.
#
# Run this on the RHEL9 EC2 that hosts the Podman container.
#
# Usage: ./podman_server_setup.sh [HOST_PORT] [CONTAINER_PORT] [IMAGE]
#   HOST_PORT       Port exposed on the RHEL9 EC2 host (default: 21240)
#   CONTAINER_PORT  Port nc listens on inside the container (default: 21240)
#   IMAGE           Container image to use (default: registry.access.redhat.com/ubi9/ubi-minimal)
#
# Example:
#   ./podman_server_setup.sh 21240 21240
#   ./podman_server_setup.sh 8080 8080 debian:12

set -euo pipefail

HOST_PORT="${1:-21240}"
CONTAINER_PORT="${2:-21240}"
IMAGE="${3:-registry.access.redhat.com/ubi9/ubi-minimal}"
CONTAINER_NAME="nc-test-server"

echo "============================================="
echo " PODMAN NC SERVER SETUP"
echo "============================================="
echo " Image          : ${IMAGE}"
echo " Host port      : ${HOST_PORT}"
echo " Container port : ${CONTAINER_PORT}"
echo " Container name : ${CONTAINER_NAME}"
echo " Host           : $(hostname) ($(hostname -I | awk '{print $1}'))"
echo " Podman version : $(podman --version)"
echo "============================================="
echo ""

# ---------- Cleanup any existing container ----------
echo "[STEP 1] Removing any existing '${CONTAINER_NAME}' container..."
podman rm -f "${CONTAINER_NAME}" 2>/dev/null && echo "  [OK ] Removed old container." || echo "  [INFO] No old container to remove."

# ---------- Determine nc binary in image ----------
# ubi-minimal uses microdnf; debian images have netcat-openbsd
echo ""
echo "[STEP 2] Pulling image '${IMAGE}'..."
podman pull "${IMAGE}"

# ---------- Detect nc availability in image ----------
NC_CMD=""
for candidate in "nc" "ncat" "netcat"; do
    if podman run --rm "${IMAGE}" which "${candidate}" &>/dev/null 2>&1; then
        NC_CMD="${candidate}"
        break
    fi
done

if [[ -z "${NC_CMD}" ]]; then
    echo ""
    echo "[WARN] No nc/ncat found in ${IMAGE}."
    echo "       Attempting to install nmap-ncat via microdnf (UBI images)..."
    # Create a derived image with ncat installed
    DOCKERFILE=$(mktemp --suffix=.Containerfile)
    cat > "${DOCKERFILE}" <<CONTAINERFILE
FROM ${IMAGE}
RUN microdnf install -y nmap-ncat 2>/dev/null || \
    apt-get update -y && apt-get install -y netcat-openbsd 2>/dev/null || \
    yum install -y nmap-ncat 2>/dev/null
CONTAINERFILE
    podman build -t nc-test-image -f "${DOCKERFILE}" .
    rm -f "${DOCKERFILE}"
    IMAGE="nc-test-image"
    NC_CMD="ncat"
fi

echo "  [OK ] Using nc command: ${NC_CMD}"

# ---------- Launch container ----------
echo ""
echo "[STEP 3] Launching container..."
echo "  Binding 0.0.0.0:${HOST_PORT} -> container:${CONTAINER_PORT}"
echo ""

# CRITICAL: bind to 0.0.0.0 on the host, not 127.0.0.1
# Use --network=host mode as fallback flag shown in comments
podman run -d \
    --name "${CONTAINER_NAME}" \
    -p "0.0.0.0:${HOST_PORT}:${CONTAINER_PORT}/tcp" \
    "${IMAGE}" \
    sh -c "${NC_CMD} -lvk -p ${CONTAINER_PORT} -e /bin/sh 2>&1 | while IFS= read -r line; do echo \"[CONTAINER] \$line\"; done"

echo ""
echo "[STEP 4] Verifying container is running..."
sleep 2
if podman ps --filter "name=${CONTAINER_NAME}" --format "{{.Names}}" | grep -q "${CONTAINER_NAME}"; then
    echo "  [OK ] Container '${CONTAINER_NAME}' is running."
else
    echo "  [ERROR] Container failed to start. Logs:"
    podman logs "${CONTAINER_NAME}" 2>&1 || true
    exit 1
fi

echo ""
echo "[STEP 5] Port mapping verification..."
podman port "${CONTAINER_NAME}"

echo ""
echo "[STEP 6] Host-level listen verification..."
if ss -tlnp 2>/dev/null | grep -q ":${HOST_PORT}"; then
    echo "  [OK ] Port ${HOST_PORT} is listening on the host."
    ss -tlnp | grep ":${HOST_PORT}"
else
    echo "  [WARN] Port ${HOST_PORT} not visible in ss output."
    echo "         This can happen with rootless Podman using slirp4netns."
    echo "         Check with: sudo ss -tlnp | grep ${HOST_PORT}"
fi

echo ""
echo "============================================="
echo " CONTAINER IS READY"
echo "============================================="
echo " From the RHEL8 EC2, run:"
echo "   ./ec2-to-podman/client_test.sh $(hostname -I | awk '{print $1}') ${HOST_PORT}"
echo ""
echo " To view container logs:"
echo "   podman logs -f ${CONTAINER_NAME}"
echo ""
echo " To stop the container:"
echo "   podman rm -f ${CONTAINER_NAME}"
echo "============================================="

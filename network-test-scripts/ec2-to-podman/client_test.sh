#!/usr/bin/env bash
# client_test.sh - Test connectivity from a plain EC2 (RHEL8) to a Podman
# container running on another EC2 (RHEL9).
#
# Run this on the RHEL8 EC2.
#
# Usage: ./client_test.sh <RHEL9_HOST_IP> [PORT] [TIMEOUT_SECS]
#   RHEL9_HOST_IP  Public or private IP of the RHEL9 EC2
#   PORT           Port published from the Podman container (default: 9000)
#   TIMEOUT        Connection timeout (default: 5)
#
# Example:
#   ./client_test.sh 10.0.2.100 9000

set -euo pipefail

HOST="${1:-}"
PORT="${2:-9000}"
TIMEOUT="${3:-5}"
ATTEMPTS=3

if [[ -z "${HOST}" ]]; then
    echo "Usage: $0 <RHEL9_HOST_IP> [PORT] [TIMEOUT_SECS]"
    exit 1
fi

echo "============================================="
echo " EC2 -> PODMAN CONTAINER CONNECTIVITY TEST"
echo "============================================="
echo " Target container host : ${HOST}"
echo " Published port        : ${PORT}"
echo " Timeout per attempt   : ${TIMEOUT}s"
echo " Attempts              : ${ATTEMPTS}"
echo " Source host           : $(hostname) ($(hostname -I | awk '{print $1}'))"
echo " Time                  : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================="
echo ""

PASS=0
FAIL=0

for i in $(seq 1 "${ATTEMPTS}"); do
    printf "[Attempt %d/%d] Connecting to %s:%s ... " "${i}" "${ATTEMPTS}" "${HOST}" "${PORT}"
    if nc -z -w "${TIMEOUT}" "${HOST}" "${PORT}" 2>/dev/null; then
        echo "SUCCESS"
        PASS=$((PASS + 1))
    else
        echo "FAILED"
        FAIL=$((FAIL + 1))
    fi
    sleep 1
done

echo ""
echo "============================================="
echo " RESULT: ${PASS}/${ATTEMPTS} attempts succeeded"
echo "============================================="
echo ""

if [[ "${PASS}" -eq 0 ]]; then
    echo "[DIAGNOSIS] All attempts failed. Likely causes and fixes:"
    echo ""
    echo "  ON THE RHEL9 HOST (Podman side):"
    echo "  ─────────────────────────────────────────"
    echo "  1. Port not published to 0.0.0.0"
    echo "     Check:  podman port <container_name>"
    echo "     Fix:    Re-run container with: -p 0.0.0.0:${PORT}:${PORT}"
    echo ""
    echo "  2. firewalld blocking the port on the RHEL9 host"
    echo "     Check:  firewall-cmd --list-all"
    echo "     Fix:    firewall-cmd --zone=public --add-port=${PORT}/tcp --permanent && firewall-cmd --reload"
    echo ""
    echo "  3. Masquerade not enabled (required for Podman -> external)"
    echo "     Check:  firewall-cmd --zone=public --query-masquerade"
    echo "     Fix:    firewall-cmd --zone=public --add-masquerade --permanent && firewall-cmd --reload"
    echo ""
    echo "  4. Rootless Podman using slirp4netns (no kernel-level bind)"
    echo "     Check:  podman info | grep -i network"
    echo "     Fix:    Run container as root OR use --network=host"
    echo "             sudo podman run --network=host ..."
    echo ""
    echo "  5. SELinux blocking the port"
    echo "     Check:  ausearch -m avc -ts recent | grep ${PORT}"
    echo "             grep 'denied' /var/log/audit/audit.log | grep ${PORT}"
    echo "     Fix:    semanage port -a -t http_port_t -p tcp ${PORT}"
    echo "             OR: setsebool -P container_manage_cgroup on"
    echo ""
    echo "  ON THE RHEL8 HOST (receiver side — if roles are reversed):"
    echo "  ─────────────────────────────────────────"
    echo "  6. AWS Security Group does not allow inbound port ${PORT}"
    echo "     Fix:    Add inbound rule in EC2 console for port ${PORT}"
    echo ""
    echo "  Run: diagnostics/full_diagnostic.sh on both hosts"
    echo "  Run: diagnostics/tcpdump_capture.sh ${PORT} on the RHEL9 host"
    echo "       to see if packets are leaving the host."
    exit 1
elif [[ "${PASS}" -lt "${ATTEMPTS}" ]]; then
    echo "[WARN] Intermittent connectivity. Possible packet loss or connection"
    echo "       instability. Check firewall rules and Podman network stability."
else
    echo "[OK] All attempts succeeded!"
    echo ""
    echo "[STEP] Sending test message..."
    PAYLOAD="HELLO_FROM_$(hostname)_AT_$(date -u '+%H:%M:%SZ')"
    echo "${PAYLOAD}" | nc -w "${TIMEOUT}" "${HOST}" "${PORT}" 2>&1 && \
        echo "  [OK ] Sent: ${PAYLOAD}" || \
        echo "  [WARN] Message send failed (nc server may need -e option)"
fi

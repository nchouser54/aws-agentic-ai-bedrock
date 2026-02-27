#!/usr/bin/env bash
# run.sh - Convenience wrapper for network-test-scripts.
#
# Sources test.env automatically and provides short subcommands for the
# most common workflows.  All values come from test.env; you can override
# any one with an environment variable inline:
#
#   RHEL9_IP=1.2.3.4 ./run.sh test
#
# Usage: ./run.sh <command> [args...]
#
# Commands (RHEL9 = Podman host, RHEL8 = receiver / client EC2):
#
#   server           Start the nc listener container on RHEL9 (Podman side)
#   test             Run client connectivity test  → RHEL9:TEST_PORT
#   alt              Run all-tools connectivity test → RHEL9:TEST_PORT
#   multi            Scan common ports against RHEL9
#   diag [rhel9|rhel8]  Run full diagnostics (pass 'rhel9' to set TARGET=RHEL8_IP)
#   tcpdump          Start packet capture on TEST_PORT (this host)
#   fw               Check firewall rules for TEST_PORT (this host)
#   iptables         Show iptables/nftables chains for TEST_PORT (this host)
#   selinux          Check / fix SELinux for TEST_PORT
#   selinux-fix      Apply SELinux fixes (diagnose mode — safe to run)
#   apparmor         Apply AppArmor fixes for CONTAINER_NAME (diagnose mode)
#   conntrack        Inspect conntrack table for TEST_PORT
#   pod              Inspect the Debian dev-pod container
#   tcp-wrappers     Check hosts.allow / hosts.deny (run on RHEL8)
#   restart          Clean restart the test container + Podman networking
#   fix-fw           Fix firewalld / masquerade rules (diagnose mode)
#   config           Print the active configuration
#   help             Show this help message

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Source config ────────────────────────────────────────────────────────────
CFG="${SCRIPT_DIR}/test.env"
if [[ -f "${CFG}" ]]; then
    # shellcheck source=/dev/null
    source "${CFG}"
else
    echo "[WARN] test.env not found. Using built-in defaults."
    echo "       Copy ${SCRIPT_DIR}/test.env.example → ${SCRIPT_DIR}/test.env"
    echo "       and fill in your IPs."
    echo ""
fi

# Apply defaults for any variable not set by the config
RHEL8_IP="${RHEL8_IP:-10.0.0.10}"
RHEL9_IP="${RHEL9_IP:-10.0.0.20}"
TEST_PORT="${TEST_PORT:-21240}"
CONTAINER_NAME="${CONTAINER_NAME:-nc-test-server}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-registry.access.redhat.com/ubi9/ubi-minimal}"
CONTAINER_PORT="${CONTAINER_PORT:-${TEST_PORT}}"
TIMEOUT_SECS="${TIMEOUT_SECS:-5}"
CAPTURE_DURATION="${CAPTURE_DURATION:-30}"

CMD="${1:-help}"

# ── Helpers ──────────────────────────────────────────────────────────────────
require_rhel9() {
    if [[ -z "${RHEL9_IP}" || "${RHEL9_IP}" == "10.0.0.20" ]]; then
        echo "[WARN] RHEL9_IP is still the placeholder value (${RHEL9_IP})."
        echo "       Set it in test.env before running this command."
    fi
}

require_rhel8() {
    if [[ -z "${RHEL8_IP}" || "${RHEL8_IP}" == "10.0.0.10" ]]; then
        echo "[WARN] RHEL8_IP is still the placeholder value (${RHEL8_IP})."
        echo "       Set it in test.env before running this command."
    fi
}

run() {
    echo "[RUN] $*"
    echo ""
    "$@"
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "${CMD}" in

    # ── RHEL9 side ───────────────────────────────────────────────────────────
    server)
        echo "Starting nc listener container on this host → ${RHEL8_IP}:${TEST_PORT}"
        run bash "${SCRIPT_DIR}/ec2-to-podman/podman_server_setup.sh" \
            "${TEST_PORT}" "${CONTAINER_PORT}" "${CONTAINER_IMAGE}"
        ;;

    # ── RHEL8 side ───────────────────────────────────────────────────────────
    test)
        require_rhel9
        run bash "${SCRIPT_DIR}/ec2-to-podman/client_test.sh" \
            "${RHEL9_IP}" "${TEST_PORT}" "${TIMEOUT_SECS}"
        ;;

    alt)
        require_rhel9
        run bash "${SCRIPT_DIR}/ec2-to-ec2/alt_connect_test.sh" \
            "${RHEL9_IP}" "${TEST_PORT}" "${TIMEOUT_SECS}"
        ;;

    multi)
        require_rhel9
        run bash "${SCRIPT_DIR}/ec2-to-ec2/multi_port_test.sh" \
            "${RHEL9_IP}" "${TEST_PORT},80,443,8080,8443" "${TIMEOUT_SECS}"
        ;;

    # ── Diagnostics ──────────────────────────────────────────────────────────
    diag)
        SIDE="${2:-}"
        if [[ "${SIDE}" == "rhel9" ]]; then
            echo "Running diagnostics targeting RHEL8 (${RHEL8_IP}) from RHEL9..."
            run bash "${SCRIPT_DIR}/diagnostics/full_diagnostic.sh" \
                "${RHEL8_IP}" "${TEST_PORT}" "${CONTAINER_NAME}"
        else
            echo "Running diagnostics targeting RHEL9 (${RHEL9_IP}) from RHEL8..."
            run bash "${SCRIPT_DIR}/diagnostics/full_diagnostic.sh" \
                "${RHEL9_IP}" "${TEST_PORT}" "${CONTAINER_NAME}"
        fi
        ;;

    tcpdump)
        echo "Starting ${CAPTURE_DURATION}s tcpdump on port ${TEST_PORT}..."
        run bash "${SCRIPT_DIR}/diagnostics/tcpdump_capture.sh" \
            "${TEST_PORT}" "" "${CAPTURE_DURATION}"
        ;;

    fw)
        run bash "${SCRIPT_DIR}/diagnostics/check_firewall.sh" "${TEST_PORT}"
        ;;

    iptables)
        run bash "${SCRIPT_DIR}/diagnostics/check_iptables.sh" "${TEST_PORT}"
        ;;

    conntrack)
        run bash "${SCRIPT_DIR}/diagnostics/check_conntrack.sh" "${TEST_PORT}"
        ;;

    pod)
        require_rhel8
        run bash "${SCRIPT_DIR}/diagnostics/check_debian_pod.sh" \
            "${CONTAINER_NAME}" "${TEST_PORT}" "${RHEL8_IP}"
        ;;

    tcp-wrappers)
        require_rhel9
        run bash "${SCRIPT_DIR}/diagnostics/check_tcp_wrappers.sh" "${RHEL9_IP}"
        ;;

    # ── SELinux ──────────────────────────────────────────────────────────────
    selinux)
        run bash "${SCRIPT_DIR}/diagnostics/check_selinux.sh" "${TEST_PORT}"
        ;;

    selinux-fix)
        echo "Running SELinux fix in diagnose (dry-run) mode."
        echo "Append ' fix' to apply: RHEL9_IP=... ./run.sh selinux-fix fix"
        MODE="${2:-diagnose}"
        run bash "${SCRIPT_DIR}/fixes/fix_selinux_podman.sh" "${TEST_PORT}" "${MODE}"
        ;;

    # ── AppArmor ─────────────────────────────────────────────────────────────
    apparmor)
        echo "Running AppArmor fix in diagnose (dry-run) mode."
        echo "Append ' fix' to apply: ./run.sh apparmor fix"
        MODE="${2:-diagnose}"
        run bash "${SCRIPT_DIR}/fixes/fix_apparmor_podman.sh" "${CONTAINER_NAME}" "${MODE}"
        ;;

    # ── Fixes ────────────────────────────────────────────────────────────────
    fix-fw)
        echo "Running firewall fix in diagnose (dry-run) mode."
        echo "Append ' fix' to apply: ./run.sh fix-fw fix"
        MODE="${2:-diagnose}"
        run bash "${SCRIPT_DIR}/fixes/fix_podman_firewall.sh" "${TEST_PORT}" "${MODE}"
        ;;

    restart)
        run bash "${SCRIPT_DIR}/fixes/restart_podman_network.sh" \
            "${CONTAINER_NAME}" "${TEST_PORT}" "${CONTAINER_PORT}"
        ;;

    # ── Config / Help ────────────────────────────────────────────────────────
    config)
        echo "============================================="
        echo " Active configuration (test.env + defaults)"
        echo "============================================="
        printf "  %-20s : %s\n" "RHEL8_IP"         "${RHEL8_IP}"
        printf "  %-20s : %s\n" "RHEL9_IP"         "${RHEL9_IP}"
        printf "  %-20s : %s\n" "TEST_PORT"         "${TEST_PORT}"
        printf "  %-20s : %s\n" "CONTAINER_NAME"    "${CONTAINER_NAME}"
        printf "  %-20s : %s\n" "CONTAINER_IMAGE"   "${CONTAINER_IMAGE}"
        printf "  %-20s : %s\n" "CONTAINER_PORT"    "${CONTAINER_PORT}"
        printf "  %-20s : %s\n" "TIMEOUT_SECS"      "${TIMEOUT_SECS}"
        printf "  %-20s : %s\n" "CAPTURE_DURATION"  "${CAPTURE_DURATION}"
        echo "============================================="
        if [[ -f "${CFG}" ]]; then
            echo " Config loaded from: ${CFG}"
        else
            echo " Config file not found: ${CFG}"
            echo " Create it: cp test.env.example test.env"
        fi
        echo "============================================="
        ;;

    help|--help|-h)
        sed -n '3,35p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        ;;

    *)
        echo "[ERROR] Unknown command: ${CMD}"
        echo "Run './run.sh help' for usage."
        exit 1
        ;;
esac

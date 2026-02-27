#!/usr/bin/env bash
# fix_selinux_podman.sh - Apply SELinux fixes for Podman container networking.
# Addresses the case where SELinux denies container processes from binding to
# ports or communicating with external hosts.
#
# Run on the RHEL9 EC2 (Podman host) as root / with sudo.
#
# Usage: ./fix_selinux_podman.sh [PORT] [MODE]
#   PORT  Port the container is using (default: 21240)
#   MODE  'fix' to apply changes, 'diagnose' to only report (default: diagnose)

set -uo pipefail

PORT="${1:-21240}"
MODE="${2:-diagnose}"

echo "============================================="
echo " SELINUX PODMAN FIX"
echo "============================================="
echo " Port : ${PORT}"
echo " Mode : ${MODE}"
echo " Host : $(hostname)"
echo "============================================="
echo ""

if [[ "${EUID}" -ne 0 ]]; then
    SUDO="sudo"
    echo "[INFO] Running as non-root, using sudo for privileged commands."
else
    SUDO=""
fi

if ! command -v sestatus &>/dev/null; then
    echo "[INFO] SELinux not installed on this host. No action needed."
    exit 0
fi

SEMODE=$(${SUDO} getenforce 2>/dev/null || echo "unknown")
echo "[INFO] SELinux mode: ${SEMODE}"
echo ""

apply() {
    local cmd="$1"
    local desc="$2"
    echo "  [ACTION] ${desc}"
    echo "           Command: ${cmd}"
    if [[ "${MODE}" == "fix" ]]; then
        eval "${SUDO} ${cmd}" && echo "  [OK ] Applied." || echo "  [ERROR] Failed to apply."
    else
        echo "  [DRY-RUN] Would run: sudo ${cmd}"
    fi
    echo ""
}

# ── Check current denials ─────────────────────────────────────────────────────
echo "── Recent AVC denials ──────────────────────"
if command -v ausearch &>/dev/null; then
    RECENT=$(${SUDO} ausearch -m avc -ts recent 2>/dev/null | grep 'type=AVC' | tail -20)
    if [[ -n "${RECENT}" ]]; then
        echo "  [WARN] Active SELinux denials:"
        echo "${RECENT}" | sed 's/^/  /'
        echo ""

        # Generate suggested policy
        echo "  Suggested policy from denials (audit2allow):"
        echo "${RECENT}" | ${SUDO} audit2allow 2>/dev/null | sed 's/^/  /' || \
            echo "  (install policycoreutils-python-utils for audit2allow)"
    else
        echo "  [OK ] No recent AVC denials."
    fi
else
    echo "  ausearch not available. Checking audit.log directly..."
    ${SUDO} grep 'type=AVC' /var/log/audit/audit.log 2>/dev/null | tail -20 | sed 's/^/  /' || \
        echo "  Cannot access audit log."
fi

echo ""

# ── Port labeling fix ─────────────────────────────────────────────────────────
echo "── Port SELinux label fix ──────────────────"
if command -v semanage &>/dev/null; then
    CURRENT_LABEL=$(${SUDO} semanage port -l 2>/dev/null | grep -E "\b${PORT}\b" || echo "")
    if [[ -n "${CURRENT_LABEL}" ]]; then
        echo "  [OK ] Port ${PORT} already has a label: ${CURRENT_LABEL}"
    else
        echo "  [WARN] Port ${PORT} has no SELinux label."
        apply "semanage port -a -t http_port_t -p tcp ${PORT}" \
            "Label port ${PORT} as http_port_t (allows containers to bind)"
    fi
else
    echo "  semanage not available. Install: dnf install policycoreutils-python-utils"
fi

echo ""

# ── SELinux booleans for Podman ───────────────────────────────────────────────
echo "── SELinux Boolean Fixes ───────────────────"

check_and_set_bool() {
    local bool_name="$1"
    local reason="$2"
    local current
    current=$(${SUDO} getsebool "${bool_name}" 2>/dev/null | awk '{print $NF}' || echo "N/A")
    printf "  %-40s : %s\n" "${bool_name}" "${current}"
    if [[ "${current}" != "on" ]]; then
        echo "    Reason: ${reason}"
        apply "setsebool -P ${bool_name} on" "Enable ${bool_name}"
    fi
}

check_and_set_bool "container_manage_cgroup" \
    "Allows containers to manage cgroups (required for many container workloads)"

check_and_set_bool "container_connect_any" \
    "Allows containers to connect to any port (required for external connectivity)"

# ── Generate and apply custom policy from recent denials ─────────────────────
echo "── Custom SELinux Policy from Denials ──────"
if command -v audit2allow &>/dev/null && command -v ausearch &>/dev/null; then
    DENY_CHECK=$(${SUDO} ausearch -m avc -ts recent 2>/dev/null | grep 'type=AVC' | wc -l)
    if [[ "${DENY_CHECK}" -gt 0 ]]; then
        POLICY_NAME="podman_netfix"
        POLICY_TE="/tmp/${POLICY_NAME}.te"
        POLICY_PP="/tmp/${POLICY_NAME}.pp"

        echo "  Generating custom policy module '${POLICY_NAME}'..."
        ${SUDO} ausearch -m avc -ts recent 2>/dev/null | \
            ${SUDO} audit2allow -M "${POLICY_NAME}" 2>/dev/null && \
            echo "  [OK ] Policy files generated: /tmp/${POLICY_NAME}.{te,pp}" || \
            echo "  [WARN] Could not generate policy."

        if [[ "${MODE}" == "fix" ]] && [[ -f "/tmp/${POLICY_NAME}.pp" ]]; then
            echo "  Applying custom policy..."
            ${SUDO} semodule -i "/tmp/${POLICY_NAME}.pp" && \
                echo "  [OK ] Custom policy applied." || \
                echo "  [ERROR] Failed to apply policy."
        else
            echo "  [DRY-RUN] Would apply: semodule -i ${POLICY_PP}"
        fi
    else
        echo "  No current denials to build a policy from."
    fi
fi

echo ""

# ── Temporary diagnostic mode (permissive for container context) ──────────────
echo "── Temporary Permissive Mode (container_t) ─"
echo "  To test if SELinux is blocking container networking:"
echo "  1. Set container_t domain to permissive:"
echo "     semanage permissive -a container_t"
echo "  2. Re-test with nc"
echo "  3. Check for denials: ausearch -m avc -ts recent | grep container"
echo "  4. Re-enable:"
echo "     semanage permissive -d container_t"
echo ""

if [[ "${MODE}" == "diagnose" ]]; then
    echo "============================================="
    echo " DRY-RUN COMPLETE"
    echo " Re-run with MODE=fix to apply changes:"
    echo "   ./fix_selinux_podman.sh ${PORT} fix"
    echo "============================================="
else
    echo "============================================="
    echo " FIXES APPLIED"
    echo " Verify with: diagnostics/check_selinux.sh ${PORT}"
    echo " Then retry:  ec2-to-podman/client_test.sh <HOST> ${PORT}"
    echo "============================================="
fi

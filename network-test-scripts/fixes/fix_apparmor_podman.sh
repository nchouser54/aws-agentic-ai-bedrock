#!/usr/bin/env bash
# fix_apparmor_podman.sh - Apply AppArmor fixes so that nc/ncat inside a
# Debian-based Podman container can accept external connections.
#
# AppArmor is the Mandatory Access Control system used on Debian/Ubuntu.
# It is the Debian equivalent of SELinux on RHEL.  When AppArmor confines a
# container process, it can silently block network operations (bind, accept,
# connect) even though the container's firewall (ufw/iptables) appears open.
#
# Symptoms this fixes:
#   - nc inside the container starts but immediately rejects connections
#   - /var/log/syslog shows: apparmor="DENIED" operation="create" profile=...
#   - check_debian_pod.sh reports AppArmor active with a profile for nc/ncat
#
# Run on the RHEL9 EC2 that hosts the Podman container (as root or with sudo).
# Optionally also run inside the container (see Section 2).
#
# Usage: ./fix_apparmor_podman.sh [CONTAINER_NAME] [MODE]
#   CONTAINER_NAME  Podman container (default: dev-pod)
#   MODE            'fix' to apply changes, 'diagnose' to only report (default: diagnose)

set -uo pipefail

CONTAINER="${1:-dev-pod}"
MODE="${2:-diagnose}"

echo "============================================="
echo " APPARMOR PODMAN FIX"
echo "============================================="
echo " Container : ${CONTAINER}"
echo " Mode      : ${MODE}"
echo " Host      : $(hostname)"
echo " Run as    : $(id)"
echo "============================================="
echo ""

if [[ "${EUID}" -ne 0 ]]; then
    SUDO="sudo"
    echo "[INFO] Running as non-root, using sudo for privileged commands."
else
    SUDO=""
fi

apply() {
    local cmd="$1"
    local desc="$2"
    echo "  [ACTION] ${desc}"
    echo "           Command: ${cmd}"
    if [[ "${MODE}" == "fix" ]]; then
        eval "${SUDO} ${cmd}" && echo "  [OK ] Applied." || echo "  [ERROR] Failed — check output above."
    else
        echo "  [DRY-RUN] Would run: sudo ${cmd}"
    fi
    echo ""
}

# ── Check if AppArmor is installed on this host ───────────────────────────────
echo "── Host AppArmor status ────────────────────"
if ! command -v aa-status &>/dev/null && ! [[ -d /sys/kernel/security/apparmor ]]; then
    echo "  [OK ] AppArmor not installed/active on this host. No action needed."
    echo "  If the Debian container has its own AppArmor, exec into it and run"
    echo "  this script again inside the container."
    exit 0
fi

if command -v aa-status &>/dev/null; then
    ${SUDO} aa-status 2>/dev/null | head -20 | sed 's/^/  /'
else
    echo "  AppArmor kernel security filesystem present."
    cat /sys/kernel/security/apparmor/profiles 2>/dev/null | head -20 | sed 's/^/  /' || true
fi
echo ""

# ── Check if AppArmor is confining the container ──────────────────────────────
echo "── AppArmor profile for container '${CONTAINER}' ──"
CONTAINER_ID=$(${SUDO} podman ps --filter "name=${CONTAINER}" --format "{{.ID}}" 2>/dev/null | head -1 || true)
if [[ -z "${CONTAINER_ID}" ]]; then
    echo "  [WARN] Container '${CONTAINER}' is not running."
    echo "  Start the container first, then re-run this script."
    echo "  Running containers:"
    ${SUDO} podman ps --format "  {{.Names}}\t{{.Status}}" 2>/dev/null || true
else
    echo "  Container ID: ${CONTAINER_ID:0:12}"
    # Check the AppArmor profile assigned to the container
    CONT_PROFILE=$(${SUDO} podman inspect "${CONTAINER}" 2>/dev/null | \
        python3 -c "
import json, sys
d = json.load(sys.stdin)[0]
hc = d.get('HostConfig', {})
sec = hc.get('SecurityOpt', []) or []
aa = [s for s in sec if 'apparmor' in s.lower()]
print('\n'.join(aa) if aa else 'none (using Podman default)')
" 2>/dev/null || echo "  (could not inspect container)")
    echo "  AppArmor SecurityOpt: ${CONT_PROFILE}"
fi

echo ""

# ── Check for recent AppArmor denials ─────────────────────────────────────────
echo "── Recent AppArmor denials (last 30 minutes) ──"
DENIALS=""
if [[ -f /var/log/syslog ]]; then
    DENIALS=$(${SUDO} grep -i 'apparmor.*DENIED\|DENIED.*apparmor' /var/log/syslog 2>/dev/null | \
        grep -iE 'nc|ncat|netcat|sh|bash' | tail -20 || true)
elif [[ -f /var/log/kern.log ]]; then
    DENIALS=$(${SUDO} grep -i 'apparmor.*DENIED' /var/log/kern.log 2>/dev/null | tail -20 || true)
else
    DENIALS=$(${SUDO} dmesg 2>/dev/null | grep -i 'apparmor.*DENIED' | tail -20 || true)
fi

if [[ -n "${DENIALS}" ]]; then
    echo "  [WARN] AppArmor denials related to nc/shell:"
    echo "${DENIALS}" | sed 's/^/  /'
else
    echo "  No recent AppArmor denials found for nc/ncat/sh."
fi

echo ""

# ── Fix 1: Relaunch container with apparmor=unconfined ────────────────────────
echo "── Fix 1: Relaunch with apparmor=unconfined (quickest fix) ──"
echo "  This removes all AppArmor confinement from the container."
echo "  Use for testing; for production prefer Fix 2 (custom profile)."
echo ""
echo "  Stop current container first:"
echo "    ${SUDO} podman stop ${CONTAINER} && ${SUDO} podman rm ${CONTAINER}"
echo ""
echo "  Relaunch with --security-opt apparmor=unconfined:"
echo "    ${SUDO} podman run -d --name ${CONTAINER} \\"
echo "      --security-opt apparmor=unconfined \\"
echo "      -p 0.0.0.0:<PORT>:<PORT>/tcp \\"
echo "      <IMAGE> <NC_COMMAND>"
echo ""

# ── Fix 2: Set container's AppArmor profile to complain mode ──────────────────
echo "── Fix 2: Set nc profile to complain mode (logs but doesn't block) ──"
if command -v aa-complain &>/dev/null; then
    for nc_path in /usr/bin/nc.openbsd /usr/bin/nc /usr/bin/ncat /usr/bin/netcat; do
        if [[ -f "${nc_path}" ]]; then
            echo "  Found: ${nc_path}"
            # Check if there's an existing profile to put into complain mode
            if ${SUDO} aa-status 2>/dev/null | grep -q "$(basename ${nc_path})"; then
                apply "aa-complain ${nc_path}" \
                    "Set $(basename ${nc_path}) AppArmor profile to complain mode"
            else
                echo "  [OK ] No AppArmor profile found for ${nc_path}."
            fi
        fi
    done
else
    echo "  aa-complain not available. Install: apt-get install apparmor-utils"
fi

echo ""

# ── Fix 3: Set container process to complain mode via profile name ─────────────
echo "── Fix 3: Set container AppArmor profile to complain mode ──"
if [[ -n "${CONTAINER_ID:-}" ]]; then
    CONT_LABEL=$(${SUDO} podman exec "${CONTAINER}" sh -c \
        'cat /proc/1/attr/current 2>/dev/null || echo "unconfined"' 2>/dev/null || echo "unconfined")
    echo "  Container init AppArmor label: ${CONT_LABEL}"
    if [[ "${CONT_LABEL}" != "unconfined" ]]; then
        PROFILE_NAME=$(echo "${CONT_LABEL}" | sed 's/ .*//')
        echo "  Profile: ${PROFILE_NAME}"
        if command -v aa-complain &>/dev/null; then
            apply "aa-complain '${PROFILE_NAME}'" \
                "Set profile '${PROFILE_NAME}' to complain mode"
        fi
    else
        echo "  [OK ] Container init process is unconfined."
    fi
fi

echo ""

# ── Fix 4: Exec-level fix inside the running container ────────────────────────
echo "── Fix 4: Disable AppArmor for nc inside the container ──"
echo "  (Run these commands inside the container if it has apparmor-utils installed)"
echo ""
echo "    podman exec ${CONTAINER} apt-get install -y apparmor-utils"
echo "    podman exec ${CONTAINER} aa-disable /usr/bin/nc.openbsd"
echo "    OR"
echo "    podman exec ${CONTAINER} aa-complain /usr/bin/nc.openbsd"
echo ""

# ── Verification ──────────────────────────────────────────────────────────────
echo "── Verification after fix ──────────────────"
echo "  1. Check AppArmor status:"
echo "     aa-status | grep -i nc"
echo ""
echo "  2. Watch denials in real-time:"
echo "     tail -f /var/log/syslog | grep -i apparmor"
echo ""
echo "  3. Re-test connectivity:"
echo "     # From RHEL8:"
echo "     ec2-to-podman/client_test.sh <RHEL9_IP> <PORT>"
echo ""

if [[ "${MODE}" == "diagnose" ]]; then
    echo "============================================="
    echo " DRY-RUN COMPLETE"
    echo " Re-run with MODE=fix to apply changes:"
    echo "   ./fix_apparmor_podman.sh ${CONTAINER} fix"
    echo "============================================="
else
    echo "============================================="
    echo " FIXES APPLIED"
    echo " Verify with: diagnostics/check_debian_pod.sh ${CONTAINER} <PORT>"
    echo " Then retry:  ec2-to-podman/client_test.sh <HOST> <PORT>"
    echo "============================================="
fi

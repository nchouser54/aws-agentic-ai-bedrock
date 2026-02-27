#!/usr/bin/env bash
# check_selinux.sh - Check SELinux status and recent denials related to
# network connections and Podman containers.
# Run on the RHEL8 or RHEL9 host.
#
# Usage: ./check_selinux.sh [PORT]
#   PORT  Specific port to check labeling for (optional, default: 9000)

set -uo pipefail

PORT="${1:-9000}"

echo "============================================="
echo " SELINUX NETWORK & PODMAN CHECK"
echo "============================================="
echo " Host : $(hostname)"
echo " Port : ${PORT}"
echo "============================================="
echo ""

# ---------- SELinux mode ----------
echo "── SELinux Status ──────────────────────────"
if command -v sestatus &>/dev/null; then
    sestatus | sed 's/^/  /'
    MODE=$(getenforce 2>/dev/null || echo "unknown")
    echo ""
    echo "  Current mode: ${MODE}"
    if [[ "${MODE}" == "Enforcing" ]]; then
        echo "  [INFO] SELinux is ENFORCING — policies are actively blocking."
    elif [[ "${MODE}" == "Permissive" ]]; then
        echo "  [INFO] SELinux is PERMISSIVE — denials logged but not blocked."
    fi
else
    echo "  SELinux not installed or sestatus not available."
    exit 0
fi

echo ""

# ---------- Recent AVC denials ----------
echo "── Recent AVC Denials (last 1 hour) ────────"
if command -v ausearch &>/dev/null; then
    DENIALS=$(ausearch -m avc -ts recent 2>/dev/null | grep 'type=AVC' | tail -30)
    if [[ -n "${DENIALS}" ]]; then
        echo "  [WARN] Recent SELinux denials found:"
        echo "${DENIALS}" | sed 's/^/  /'
        echo ""
        echo "  For human-readable output:"
        ausearch -m avc -ts recent 2>/dev/null | audit2allow 2>/dev/null | head -30 | sed 's/^/  /' || \
            echo "  (install policycoreutils-python-utils for audit2allow)"
    else
        echo "  [OK] No recent AVC denials found."
    fi
elif [[ -f /var/log/audit/audit.log ]]; then
    DENIALS=$(grep 'type=AVC' /var/log/audit/audit.log | tail -20)
    if [[ -n "${DENIALS}" ]]; then
        echo "  [WARN] AVC denials in audit.log:"
        echo "${DENIALS}" | sed 's/^/  /'
    else
        echo "  [OK] No AVC denials in audit.log."
    fi
else
    echo "  Cannot read audit log (run as root for full access)."
fi

echo ""

# ---------- Port labeling ----------
echo "── SELinux Port Labels for ${PORT} ─────────"
if command -v semanage &>/dev/null; then
    LABEL=$(semanage port -l 2>/dev/null | grep -E "\b${PORT}\b" || echo "")
    if [[ -n "${LABEL}" ]]; then
        echo "  [OK ] Port ${PORT} has an SELinux label:"
        echo "  ${LABEL}"
    else
        echo "  [WARN] Port ${PORT} has NO SELinux port label."
        echo "  This may prevent processes from binding to it."
        echo ""
        echo "  Common port types for network services:"
        echo "    http_port_t    : 80, 443, 8080, 8443"
        echo "    ssh_port_t     : 22"
        echo "    unreserved_port_t : ephemeral / custom ports"
        echo ""
        echo "  Fix options:"
        echo "    Option A (label port as http-like):"
        echo "      semanage port -a -t http_port_t -p tcp ${PORT}"
        echo ""
        echo "    Option B (label as unreserved port):"
        echo "      semanage port -a -t unreserved_port_t -p tcp ${PORT}"
        echo ""
        echo "    Option C (temporary — allow all container networking):"
        echo "      setsebool -P container_manage_cgroup on"
        echo "      setsebool -P container_use_cephfs on"
    fi
else
    echo "  semanage not available (install policycoreutils-python-utils)"
fi

echo ""

# ---------- Podman SELinux booleans ----------
echo "── SELinux Booleans for Container/Podman ───"
PODMAN_BOOLEANS=(
    "container_manage_cgroup"
    "container_use_cephfs"
    "container_connect_any"
    "virt_use_nfs"
    "virt_sandbox_use_netlink"
    "virt_sandbox_use_all_caps"
)

for bool in "${PODMAN_BOOLEANS[@]}"; do
    VAL=$(getsebool "${bool}" 2>/dev/null || echo "N/A")
    printf "  %-40s : %s\n" "${bool}" "${VAL}"
done

echo ""
echo "── nc Process SELinux Context ──────────────"
if pgrep -x nc &>/dev/null || pgrep -x ncat &>/dev/null; then
    ps auxZ 2>/dev/null | grep -E '\bnc\b|\bncat\b' | grep -v grep | sed 's/^/  /' || true
else
    echo "  nc/ncat not currently running."
fi

echo ""
echo "── Quick Fixes If SELinux Is Blocking ──────"
echo ""
echo "  1. Temporarily set to Permissive to confirm SELinux is the cause:"
echo "     setenforce 0"
echo "     (run nc test — if it works, SELinux is the issue)"
echo "     setenforce 1  # re-enable after test"
echo ""
echo "  2. Generate and apply a custom policy from denials:"
echo "     ausearch -m avc -ts recent | audit2allow -M my_podman_policy"
echo "     semodule -i my_podman_policy.pp"
echo ""
echo "  3. For Podman containers, apply the container_t label fix:"
echo "     setsebool -P container_manage_cgroup on"
echo "     setsebool -P container_connect_any on"
echo ""
echo "  See also: fixes/fix_selinux_podman.sh"
echo "============================================="

#!/usr/bin/env bash
# fix_podman_firewall.sh - Fix firewalld and iptables/nftables configuration
# so that traffic from a Podman container on RHEL9 can reach external EC2s,
# AND so that external hosts can connect to the published container port.
#
# Run on the RHEL9 EC2 that hosts the Podman container (as root or with sudo).
#
# The symptom this fixes:
#   - tcpdump sees packets arriving on the RHEL9 host
#   - But nc inside / connecting to the container still times out
#   - firewall-cmd --list-all doesn't show the port as allowed
#
# Usage: ./fix_podman_firewall.sh [PORT] [ZONE]
#   PORT  Port to open (default: 9000)
#   ZONE  firewalld zone (default: public)

set -euo pipefail

PORT="${1:-9000}"
ZONE="${2:-public}"
PROTO="tcp"

echo "============================================="
echo " PODMAN FIREWALL FIX"
echo "============================================="
echo " Port     : ${PORT}/${PROTO}"
echo " Zone     : ${ZONE}"
echo " Host     : $(hostname)"
echo " Run as   : $(id)"
echo "============================================="
echo ""

if [[ "${EUID}" -ne 0 ]]; then
    echo "[WARN] Not running as root. Commands will use sudo."
    SUDO="sudo"
else
    SUDO=""
fi

CHANGES=()

# ── Step 1: Enable masquerade ─────────────────────────────────────────────────
echo "[STEP 1] Enable masquerade in zone '${ZONE}'..."
echo "  Masquerade allows container NAT traffic to leave the host as the host IP."
if ${SUDO} firewall-cmd --zone="${ZONE}" --query-masquerade 2>/dev/null; then
    echo "  [OK ] Masquerade already enabled."
else
    ${SUDO} firewall-cmd --zone="${ZONE}" --add-masquerade --permanent
    CHANGES+=("masquerade enabled in zone ${ZONE}")
    echo "  [OK ] Masquerade added (permanent)."
fi

# ── Step 2: Open the published port ──────────────────────────────────────────
echo ""
echo "[STEP 2] Open port ${PORT}/${PROTO} in zone '${ZONE}'..."
if ${SUDO} firewall-cmd --zone="${ZONE}" --query-port="${PORT}/${PROTO}" 2>/dev/null; then
    echo "  [OK ] Port ${PORT}/${PROTO} already open."
else
    ${SUDO} firewall-cmd --zone="${ZONE}" --add-port="${PORT}/${PROTO}" --permanent
    CHANGES+=("port ${PORT}/${PROTO} opened in zone ${ZONE}")
    echo "  [OK ] Port ${PORT}/${PROTO} added (permanent)."
fi

# ── Step 3: Ensure IP forwarding is enabled ───────────────────────────────────
echo ""
echo "[STEP 3] Ensure kernel IP forwarding is enabled..."
CURRENT_FWD=$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null || echo "0")
if [[ "${CURRENT_FWD}" == "1" ]]; then
    echo "  [OK ] IP forwarding already enabled."
else
    ${SUDO} sysctl -w net.ipv4.ip_forward=1
    # Make persistent
    if ! grep -q 'net.ipv4.ip_forward' /etc/sysctl.d/99-podman.conf 2>/dev/null; then
        echo "net.ipv4.ip_forward=1" | ${SUDO} tee -a /etc/sysctl.d/99-podman.conf
    fi
    CHANGES+=("IP forwarding enabled")
    echo "  [OK ] IP forwarding enabled and persisted."
fi

# ── Step 4: Handle RHEL9 nftables / Netavark conflict ────────────────────────
echo ""
echo "[STEP 4] Checking for Netavark + firewalld nftables conflict (RHEL9)..."
OS_VER=$(grep VERSION_ID /etc/os-release | cut -d= -f2 | tr -d '"' | cut -d. -f1)
if [[ "${OS_VER}" -ge 9 ]] 2>/dev/null; then
    echo "  [INFO] RHEL9+ detected. Podman uses Netavark (nftables backend)."
    echo "  [INFO] firewalld also uses nftables on RHEL9."
    echo ""
    echo "  Key fix: ensure the 'podman' interface/zone is trusted."

    # Add the podman network interface to the trusted zone
    PODMAN_IFACE=$(ip link show | grep -E 'podman|cni' | awk -F': ' '{print $2}' | head -1 || true)
    if [[ -n "${PODMAN_IFACE}" ]]; then
        echo "  Found Podman interface: ${PODMAN_IFACE}"
        if ! ${SUDO} firewall-cmd --zone=trusted --query-interface="${PODMAN_IFACE}" 2>/dev/null; then
            ${SUDO} firewall-cmd --zone=trusted --add-interface="${PODMAN_IFACE}" --permanent
            CHANGES+=("added ${PODMAN_IFACE} to trusted zone")
            echo "  [OK ] Added ${PODMAN_IFACE} to trusted zone."
        else
            echo "  [OK ] ${PODMAN_IFACE} already in trusted zone."
        fi
    else
        echo "  [INFO] No podman/cni interface found yet (container may not be running)."
        echo "         After starting your container, re-run this script."
    fi

    # Add the default Podman subnet to trusted
    PODMAN_SUBNET="10.88.0.0/16"
    echo ""
    echo "  Adding Podman default subnet ${PODMAN_SUBNET} to trusted zone..."
    if ! ${SUDO} firewall-cmd --zone=trusted --query-source="${PODMAN_SUBNET}" 2>/dev/null; then
        ${SUDO} firewall-cmd --zone=trusted --add-source="${PODMAN_SUBNET}" --permanent
        CHANGES+=("Podman subnet ${PODMAN_SUBNET} trusted")
        echo "  [OK ] Subnet ${PODMAN_SUBNET} added to trusted zone."
    else
        echo "  [OK ] Subnet already trusted."
    fi

    # RHEL9 specific: ensure FORWARD policy allows container traffic
    echo ""
    echo "  Ensuring FORWARD chain allows Podman traffic..."
    if ! ${SUDO} iptables -C FORWARD -i podman0 -j ACCEPT 2>/dev/null && \
       ! ${SUDO} iptables -C FORWARD -o podman0 -j ACCEPT 2>/dev/null; then
        echo "  [INFO] Podman FORWARD rules not found — Netavark manages these via nftables."
        echo "         This is normal on RHEL9+."
    fi
fi

# ── Step 5: Reload firewalld ──────────────────────────────────────────────────
echo ""
echo "[STEP 5] Reloading firewalld..."
${SUDO} firewall-cmd --reload
echo "  [OK ] firewalld reloaded."

# ── Step 6: Restart Podman containers ────────────────────────────────────────
echo ""
echo "[STEP 6] Restart any running containers to pick up new firewall rules..."
echo "  (Podman re-applies port mappings on container restart)"
RUNNING=$(${SUDO} podman ps --format '{{.Names}}' 2>/dev/null || podman ps --format '{{.Names}}' 2>/dev/null || true)
if [[ -n "${RUNNING}" ]]; then
    echo "  Running containers: ${RUNNING}"
    echo "  [ACTION REQUIRED] Restart your containers manually:"
    echo "    podman restart <container_name>"
    echo "  OR re-run: ec2-to-podman/podman_server_setup.sh"
else
    echo "  No running containers found. Start your container after this fix."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================="
echo " CHANGES APPLIED"
echo "============================================="
if [[ ${#CHANGES[@]} -eq 0 ]]; then
    echo " No changes needed — firewall was already correctly configured."
    echo " If you still have connectivity issues, check:"
    echo "   1. AWS Security Group inbound rules for port ${PORT}"
    echo "   2. SELinux: run diagnostics/check_selinux.sh"
    echo "   3. Container binding: run ec2-to-podman/check_podman_config.sh"
else
    for change in "${CHANGES[@]}"; do
        echo "  [+] ${change}"
    done
fi

echo ""
echo " Verification commands:"
echo "   firewall-cmd --zone=${ZONE} --list-all"
echo "   firewall-cmd --zone=trusted --list-all"
echo ""
echo " Next step: re-run the connectivity test:"
echo "   ec2-to-podman/client_test.sh <RHEL8_IP> ${PORT}  # from RHEL8"
echo "============================================="

#!/usr/bin/env bash
# tcpdump_capture.sh - Capture traffic on a specific port to verify whether
# packets are arriving / leaving the host or being dropped by the kernel.
#
# KEY INSIGHT:
#   tcpdump captures at the NIC BEFORE iptables/nftables processes the packet.
#   If tcpdump SEES the packet but nc DOESN'T receive it → firewall is dropping it.
#   If tcpdump DOESN'T see the packet → issue is upstream (SG, routing, Podman NAT).
#
# Run this on EITHER host while running the nc test from the other side.
#
# Usage: ./tcpdump_capture.sh [PORT] [INTERFACE] [DURATION_SECS]
#   PORT       Port to capture (default: 21240)
#   INTERFACE  Network interface (default: auto-detected)
#   DURATION   How long to capture in seconds (default: 30)
#
# Requires: tcpdump (sudo/root), or run as root.

set -uo pipefail

PORT="${1:-21240}"
IFACE="${2:-}"
DURATION="${3:-30}"
CAPFILE="/tmp/capture_port${PORT}_$(date +%Y%m%d_%H%M%S).pcap"

echo "============================================="
echo " TCPDUMP PACKET CAPTURE"
echo "============================================="
echo " Port      : ${PORT}"
echo " Duration  : ${DURATION}s"
echo " Capture   : ${CAPFILE}"
echo "============================================="
echo ""

# ---------- Auto-detect interface ----------
if [[ -z "${IFACE}" ]]; then
    # Prefer the primary default route interface
    IFACE=$(ip route show default 2>/dev/null | awk '/default/ {print $5}' | head -1)
    if [[ -z "${IFACE}" ]]; then
        IFACE=$(ip link show | awk -F': ' '/^[0-9]+: [^lo]/{print $2}' | head -1)
    fi
    echo "[INFO] Auto-detected interface: ${IFACE}"
fi

if [[ -z "${IFACE}" ]]; then
    echo "[ERROR] Could not detect network interface. Specify it as the 2nd argument."
    exit 1
fi

echo "[INFO] Interface IP: $(ip addr show "${IFACE}" | grep 'inet ' | awk '{print $2}')"
echo ""
echo "[INFO] Starting capture for ${DURATION}s..."
echo "[INFO] While this runs, trigger the nc test from the other host."
echo ""
echo "──── LIVE OUTPUT ────────────────────────────"

# Capture on the main interface AND loopback (for local traffic)
# -n: no DNS resolution  -v: verbose  -l: line-buffered
timeout "${DURATION}" tcpdump -i "${IFACE}" -n -l -v \
    "tcp port ${PORT}" 2>&1 | tee /tmp/tcpdump_live_$$.txt || true

echo "──── END LIVE OUTPUT ─────────────────────────"
echo ""

# Save full pcap for offline analysis
echo "[INFO] Saving full pcap file..."
timeout "${DURATION}" tcpdump -i "${IFACE}" -n -w "${CAPFILE}" \
    "tcp port ${PORT}" 2>/dev/null &
TCPDUMP_PID=$!
sleep "${DURATION}"
kill "${TCPDUMP_PID}" 2>/dev/null || true
wait "${TCPDUMP_PID}" 2>/dev/null || true

echo ""
echo "============================================="
echo " ANALYSIS"
echo "============================================="

LIVE_LOG="/tmp/tcpdump_live_$$.txt"
SYN_COUNT=$(grep -c 'Flags \[S\]' "${LIVE_LOG}" 2>/dev/null || echo 0)
SYNACK_COUNT=$(grep -c 'Flags \[S\.\]' "${LIVE_LOG}" 2>/dev/null || echo 0)
RST_COUNT=$(grep -c 'Flags \[R' "${LIVE_LOG}" 2>/dev/null || echo 0)
DATA_COUNT=$(grep -c 'length [1-9]' "${LIVE_LOG}" 2>/dev/null || echo 0)

echo " SYN packets seen     : ${SYN_COUNT}"
echo " SYN-ACK packets seen : ${SYNACK_COUNT}"
echo " RST packets seen     : ${RST_COUNT}"
echo " Data packets seen    : ${DATA_COUNT}"
echo ""

if [[ "${SYN_COUNT}" -gt 0 && "${SYNACK_COUNT}" -eq 0 ]]; then
    echo "[DIAGNOSIS] SYN packets arriving but NO SYN-ACK from this host."
    echo "  → The OS received the SYN but something is preventing the response."
    echo "  → Likely causes:"
    echo "    a) firewalld/iptables DROP rule on port ${PORT}"
    echo "    b) SELinux denying the bind/accept"
    echo "    c) nc not listening (bound to 127.0.0.1 or wrong port)"
    echo ""
    echo "  → Run: diagnostics/check_firewall.sh ${PORT}"
    echo "  → Run: diagnostics/check_selinux.sh"
elif [[ "${SYN_COUNT}" -eq 0 ]]; then
    echo "[DIAGNOSIS] NO SYN packets seen at all on port ${PORT}."
    echo "  → Packets are not arriving at this host."
    echo "  → Likely causes:"
    echo "    a) AWS Security Group blocking inbound port ${PORT}"
    echo "    b) Wrong destination IP being used by the sender"
    echo "    c) If source is Podman: container traffic not leaving RHEL9 host"
    echo "       (Podman NAT / masquerade not configured)"
    echo ""
    echo "  → Run tcpdump_capture.sh on the SENDER host to see if packets leave."
elif [[ "${SYNACK_COUNT}" -gt 0 && "${DATA_COUNT}" -eq 0 ]]; then
    echo "[DIAGNOSIS] Handshake completing (SYN+SYN-ACK) but no data transferred."
    echo "  → TCP connection is working! The nc application may not be sending data."
    echo "  → This is typically SUCCESS for a basic port test."
else
    echo "[DIAGNOSIS] Traffic detected — review the output above for anomalies."
fi

rm -f "${LIVE_LOG}"

echo ""
echo " Full pcap saved to : ${CAPFILE}"
echo " Analyze offline    : tcpdump -r ${CAPFILE} -n -v"
echo " View in Wireshark  : copy ${CAPFILE} to your workstation"
echo "============================================="

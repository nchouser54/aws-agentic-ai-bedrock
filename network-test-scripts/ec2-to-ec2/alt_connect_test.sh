#!/usr/bin/env bash
# alt_connect_test.sh - Test connectivity using every available tool, not just nc.
#
# When nc shows a timeout, this script tries alternative tools to isolate
# whether the problem is with nc specifically or the network path itself.
#
# Tools tried:
#   1. nc / ncat      - standard baseline
#   2. bash /dev/tcp  - bash built-in (no external binary — pure kernel socket)
#   3. socat          - different socket options than nc
#   4. curl           - HTTP TCP connect (reveals port vs application issue)
#   5. telnet         - different syscall path
#   6. python3 socket - raw socket, different SELinux context from nc
#   7. nmap -sT       - 'filtered' vs 'closed' tells you if firewall is dropping
#   8. openssl        - TCP + optional TLS
#
# KEY DIAGNOSTIC VALUE:
#   If /dev/tcp SUCCEEDS but nc FAILS → problem is nc-specific, not the network.
#   If nmap says FILTERED → firewall is silently dropping (no RST).
#   If nmap says CLOSED   → port is reachable but nothing is listening.
#
# Usage: ./alt_connect_test.sh <HOST> [PORT] [TIMEOUT_SECS]

set -uo pipefail

HOST="${1:-}"
PORT="${2:-21240}"
TIMEOUT="${3:-5}"

if [[ -z "${HOST}" ]]; then
    echo "Usage: $0 <HOST> [PORT] [TIMEOUT_SECS]"
    exit 1
fi

echo "============================================="
echo " ALTERNATIVE CONNECTIVITY TESTS"
echo "============================================="
echo " Target  : ${HOST}:${PORT}"
echo " Timeout : ${TIMEOUT}s per test"
echo " From    : $(hostname) ($(hostname -I | awk '{print $1}'))"
echo " Time    : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================="
echo ""

PASS=()
FAIL=()
SKIP=()

result() {
    local name="$1" rc="$2"
    printf "  [%-20s] " "${name}"
    if [[ "${rc}" -eq 0 ]]; then echo "SUCCESS"; PASS+=("${name}")
    else echo "FAILED"; FAIL+=("${name}"); fi
}

echo "── 1. nc / ncat ────────────────────────────"
if command -v nc &>/dev/null; then
    nc -z -w "${TIMEOUT}" "${HOST}" "${PORT}" 2>/dev/null; result "nc -z" $?
else
    echo "  [nc                   ] SKIP"; SKIP+=("nc")
fi
if command -v ncat &>/dev/null; then
    ncat -z -w "${TIMEOUT}" "${HOST}" "${PORT}" 2>/dev/null; result "ncat" $?
fi

echo ""
echo "── 2. bash /dev/tcp (no binary) ────────────"
echo "  Pure kernel socket — bypasses nc entirely."
timeout "${TIMEOUT}" bash -c "exec 3<>/dev/tcp/${HOST}/${PORT}" 2>/dev/null
RC=$?; exec 3>&- 2>/dev/null || true; result "/dev/tcp" "${RC}"
if [[ "${RC}" -eq 0 ]]; then
    echo "  [KEY] /dev/tcp succeeded — if nc fails, issue is nc-specific."
fi

echo ""
echo "── 3. socat ────────────────────────────────"
if command -v socat &>/dev/null; then
    timeout "${TIMEOUT}" socat /dev/null "TCP:${HOST}:${PORT},connect-timeout=${TIMEOUT}" 2>/dev/null
    result "socat" $?
else
    echo "  [socat                ] SKIP — dnf install socat"; SKIP+=("socat")
fi

echo ""
echo "── 4. curl --connect-only ──────────────────"
if command -v curl &>/dev/null; then
    COUT=$(curl --connect-only --max-time "${TIMEOUT}" "http://${HOST}:${PORT}" 2>&1)
    CRC=$?
    if [[ "${CRC}" -eq 0 ]] || echo "${COUT}" | grep -qE "52|Empty reply"; then
        echo "  [curl --connect-only  ] TCP CONNECTED (HTTP layer varies)"; PASS+=("curl")
    elif echo "${COUT}" | grep -q "refused"; then
        echo "  [curl --connect-only  ] PORT CLOSED (RST received)"; FAIL+=("curl")
    else
        echo "  [curl --connect-only  ] FAILED/TIMEOUT"; FAIL+=("curl")
    fi
else
    echo "  [curl                 ] SKIP"; SKIP+=("curl")
fi

echo ""
echo "── 5. telnet ───────────────────────────────"
if command -v telnet &>/dev/null; then
    TOUT=$(echo "quit" | timeout "${TIMEOUT}" telnet "${HOST}" "${PORT}" 2>&1 || true)
    if echo "${TOUT}" | grep -qE "Connected|Escape"; then
        echo "  [telnet               ] CONNECTED"; PASS+=("telnet")
    elif echo "${TOUT}" | grep -q "refused"; then
        echo "  [telnet               ] REFUSED (port closed)"; FAIL+=("telnet-refused")
    else
        echo "  [telnet               ] FAILED/TIMEOUT"; FAIL+=("telnet")
    fi
else
    echo "  [telnet               ] SKIP — dnf install telnet"; SKIP+=("telnet")
fi

echo ""
echo "── 6. python3 raw socket ───────────────────"
if command -v python3 &>/dev/null; then
    timeout "${TIMEOUT}" python3 - <<PYEOF 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(${TIMEOUT})
try:
    s.connect(('${HOST}', ${PORT}))
    s.close()
    sys.exit(0)
except Exception as e:
    sys.exit(1)
PYEOF
    result "python3 socket" $?
else
    echo "  [python3 socket       ] SKIP"; SKIP+=("python3")
fi

echo ""
echo "── 7. nmap SYN scan ────────────────────────"
if command -v nmap &>/dev/null; then
    NOUT=$(nmap -sT -p "${PORT}" --host-timeout "${TIMEOUT}s" "${HOST}" 2>/dev/null | grep -E "${PORT}|open|closed|filtered")
    echo "  ${NOUT}"
    if echo "${NOUT}" | grep -q "open"; then
        echo "  [nmap                 ] OPEN"; PASS+=("nmap")
    elif echo "${NOUT}" | grep -q "filtered"; then
        echo "  [nmap                 ] FILTERED — firewall is silently dropping (no RST)"
        echo "  [KEY] 'filtered' = DROP rule. 'closed' = RST = port is reachable."
        FAIL+=("nmap-filtered")
    else
        echo "  [nmap                 ] CLOSED"; FAIL+=("nmap-closed")
    fi
else
    echo "  [nmap                 ] SKIP — dnf install nmap"; SKIP+=("nmap")
fi

echo ""
echo "── 8. openssl s_client ─────────────────────"
if command -v openssl &>/dev/null; then
    OOUT=$(echo "Q" | timeout "${TIMEOUT}" openssl s_client -connect "${HOST}:${PORT}" 2>&1 | head -3 || true)
    if echo "${OOUT}" | grep -qE "CONNECTED|BEGIN CERT"; then
        echo "  [openssl              ] TCP+TLS CONNECTED"; PASS+=("openssl")
    elif echo "${OOUT}" | grep -qE "errno|no peer cert|handshake"; then
        echo "  [openssl              ] TCP connected, no TLS (expected for plain nc)"; PASS+=("openssl-tcp")
    else
        echo "  [openssl              ] FAILED"; FAIL+=("openssl")
    fi
else
    echo "  [openssl              ] SKIP"; SKIP+=("openssl")
fi

echo ""
echo "============================================="
echo " SUMMARY"
echo "============================================="
echo " PASS (${#PASS[@]}): ${PASS[*]:-none}"
echo " FAIL (${#FAIL[@]}): ${FAIL[*]:-none}"
echo " SKIP (${#SKIP[@]}): ${SKIP[*]:-none}"
echo ""

if [[ ${#PASS[@]} -gt 0 && ${#FAIL[@]} -gt 0 ]]; then
    echo " [FINDING] Mixed results — issue is tool-specific, not the network path."
    if [[ " ${PASS[*]} " =~ "/dev/tcp" ]] && printf '%s\n' "${FAIL[@]}" | grep -q "^nc"; then
        echo "  → /dev/tcp works but nc fails: SELinux label or nc socket option blocked."
    fi
elif [[ ${#PASS[@]} -eq 0 ]] && [[ ${#SKIP[@]} -lt 4 ]]; then
    echo " [FINDING] All tools failed — issue is in the network path."
    echo " Check: diagnostics/check_firewall.sh ${PORT} (on ${HOST})"
    echo "         diagnostics/check_custom_rhel8.sh (on ${HOST})"
    echo "         AWS Security Group inbound rules for port ${PORT}"
else
    echo " [OK] ${HOST}:${PORT} is reachable from this host."
fi
echo "============================================="

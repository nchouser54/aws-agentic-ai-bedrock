#!/usr/bin/env bash
# Full container connectivity verifier (container -> target host/service)
# Run INSIDE the container
# Usage:
#   ./verify_container_full_connectivity.sh <TARGET_HOST_OR_IP> <PORT> [PROTOCOL]
# Examples:
#   ./verify_container_full_connectivity.sh 10.0.1.50 8080 tcp
#   ./verify_container_full_connectivity.sh rhel8.internal 443 https

set -euo pipefail

TARGET="${1:?Usage: $0 <TARGET_HOST_OR_IP> <PORT> [PROTOCOL]}"
PORT="${2:?Usage: $0 <TARGET_HOST_OR_IP> <PORT> [PROTOCOL]}"
PROTOCOL="${3:-tcp}"   # tcp|http|https
TIMEOUT="${TIMEOUT:-5}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

TMPDIR=$(mktemp -d)

log_step() { echo -e "${YELLOW}[*]${NC} $1"; }
log_pass() { echo -e "${GREEN}[✓]${NC} $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
log_fail() { echo -e "${RED}[✗]${NC} $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; WARN_COUNT=$((WARN_COUNT + 1)); }
log_info() { echo -e "${BLUE}[i]${NC} $1"; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }

banner() {
  echo "============================================================"
  echo "Container Full Connectivity Verification"
  echo "============================================================"
  echo "Target     : ${TARGET}"
  echo "Port       : ${PORT}"
  echo "Protocol   : ${PROTOCOL}"
  echo "Timeout    : ${TIMEOUT}s"
  echo "Temp output: ${TMPDIR}"
  echo "============================================================"
  echo
}

check_runtime_context() {
  log_step "Runtime context"
  log_info "Hostname: $(hostname 2>/dev/null || echo unknown)"
  log_info "Kernel  : $(uname -a 2>/dev/null || echo unknown)"

  if [[ -f /.dockerenv ]]; then
    log_pass "Detected Docker container runtime"
  elif grep -qaE 'docker|containerd|kubepods|cri-o|podman' /proc/1/cgroup 2>/dev/null; then
    log_pass "Detected containerized runtime via cgroup"
  else
    log_warn "Container runtime not conclusively detected"
  fi

  if has_cmd ip; then
    ip -4 addr show >"$TMPDIR/ip_addr.txt" 2>&1 || true
    ip route show >"$TMPDIR/ip_route.txt" 2>&1 || true
    log_pass "Captured IP and route tables"
  else
    log_warn "'ip' command not available"
  fi

  echo
}

check_proxy_and_dns() {
  log_step "Proxy and DNS checks"

  local hp np
  hp="${HTTP_PROXY:-${http_proxy:-}}"
  sp="${HTTPS_PROXY:-${https_proxy:-}}"
  np="${NO_PROXY:-${no_proxy:-}}"

  if [[ -n "$hp" || -n "$sp" ]]; then
    log_warn "Proxy environment detected"
    log_info "HTTP_PROXY : ${hp:-<unset>}"
    log_info "HTTPS_PROXY: ${sp:-<unset>}"
    log_info "NO_PROXY   : ${np:-<unset>}"
  else
    log_pass "No proxy environment variables detected"
  fi

  if [[ -f /etc/resolv.conf ]]; then
    cp /etc/resolv.conf "$TMPDIR/resolv.conf" || true
    log_pass "DNS resolver config available (/etc/resolv.conf)"
  else
    log_fail "Missing /etc/resolv.conf"
  fi

  # Resolve target if hostname
  if [[ "$TARGET" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    TARGET_IP="$TARGET"
    log_pass "Target is IPv4 address: $TARGET_IP"
  else
    TARGET_IP=""
    if has_cmd getent; then
      TARGET_IP=$(getent ahostsv4 "$TARGET" 2>/dev/null | awk 'NR==1{print $1}')
    elif has_cmd nslookup; then
      TARGET_IP=$(nslookup "$TARGET" 2>/dev/null | awk '/^Address: /{print $2; exit}')
    fi

    if [[ -n "$TARGET_IP" ]]; then
      log_pass "Resolved ${TARGET} -> ${TARGET_IP}"
    else
      log_fail "Failed to resolve hostname: ${TARGET}"
    fi
  fi

  echo
}

check_icmp_and_route() {
  log_step "L3 route and ICMP checks"

  local dest
  dest="${TARGET_IP:-$TARGET}"

  if has_cmd ip; then
    if ip route get "$dest" >/tmp/route_get.out 2>&1; then
      log_pass "Route to ${dest} exists"
      cat /tmp/route_get.out >>"$TMPDIR/route_get.txt" || true
    else
      log_fail "No route to ${dest}"
      cat /tmp/route_get.out >>"$TMPDIR/route_get.txt" || true
    fi
  else
    log_warn "Cannot verify route with 'ip route get' (missing ip command)"
  fi

  if has_cmd ping; then
    if ping -c 2 -W 2 "$dest" >"$TMPDIR/ping.txt" 2>&1; then
      log_pass "ICMP ping to ${dest} succeeded"
    else
      log_warn "ICMP ping to ${dest} failed (may be blocked by policy)"
    fi
  else
    log_warn "ping not available"
  fi

  echo
}

check_tcp_connectivity() {
  log_step "L4 TCP connectivity checks"

  local dest
  dest="${TARGET_IP:-$TARGET}"

  if has_cmd nc; then
    if nc -z -w "$TIMEOUT" "$dest" "$PORT" >"$TMPDIR/nc.txt" 2>&1; then
      log_pass "TCP connect succeeded (nc) to ${dest}:${PORT}"
    else
      log_fail "TCP connect failed (nc) to ${dest}:${PORT}"
      cat "$TMPDIR/nc.txt" 2>/dev/null | sed 's/^/    /' || true
    fi
  else
    if timeout "$TIMEOUT" bash -c "</dev/tcp/${dest}/${PORT}" >/dev/null 2>&1; then
      log_pass "TCP connect succeeded (/dev/tcp) to ${dest}:${PORT}"
    else
      log_fail "TCP connect failed (/dev/tcp) to ${dest}:${PORT}"
    fi
  fi

  echo
}

check_tls_if_needed() {
  if [[ "$PROTOCOL" != "https" && "$PORT" != "443" ]]; then
    return 0
  fi

  log_step "TLS checks"
  local dest
  dest="${TARGET_IP:-$TARGET}"

  if has_cmd openssl; then
    if timeout "$TIMEOUT" openssl s_client -connect "${dest}:${PORT}" -servername "$TARGET" -brief < /dev/null >"$TMPDIR/openssl.txt" 2>&1; then
      log_pass "TLS handshake succeeded (openssl s_client)"
    else
      log_fail "TLS handshake failed (openssl s_client)"
      tail -n 20 "$TMPDIR/openssl.txt" 2>/dev/null | sed 's/^/    /' || true
    fi
  else
    log_warn "openssl not available; skipping direct TLS handshake"
  fi

  # Java truststore hints for gradle/jvm clients
  if has_cmd java; then
    log_pass "Java runtime detected"
    java -version >"$TMPDIR/java_version.txt" 2>&1 || true

    local java_home
    java_home="${JAVA_HOME:-}"
    if [[ -n "$java_home" && -f "$java_home/lib/security/cacerts" ]]; then
      log_pass "JAVA_HOME truststore present: $java_home/lib/security/cacerts"
    else
      log_warn "JAVA_HOME truststore path not obvious; if Gradle has PKIX errors, verify JVM cacerts"
    fi
  else
    log_warn "Java not found; Gradle TLS verification may not be possible"
  fi

  echo
}

check_http_if_needed() {
  if [[ "$PROTOCOL" != "http" && "$PROTOCOL" != "https" ]]; then
    return 0
  fi

  log_step "L7 HTTP(S) checks"
  local scheme dest url
  dest="${TARGET_IP:-$TARGET}"

  if [[ "$PROTOCOL" == "https" || "$PORT" == "443" ]]; then
    scheme="https"
  else
    scheme="http"
  fi

  url="${scheme}://${dest}:${PORT}/"

  if has_cmd curl; then
    local curl_flags
    curl_flags="--connect-timeout ${TIMEOUT} --max-time $((TIMEOUT * 2)) -sS -o /dev/null -w HTTP:%{http_code} DNS:%{time_namelookup} TCP:%{time_connect} TLS:%{time_appconnect} TTFB:%{time_starttransfer} TOTAL:%{time_total}"

    if [[ "$scheme" == "https" ]]; then
      # strict first
      if eval curl ${curl_flags} "$url" >"$TMPDIR/curl_strict.txt" 2>"$TMPDIR/curl_strict.err"; then
        log_pass "HTTPS request succeeded with certificate validation"
        log_info "$(cat "$TMPDIR/curl_strict.txt")"
      else
        log_fail "HTTPS request failed with certificate validation"
        tail -n 8 "$TMPDIR/curl_strict.err" 2>/dev/null | sed 's/^/    /' || true
        # diagnostic insecure retry
        if eval curl -k ${curl_flags} "$url" >"$TMPDIR/curl_insecure.txt" 2>"$TMPDIR/curl_insecure.err"; then
          log_warn "HTTPS works only with -k (certificate trust problem likely)"
          log_info "$(cat "$TMPDIR/curl_insecure.txt")"
        else
          log_fail "HTTPS still failed with -k (network/server issue likely)"
          tail -n 8 "$TMPDIR/curl_insecure.err" 2>/dev/null | sed 's/^/    /' || true
        fi
      fi
    else
      if eval curl ${curl_flags} "$url" >"$TMPDIR/curl_http.txt" 2>"$TMPDIR/curl_http.err"; then
        log_pass "HTTP request succeeded"
        log_info "$(cat "$TMPDIR/curl_http.txt")"
      else
        log_fail "HTTP request failed"
        tail -n 8 "$TMPDIR/curl_http.err" 2>/dev/null | sed 's/^/    /' || true
      fi
    fi
  else
    log_warn "curl not available; skipping HTTP(S) checks"
  fi

  echo
}

check_gradle_specific() {
  log_step "Gradle/JVM client checks"

  if has_cmd gradle; then
    log_pass "gradle CLI detected"
    gradle --version >"$TMPDIR/gradle_version.txt" 2>&1 || true
  elif [[ -x ./gradlew ]]; then
    log_pass "gradlew wrapper detected in current directory"
    ./gradlew --version >"$TMPDIR/gradlew_version.txt" 2>&1 || true
  else
    log_warn "No gradle/gradlew detected in current directory/PATH"
  fi

  # Common hint for internal hosts bypassing proxies
  local np
  np="${NO_PROXY:-${no_proxy:-}}"
  if [[ -n "$np" ]]; then
    if grep -qE "(^|,)(\*\.)?${TARGET//./\.}(,|$)" <<< "$np"; then
      log_pass "NO_PROXY appears to include target"
    else
      log_warn "NO_PROXY may not include target (${TARGET}); proxy interception can break Gradle"
    fi
  else
    log_warn "NO_PROXY is unset; internal traffic may still route through proxy"
  fi

  echo
}

print_summary() {
  echo "============================================================"
  echo "Summary"
  echo "============================================================"
  echo "Pass : ${PASS_COUNT}"
  echo "Warn : ${WARN_COUNT}"
  echo "Fail : ${FAIL_COUNT}"
  echo "Logs : ${TMPDIR} (preserved for review)"
  echo "============================================================"

  if (( FAIL_COUNT > 0 )); then
    echo
    echo "Most likely next actions:"
    echo "1) If TCP failed: check SG/NACL/firewall/listener on RHEL8"
    echo "2) If HTTPS strict failed but -k worked: import cert chain into JVM truststore"
    echo "3) If only Gradle fails: verify proxy/NO_PROXY and JVM truststore settings"
    return 2
  fi

  if (( WARN_COUNT > 0 )); then
    return 1
  fi

  return 0
}

banner
check_runtime_context
check_proxy_and_dns
check_icmp_and_route
check_tcp_connectivity
check_tls_if_needed
check_http_if_needed
check_gradle_specific
print_summary

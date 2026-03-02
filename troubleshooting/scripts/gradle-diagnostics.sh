#!/usr/bin/env bash
# Gradle/JVM environment diagnostics for network issues
# Run INSIDE container where Gradle runs
# Usage: ./gradle-diagnostics.sh

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_section() { echo ""; echo -e "${BLUE}=== $1 ===${NC}"; }
log_info() { echo -e "${GREEN}[i]${NC} $1"; }

banner() {
  echo "=============================================="
  echo "Gradle/JVM Network Diagnostics"
  echo "=============================================="
  echo ""
}

# Gradle version
log_section "Gradle Version"
if command -v gradle >/dev/null 2>&1; then
  log_info "Gradle CLI found:"
  gradle --version 2>&1 | head -3
elif [[ -x ./gradlew ]]; then
  log_info "Gradle Wrapper (./gradlew) found:"
  ./gradlew --version 2>&1 | grep "Gradle" | head -1 || ./gradlew --version 2>&1 | head -1
else
  echo "⚠ No gradle/gradlew found in PATH or current dir"
fi

# Java info
log_section "Java Runtime"
if command -v java >/dev/null 2>&1; then
  java -version 2>&1
  echo ""
  log_info "JAVA_HOME: ${JAVA_HOME:-<not set>}"
else
  echo "⚠ Java not found"
fi

# Java truststore
log_section "Java Truststore (Certificate Authority Store)"
if [[ -n "${JAVA_HOME:-}" && -f "$JAVA_HOME/lib/security/cacerts" ]]; then
  log_info "Found JVM cacerts at: $JAVA_HOME/lib/security/cacerts"
  if command -v keytool >/dev/null 2>&1; then
    CERT_COUNT=$(keytool -list -keystore "$JAVA_HOME/lib/security/cacerts" -storepass changeit 2>/dev/null | grep -c "TrustedCertEntry" || echo "unknown")
    log_info "Trusted certificates in store: $CERT_COUNT"
  fi
else
  echo "⚠ JVM cacerts not found at default location"
fi

# Proxy environment
log_section "Proxy Environment Variables"
HP="${HTTP_PROXY:-${http_proxy:-<unset>}}"
SP="${HTTPS_PROXY:-${https_proxy:-<unset>}}"
NP="${NO_PROXY:-${no_proxy:-<unset>}}"
FP="${FTP_PROXY:-${ftp_proxy:-<unset>}}"

log_info "HTTP_PROXY  : $HP"
log_info "HTTPS_PROXY : $SP"
log_info "NO_PROXY    : $NP"
log_info "FTP_PROXY   : $FP"

# Gradle JVM args
log_section "Gradle JVM Arguments (check proxy/truststore settings)"
if [[ -f "$HOME/.gradle/gradle.properties" ]]; then
  log_info "Found ~/.gradle/gradle.properties:"
  cat "$HOME/.gradle/gradle.properties" | grep -iE "proxy|ssl|tls|trust|jvm" || echo "  (no proxy/TLS settings found)"
else
  echo "  No ~/.gradle/gradle.properties"
fi

if [[ -f gradle.properties ]]; then
  log_info "Found ./gradle.properties:"
  cat gradle.properties | grep -iE "proxy|ssl|tls|trust|jvm" || echo "  (no proxy/TLS settings found)"
else
  echo "  No ./gradle.properties in current dir"
fi

# JVM system properties that Gradle uses
log_section "Helpful JVM Flags for Gradle"
cat << 'EOF'
If Gradle fails with TLS/cert errors, try:
  gradle --info -Djavax.net.debug=ssl:handshake ...  (verbose TLS debug)
  gradle -DsystemProp.https.protocols=TLSv1.2 ...    (force TLS 1.2)
  gradle -DsystemProp.sun.security.ssl.allowUnsafeRenegotiation=true ...  (if renegotiation blocked)

For proxy bypass (direct RHEL8 connection):
  gradle -Dhttp.nonProxyHosts=10.0* -Dhttps.nonProxyHosts=10.0* ...
  OR:  NO_PROXY=10.0.0.0/8 gradle ...

For certificate trust issues:
  gradle -Djavax.net.ssl.trustStore=/path/to/cacerts -Djavax.net.ssl.trustStorePassword=changeit ...
EOF

# Network diagnostics
log_section "Container Network"
if command -v ip >/dev/null 2>&1; then
  echo "Network interfaces:"
  ip -4 addr show 2>/dev/null | grep -E "^\d|inet " | head -10 || true
  echo ""
  echo "Routing:"
  ip route show 2>/dev/null | head -5 || true
else
  echo "⚠ 'ip' command not available"
fi

# DNS
log_section "DNS Resolution"
if [[ -f /etc/resolv.conf ]]; then
  echo "Nameservers:"
  grep "^nameserver" /etc/resolv.conf || echo "  (none configured)"
else
  echo "⚠ /etc/resolv.conf not found"
fi

# Gradle wrapper properties
log_section "Gradle Wrapper Config"
if [[ -f gradle/wrapper/gradle-wrapper.properties ]]; then
  echo "gradle/wrapper/gradle-wrapper.properties:"
  cat gradle/wrapper/gradle-wrapper.properties
else
  echo "⚠ gradle/wrapper/gradle-wrapper.properties not found"
fi

# JVM memory
log_section "JVM Memory Settings"
if [[ -f gradle.properties ]]; then
  grep -iE "memory|jvmargs|org.gradle.jvmargs" gradle.properties || echo "  (using defaults)"
else
  echo "  (using defaults)"
fi

echo ""
echo "=============================================="
echo "End Gradle/JVM Diagnostics"
echo "=============================================="

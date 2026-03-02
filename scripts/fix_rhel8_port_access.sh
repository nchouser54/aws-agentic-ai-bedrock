#!/usr/bin/env bash
# RHEL8 SELinux + Firewall Quick Fixer
# Run on RHEL8 to quickly identify and fix common issues
# Usage: ./fix_rhel8_port_access.sh <PORT> [SERVICE_NAME] [--fix]

set -euo pipefail

PORT="${1:?Usage: $0 <PORT> [SERVICE_NAME] [--fix]}"
SERVICE_NAME="${2:-unknown}"
AUTO_FIX="${3:---check}"  # --fix to auto-apply fixes

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_step() { echo -e "${YELLOW}[*]${NC} $1"; }
log_pass() { echo -e "${GREEN}[✓]${NC} $1"; }
log_fail() { echo -e "${RED}[✗]${NC} $1"; }
log_info() { echo -e "${BLUE}[i]${NC} $1"; }

echo "========================================="
echo "RHEL8 Port Access Fixer"
echo "========================================="
echo "Port: ${PORT}"
echo "Service: ${SERVICE_NAME}"
echo "Mode: ${AUTO_FIX}"
echo ""

# Verify running as root
if [ "$EUID" -ne 0 ]; then
  log_fail "This script must run as root"
  log_info "Re-run with: sudo $0 $PORT $SERVICE_NAME $AUTO_FIX"
  exit 1
fi

log_pass "Running as root"
echo ""

# ============================================================
# FIREWALLD FIXES
# ============================================================

log_step "Checking firewalld..."
echo ""

if systemctl is-active --quiet firewalld; then
  log_pass "firewalld is active"
  echo ""
  
  # Check if port already allowed
  if firewall-cmd --query-port="${PORT}/tcp" &>/dev/null 2>&1; then
    log_pass "Port ${PORT}/tcp is already allowed in firewalld"
  else
    log_fail "Port ${PORT}/tcp is NOT allowed in firewalld"
    
    if [ "$AUTO_FIX" == "--fix" ]; then
      log_info "Adding port ${PORT}/tcp to firewalld..."
      firewall-cmd --permanent --add-port="${PORT}/tcp"
      firewall-cmd --reload
      log_pass "Port ${PORT}/tcp added and firewalld reloaded"
    else
      echo "  Fix with:"
      echo "    sudo firewall-cmd --permanent --add-port=${PORT}/tcp"
      echo "    sudo firewall-cmd --reload"
    fi
  fi
  
  # Check UDP if port 53
  if [ "$PORT" == "53" ]; then
    if ! firewall-cmd --query-port="${PORT}/udp" &>/dev/null 2>&1; then
      log_fail "Port ${PORT}/udp NOT allowed (needed for DNS)"
      if [ "$AUTO_FIX" == "--fix" ]; then
        firewall-cmd --permanent --add-port="${PORT}/udp"
        firewall-cmd --reload
        log_pass "Port ${PORT}/udp added"
      fi
    fi
  fi
else
  log_info "firewalld not running (using iptables only)"
fi

echo ""

# ============================================================
# SELINUX FIXES
# ============================================================

log_step "Checking SELinux..."
echo ""

if command -v getenforce &>/dev/null; then
  SE_STATUS=$(getenforce 2>/dev/null || echo "Disabled")
  
  if [ "$SE_STATUS" == "Disabled" ]; then
    log_pass "SELinux is disabled"
  else
    log_fail "SELinux is ${SE_STATUS} (may block port ${PORT})"
    echo ""
    
    if [ "$SE_STATUS" == "Enforcing" ]; then
      log_info "Checking SELinux policy for port ${PORT}..."
      
      if command -v semanage &>/dev/null; then
        # Determine common port types
        PORT_TYPE=""
        case "$SERVICE_NAME" in
          http|apache|httpd|nginx) PORT_TYPE="http_port_t" ;;
          https) PORT_TYPE="http_port_t" ;;
          ssh) PORT_TYPE="ssh_port_t" ;;
          ftp) PORT_TYPE="ftp_port_t" ;;
          smtp|mail) PORT_TYPE="smtp_port_t" ;;
          dns|named) PORT_TYPE="dns_port_t" ;;
          postgresql|postgres) PORT_TYPE="postgresql_port_t" ;;
          mysql) PORT_TYPE="mysqld_port_t" ;;
          mongodb) PORT_TYPE="mongod_port_t" ;;
          redis) PORT_TYPE="redis_port_t" ;;
          *)
            # Try common web ports
            if [ "$PORT" == "8080" ] || [ "$PORT" == "8000" ] || [ "$PORT" == "3000" ]; then
              PORT_TYPE="http_port_t"
            fi
          ;;
        esac
        
        # Check if port already in policy
        if semanage port -l | grep -q "${PORT}"; then
          log_pass "Port ${PORT} already in SELinux policy"
          semanage port -l | grep "${PORT}"
        else
          if [ -z "$PORT_TYPE" ]; then
            log_fail "Port ${PORT} not in SELinux policy and service type unknown"
            echo "  Check available port types:"
            echo "    semanage port -l | head -20"
            echo ""
            echo "  Or guess the type based on service and add manually:"
            echo "    semanage port -a -t <type> -p tcp ${PORT}"
          else
            log_fail "Port ${PORT} not in SELinux policy as ${PORT_TYPE}"
            
            if [ "$AUTO_FIX" == "--fix" ]; then
              log_info "Adding port ${PORT} as ${PORT_TYPE}..."
              semanage port -a -t "${PORT_TYPE}" -p tcp "${PORT}"
              log_pass "Port ${PORT} added to SELinux policy as ${PORT_TYPE}"
            else
              echo "  Fix with:"
              echo "    sudo semanage port -a -t ${PORT_TYPE} -p tcp ${PORT}"
            fi
          fi
        fi
      else
        log_fail "semanage not installed, cannot check SELinux port policy"
        echo "  Install with: sudo yum install -y policycoreutils-python-utils"
      fi
    else
      log_info "SELinux is in ${SE_STATUS} mode (permissive), won't block traffic"
    fi
  fi
else
  log_pass "SELinux tools not available"
fi

echo ""

# ============================================================
# SERVICE STATUS
# ============================================================

if [ "$SERVICE_NAME" != "unknown" ]; then
  log_step "Checking service: ${SERVICE_NAME}"
  echo ""
  
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    log_pass "Service ${SERVICE_NAME} is running"
    systemctl status "${SERVICE_NAME}" --no-pager || true
  else
    log_fail "Service ${SERVICE_NAME} is NOT running"
    
    if [ "$AUTO_FIX" == "--fix" ]; then
      log_info "Starting ${SERVICE_NAME}..."
      systemctl start "${SERVICE_NAME}"
      systemctl enable "${SERVICE_NAME}"
      log_pass "Service ${SERVICE_NAME} started and enabled"
    else
      echo "  Start with: sudo systemctl start ${SERVICE_NAME}"
      echo "  Enable on boot: sudo systemctl enable ${SERVICE_NAME}"
    fi
  fi
  
  echo ""
fi

# ============================================================
# VERIFICATION
# ============================================================

log_step "Verifying port is accessible..."
echo ""

if timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/${PORT}" 2>/dev/null; then
  log_pass "Port ${PORT} is now accepting localhost connections!"
else
  log_fail "Port ${PORT} still not accepting connections"
  echo ""
  echo "  Additional diagnostics:"
  echo "    ss -tlnp | grep ${PORT}"
  echo "    lsof -i :${PORT}"
  echo "    journalctl -u ${SERVICE_NAME} -n 20"
fi

echo ""

# ============================================================
# SUMMARY
# ============================================================

echo "========================================="
echo "SUMMARY"
echo "========================================="
echo ""
if [ "$AUTO_FIX" != "--fix" ]; then
  echo "To automatically apply fixes, re-run with: --fix"
  echo ""
fi
echo "Verify with:"
echo "  • From container/RHEL9:"
echo "    bash test_container_rhel_connectivity.sh <RHEL8_IP> ${PORT}"
echo ""
echo "  • From RHEL8:"
echo "    ss -tlnp | grep ${PORT}"
echo "    firewall-cmd --list-ports | grep ${PORT}"
echo "    sudo semanage port -l | grep ${PORT}"
echo ""

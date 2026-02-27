#!/usr/bin/env bash
# check_podman_config.sh - Inspect all Podman networking config relevant to
# external connectivity. Run this on the RHEL9 EC2 that runs the container.
#
# Usage: ./check_podman_config.sh [CONTAINER_NAME_OR_ID]
#   CONTAINER_NAME_OR_ID  Optional: narrow checks to a specific container

set -uo pipefail

CONTAINER="${1:-}"
SUDO=""; [[ "${EUID}" -ne 0 ]] && SUDO="sudo"

echo "============================================="
echo " PODMAN NETWORK CONFIGURATION CHECK"
echo "============================================="
echo " Host     : $(hostname) / $(hostname -I | awk '{print $1}')"
echo " OS       : $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')"
echo " Kernel   : $(uname -r)"
echo " Podman   : $(podman --version)"
echo " User     : $(id)"
echo " Time     : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================="
echo ""

# ---------- Podman info ----------
echo "── Podman system info ──────────────────────"
podman info --format json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
host = d.get('host', {})
print(f\"  Network backend : {d.get('plugins', {}).get('network', 'unknown')}\")
print(f\"  CGroup manager  : {host.get('cgroupManager', 'unknown')}\")
print(f\"  rootless        : {host.get('security', {}).get('rootless', 'unknown')}\")
" 2>/dev/null || podman info | grep -E 'network|rootless|cgroupManager' | sed 's/^/  /'

echo ""

# ---------- Running containers ----------
echo "── Running containers ──────────────────────"
if [[ -n "${CONTAINER}" ]]; then
    podman ps --filter "name=${CONTAINER}" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || \
    podman ps | grep "${CONTAINER}"
else
    podman ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || podman ps
fi

echo ""

# ---------- Port mappings ----------
echo "── Port mappings ───────────────────────────"
if [[ -n "${CONTAINER}" ]]; then
    echo "  Container: ${CONTAINER}"
    podman port "${CONTAINER}" 2>/dev/null | sed 's/^/    /' || echo "  [WARN] Could not get ports for ${CONTAINER}"
else
    for cname in $(podman ps --format '{{.Names}}' 2>/dev/null); do
        echo "  Container: ${cname}"
        podman port "${cname}" 2>/dev/null | sed 's/^/    /' || echo "    (no ports)"
    done
fi

echo ""

# ---------- Network list ----------
echo "── Podman networks ─────────────────────────"
podman network ls 2>/dev/null | sed 's/^/  /'

echo ""

# ---------- Network inspect ----------
echo "── Network inspect (all) ───────────────────"
for netname in $(podman network ls --format '{{.Name}}' 2>/dev/null); do
    echo "  --- Network: ${netname} ---"
    podman network inspect "${netname}" 2>/dev/null | python3 -c "
import json, sys
nets = json.load(sys.stdin)
for n in nets:
    print(f\"    driver    : {n.get('driver', 'unknown')}\")
    print(f\"    dns_enabled: {n.get('dns_enabled', 'unknown')}\")
    for sub in n.get('subnets', []):
        print(f\"    subnet    : {sub.get('subnet', '')}\")
        print(f\"    gateway   : {sub.get('gateway', '')}\")
" 2>/dev/null || echo "  (parse error)"
done

echo ""

# ---------- Rootless check ----------
echo "── Rootless / slirp4netns / pasta ──────────"
if id | grep -qv 'uid=0'; then
    echo "  [WARN] Running as non-root. Rootless Podman uses slirp4netns or pasta."
    echo "         External ports are proxied through the host userspace, which"
    echo "         means they may NOT show in 'ss -tlnp' but still work."
    echo "  Check: podman info | grep -i 'network\|slirp'"
    if pgrep -x slirp4netns &>/dev/null; then
        echo "  [INFO] slirp4netns process is running."
    fi
    if pgrep -x pasta &>/dev/null; then
        echo "  [INFO] pasta (passt) process is running."
    fi
else
    echo "  [INFO] Running as root. Podman uses kernel-level network namespaces."
    echo "         Ports WILL appear in 'ss -tlnp'."
fi

echo ""

# ---------- Host port listen check ----------
echo "── Host listening ports (ss) ───────────────"
if [[ -n "${CONTAINER}" ]]; then
    PORTS_RAW=$(podman port "${CONTAINER}" 2>/dev/null | awk -F'[ :]' '{print $(NF)}')
    for p in ${PORTS_RAW}; do
        printf "  Port %-6s : " "${p}"
        if ss -tlnp 2>/dev/null | grep -q ":${p}"; then
            echo "LISTENING (visible to kernel)"
            ss -tlnp | grep ":${p}" | sed 's/^/    /'
        else
            echo "not in ss (may be proxied via rootless Podman)"
        fi
    done
else
    echo "  (specify a container name for targeted port check)"
    ss -tlnp 2>/dev/null | grep -E 'LISTEN|State' | head -20 | sed 's/^/  /'
fi

echo ""
echo "── Kernel IP forwarding ────────────────────"
FWD=$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null || echo "unknown")
echo "  ip_forward : ${FWD}"
if [[ "${FWD}" != "1" ]]; then
    echo "  [WARN] IP forwarding is disabled! Podman container traffic cannot route."
    echo "  Fix:   echo 1 > /proc/sys/net/ipv4/ip_forward"
    echo "         sysctl -w net.ipv4.ip_forward=1"
fi

echo ""

# ---------- aardvark-dns (Podman 4+ DNS backend) ----------
echo "── aardvark-dns (Podman 4+ DNS backend) ────"
echo "  [INFO] Podman 4+ uses aardvark-dns for container DNS. If it crashes,"
echo "         containers cannot resolve hostnames — connectivity appears broken."
if command -v aardvark-dns &>/dev/null; then
    echo "  aardvark-dns path: $(which aardvark-dns)"
    echo "  version          : $(aardvark-dns --version 2>/dev/null || echo 'N/A')"
fi
AARDVARK_PID=$(pgrep -x aardvark-dns 2>/dev/null || true)
if [[ -n "${AARDVARK_PID}" ]]; then
    echo "  [OK ] aardvark-dns is running (pid: ${AARDVARK_PID})"
else
    echo "  [WARN] aardvark-dns process not found."
    echo "         If Podman uses Netavark (RHEL9+), missing aardvark-dns breaks container DNS."
    echo "  Check: podman info | grep -i dns"
fi
# Check for aardvark-dns socket/state files
for f in /run/containers/networks/aardvark-dns /run/netavark/aardvark-dns.sock; do
    [[ -e "${f}" ]] && echo "  State : ${f}" && ls -la "${f}" 2>/dev/null
done

echo ""

# ---------- CNI plugins check (older Podman / RHEL8) ----------
echo "── CNI plugins (older Podman / RHEL8) ──────"
PODMAN_VER_NUM=$(podman --version 2>/dev/null | grep -oP '[\d]+\.[\d]+' | head -1 || echo "0.0")
MAJOR=$(echo "${PODMAN_VER_NUM}" | cut -d. -f1)
if [[ "${MAJOR}" -lt 4 ]] 2>/dev/null; then
    echo "  [INFO] Podman < 4 detected. Uses CNI plugins instead of Netavark."
    CNI_PATHS=(
        "/usr/lib/cni"
        "/opt/cni/bin"
        "/usr/libexec/cni"
    )
    CNI_FOUND=false
    for d in "${CNI_PATHS[@]}"; do
        if [[ -d "${d}" ]]; then
            echo "  CNI dir: ${d}"
            ls "${d}" 2>/dev/null | sed 's/^/    /'
            CNI_FOUND=true
        fi
    done
    if [[ "${CNI_FOUND}" == "false" ]]; then
        echo "  [WARN] No CNI plugin directory found."
        echo "  Fix:   dnf install containernetworking-plugins"
    fi
    # Check bridge plugin specifically
    BRIDGE_PLUGIN=$(find /usr/lib/cni /opt/cni/bin /usr/libexec/cni 2>/dev/null -name 'bridge' | head -1 || true)
    if [[ -z "${BRIDGE_PLUGIN}" ]]; then
        echo "  [CRITICAL] CNI bridge plugin NOT found — Podman networking will fail."
    else
        echo "  [OK ] CNI bridge plugin: ${BRIDGE_PLUGIN}"
    fi
else
    echo "  [INFO] Podman ${PODMAN_VER_NUM} uses Netavark (CNI not required)."
fi

echo ""

# ---------- Docker daemon conflict ----------
echo "── Docker daemon conflict check ─────────────"
echo "  [INFO] Docker daemon modifies iptables/nftables rules independently."
echo "         If Docker runs alongside Podman, rules can conflict and drop container traffic."
if systemctl is-active --quiet docker 2>/dev/null; then
    echo "  [WARN] Docker daemon IS running on this host!"
    echo "         Docker-managed iptables rules (DOCKER chains) may interfere with Podman."
    echo "         Docker bridge IP range:"
    docker network inspect bridge 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
for n in d:
    for s in n.get('IPAM',{}).get('Config',[]):
        print(f\"    Subnet: {s.get('Subnet','?')} Gateway: {s.get('Gateway','?')}\")
" 2>/dev/null || true
    echo ""
    echo "  Potential fixes:"
    echo "    1. Stop Docker:  systemctl stop docker && systemctl disable docker"
    echo "    2. Or configure Docker to NOT manage iptables:"
    echo "       Add to /etc/docker/daemon.json: {\"iptables\": false}"
    echo "       Then: systemctl restart docker"
    echo "  Check Docker chains: iptables -L -n | grep -E 'DOCKER'"
    DOCKER_CHAINS=$(${SUDO} iptables -L -n 2>/dev/null | grep 'Chain DOCKER' || true)
    [[ -n "${DOCKER_CHAINS}" ]] && echo "${DOCKER_CHAINS}" | sed 's/^/    /'
elif command -v docker &>/dev/null; then
    echo "  [INFO] Docker CLI installed but daemon not running — no conflict."
else
    echo "  [OK ] Docker not installed — no conflict risk."
fi

echo ""
echo "============================================="
echo " Done. Review any [WARN] items above."
echo "============================================="

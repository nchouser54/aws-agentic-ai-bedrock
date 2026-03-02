# Troubleshooting Scripts Index

**Consolidated EC2 connectivity diagnostic scripts** — all in one place for easy access and maintenance.

## 📋 Scripts Overview

All scripts are located in `troubleshooting/scripts/` and are executable from your laptop, EC2 instances, or containers.

---

## 🚀 **Gradle/Container Connectivity Issue? Start Here**

If your **container's Gradle process can't connect to RHEL8**, run these in order:

```bash
# 1. Quick yes/no on network reachability (30 seconds)
./container-quick-check.sh <RHEL8_IP> 443

# 2. Dump all Gradle/Java/Proxy settings
./gradle-diagnostics.sh

# 3. Full connectivity sweep if above don't explain it
./verify_container_full_connectivity.sh <RHEL8_IP> 443 https
```

### Common Gradle Failures & Fixes

| Error | Likely Cause | Fix |
|-------|------|-----|
| `Connection timed out` | Network/firewall/port not listening | Run `container-quick-check.sh`, then `diagnose_rhel8_listener.sh` on RHEL8 |
| `PKIX path building failed` | Cert not in JVM truststore | Run `gradle-diagnostics.sh`, check Java section |
| `407 Proxy Authentication Required` | Proxy intercepting internal traffic | Run `gradle-diagnostics.sh`, check NO_PROXY for internal subnet (e.g., 10.0.0.0/8) |
| `Connection refused` | Service not listening or bound to 127.0.0.1 | SSH to RHEL8, run `diagnose_rhel8_listener.sh <PORT>` |

### 🔧 Quick Fixes for Gradle

**If network is reachable but TLS fails:**
```bash
# Add to gradle.properties or run gradle with:
gradle -DsystemProp.https.protocols=TLSv1.2 yourTask
```

**If proxy is intercepting internal traffic:**
```bash
export NO_PROXY=10.0.0.0/8
gradle yourTask
```

**For certificate trust issues:**
```bash
gradle -Djavax.net.ssl.trustStore=$JAVA_HOME/lib/security/cacerts -Djavax.net.ssl.trustStorePassword=changeit yourTask
```

---

### 1. **verify_vpc_connectivity.sh** (AWS Layer)
**What it does:** Validates AWS infrastructure configuration for same-subnet EC2 connectivity.

**Run from:** Your laptop (requires AWS CLI configured)

**Usage:**
```bash
./scripts/verify_vpc_connectivity.sh <instance-id-1> <instance-id-2> --region us-gov-west-1
```

**Checks:**
- ✓ Both instances running and in same VPC/subnet
- ✓ Security group ingress rules allow traffic
- ✓ Security group egress rules allow traffic
- ✓ Network ACLs don't block traffic
- ✓ Route tables configured correctly
- ✓ ENI (Elastic Network Interface) status
- ✓ Instance types and IP assignments

**What to do if it fails:**
- Fix AWS security group rules
- Update NACL rules
- Verify route tables
- Ensure instances are in same subnet (or add route table entry if different subnets)

**Output:** Detailed JSON and summary of AWS layer configuration

---

### 2. **verify_instance_networking.sh** (Instance Layer)
**What it does:** Validates instance-level networking and local firewall configuration.

**Run from:** SSH session on RHEL8 or RHEL9 instance

**Usage:**
```bash
# On RHEL8:
./verify_instance_networking.sh <my-ip> <target-ip> 8080

# Example:
./verify_instance_networking.sh 10.0.1.50 10.0.1.100 8080
```

**Checks:**
- ✓ IP addresses assigned to interfaces
- ✓ Network interfaces UP and configured
- ✓ Routing to target instance
- ✓ ARP entries
- ✓ ICMP (ping) reachability
- ✓ TCP port connectivity
- ✓ Firewalld rules and active zones
- ✓ iptables rules (no unexpected DROPs/REJECTs)
- ✓ SELinux status and policy
- ✓ Service listening on port
- ✓ MTU configuration

**What to do if it fails:**
- Enable/fix firewalld rules
- Add port to SELinux policy
- Start service if not listening
- Fix routes if destination unreachable

**Output:** Step-by-step verification with pass/fail for each layer

---

### 3. **diagnose_rhel8_listener.sh** (RHEL8 Deep-Dive)
**What it does:** Deep diagnostic for RHEL8-specific port listening and firewall issues.

**Run from:** SSH session on RHEL8 (non-root, but some checks need sudo)

**Usage:**
```bash
./diagnose_rhel8_listener.sh 8080 myservice
```

**Checks:**
- ✓ Which process is listening on port
- ✓ PID and command details
- ✓ Firewalld status and rules
- ✓ Port in firewalld allowed list
- ✓ iptables rules (check for REJECT/DROP)
- ✓ SELinux mode and policy
- ✓ Port context in SELinux policy
- ✓ Bind address (localhost vs 0.0.0.0)
- ✓ Service status and logs
- ✓ Recent SELinux denials
- ✓ Active connections on port

**What to do if it fails:**
- Service not listening → Start service
- Port not in firewalld → Run fix_rhel8_port_access.sh
- Port not in SELinux policy → Run fix_rhel8_port_access.sh
- SELinux denials → Check audit logs, fix policy

**Output:** Diagnostic summary with recommended fixes

---

### 4. **fix_rhel8_port_access.sh** (Auto-Fix Script)
**What it does:** Automatically fixes common RHEL8 port access issues (firewalld, SELinux).

**Run from:** SSH session on RHEL8 with sudo access

**Usage:**
```bash
# Dry-run (see what would be fixed):
sudo ./fix_rhel8_port_access.sh 8080 myservice

# Actually apply fixes:
sudo ./fix_rhel8_port_access.sh 8080 myservice --fix
```

**Fixes:**
- ✓ Add port to firewalld (if needed)
- ✓ Add port to SELinux policy (if Enforcing)
- ✓ Start and enable service (if provided)
- ✓ Reload firewalld for changes to take effect

**Dry-run mode:** Shows what would be fixed without making changes

**Apply mode:** Actually implements the fixes

**Output:** Confirms which fixes were applied

---

### 5. **test_container_rhel_connectivity.sh** (Container-to-RHEL)
**What it does:** Quick connectivity test from container to RHEL8 instance.

**Run from:** Inside container or pod

**Usage:**
```bash
./test_container_rhel_connectivity.sh 10.0.1.50 8080 myservice
```

**Checks:**
- ✓ ICMP (ping) reachability
- ✓ TCP port open (using nc or /dev/tcp)
- ✓ HTTP response (curl if available)
- ✓ Container firewall status
- ✓ Container SELinux status
- ✓ Container DNS resolution
- ✓ Network namespace info

**What to do if it fails:**
- ICMP fails → AWS NACL/SG blocking ICMP
- TCP fails → Service not listening or local firewall blocking
- HTTP fails → Service not HTTP-capable

**Output:** Quick pass/fail summary with troubleshooting hints

---

### 6. **test_rhel_connectivity_advanced.sh** (Advanced Diagnostics)
**What it does:** Multi-layer connectivity test with packet capture and detailed diagnostics.

**Run from:** RHEL8/RHEL9 instance (use sudo for tcpdump)

**Usage:**
```bash
./test_rhel_connectivity_advanced.sh 10.0.1.50 8080 tcp
./test_rhel_connectivity_advanced.sh 10.0.1.50 80 http
```

**Checks:**
- ✓ System information and timestamps
- ✓ IP configuration and interfaces
- ✓ ARP cache and entries
- ✓ Routing to target
- ✓ DNS resolution (if hostname used)
- ✓ ICMP reachability (5 pings)
- ✓ TCP connection test
- ✓ Port scanning (common ports)
- ✓ Traceroute to target (if available)
- ✓ Firewall status (firewalld/iptables)
- ✓ Interface statistics
- ✓ Packet capture with tcpdump (saves to /tmp/)
- ✓ Service discovery

**Outputs:** All results saved to `/tmp/rhel-connectivity-test-<timestamp>/`
- `ping.txt` — ICMP test results
- `tcp-test.txt` — TCP connection test
- `port-scan.txt` — Port scanning results
- `traceroute.txt` — Route tracing
- `routes.txt` — Kernel routing table
- `traffic.pcap` — Packet capture (needs tcpdump)
- `summary.txt` — Test summary and recommendations

**What to do if it fails:**
- Review individual output files
- Analyze packet capture with: `tcpdump -r traffic.pcap -vv`
- Check port-scan results to see what's listening
- Review traceroute for routing issues

**Output:** Organized directory with detailed reports

---

### 7. **container-quick-check.sh** (Fast Container Reachability)
**What it does:** Ultra-fast 30-second YES/NO check: can container reach RHEL8?

**Run from:** Inside container (Docker/K8s/podman)

**Usage:**
```bash
./container-quick-check.sh <RHEL8_IP> 443
./container-quick-check.sh <RHEL8_IP> 8080
```

**Exit codes:**
- `0` = SUCCESS (RHEL8 is reachable)
- `1` = FAILED (network path broken)
- `2` = PARTIAL (warnings; may still work)

**Checks:**
- ✓ TCP connectivity via `/dev/tcp`
- ✓ TCP connectivity via `nc` (if available)
- ✓ DNS resolution (if hostname given)

**What to do if it fails:**
- Exit 1 (FAILED) → RHEL8 listener/firewall/SG problem
- Exit 2 (PARTIAL) → May be network-layer issue

**Output:** Single-line result + exit code (great for scripts/CI)

---

### 8. **gradle-diagnostics.sh** (Gradle/JVM Environment)
**What it does:** Dumps all Gradle/Java/Proxy settings that affect network connectivity.

**Run from:** Inside container where Gradle runs

**Usage:**
```bash
./gradle-diagnostics.sh
```

**Shows:**
- ✓ Gradle and wrapper version
- ✓ Java runtime version and JAVA_HOME
- ✓ JVM truststore (cacerts) location and certificate count
- ✓ Proxy environment (HTTP_PROXY, HTTPS_PROXY, NO_PROXY, FTP_PROXY)
- ✓ Gradle properties file settings (~/.gradle/gradle.properties, ./gradle.properties)
- ✓ Helpful JVM flags for TLS debugging
- ✓ Container network interfaces and routing
- ✓ DNS configuration
- ✓ Gradle wrapper config
- ✓ JVM memory settings

**What to do if it fails/shows problems:**
- No Gradle found? Install or check PATH
- Proxy set but NO_PROXY empty? Add internal subnet (e.g., `NO_PROXY=10.0.0.0/8`)
- TLS warnings? Export: `export HTTPS_PROXY=""` or add flags shown in output
- Truststore issues? Add `-Djavax.net.ssl.trustStore=...` to Gradle command

**Output:** Formatted diagnostics with recommended fixes

---

### 9. **verify_container_full_connectivity.sh** (Full Container Sweep)
**What it does:** Comprehensive container → RHEL8 connectivity test (network + TLS + HTTP + Gradle checks).

**Run from:** Inside container

**Usage:**
```bash
./verify_container_full_connectivity.sh <RHEL8_IP> 443 https
./verify_container_full_connectivity.sh <RHEL8_IP> 8080 tcp
```

**Includes:**
- Container runtime detection (Docker/K8s/podman)
- Proxy config review
- DNS resolution
- Route discovery
- ICMP ping test
- TCP connectivity
- TLS handshake (openssl s_client)
- HTTP(S) request test (curl strict + insecure fallback)
- Gradle/JVM hints
- Summary with pass/warn/fail counts

**Output:** Detailed logs in temp directory + exit code (0=pass, 1=partial, 2=fail)

---

## 🎯 Quick Reference

| Issue | Try This Script First |
|-------|----------------------|
| Can't ping RHEL8 from RHEL9 | `verify_vpc_connectivity.sh` |
| Ping works but port is blocked | `verify_instance_networking.sh` |
| Port 8080 not responding | `diagnose_rhel8_listener.sh` |
| Need to open port in RHEL8 | `fix_rhel8_port_access.sh --fix` |
| Container can't reach RHEL8 | `container-quick-check.sh` (first) |
| Gradle fails in container | `gradle-diagnostics.sh` (first) |
| Need detailed diagnostics | `test_rhel_connectivity_advanced.sh` or `verify_container_full_connectivity.sh` |

---

## 🚀 Typical Troubleshooting Flow

1. **Check AWS layer:**
   ```bash
   ./scripts/verify_vpc_connectivity.sh i-abc i-xyz --region us-gov-west-1
   ```

2. **SSH to RHEL8 and check local networking:**
   ```bash
   ./verify_instance_networking.sh 10.0.1.50 10.0.1.100 8080
   ```

3. **If port not listening, diagnose RHEL8:**
   ```bash
   ./diagnose_rhel8_listener.sh 8080 myservice
   ```

4. **Auto-fix if needed:**
   ```bash
   sudo ./fix_rhel8_port_access.sh 8080 myservice --fix
   ```

5. **Test from RHEL9:**
   ```bash
   ./verify_instance_networking.sh 10.0.1.100 10.0.1.50 8080
   ```

6. **If still failing, deep-dive diagnostics:**
   ```bash
   sudo ./test_rhel_connectivity_advanced.sh 10.0.1.50 8080 tcp
   ```

---

## 📂 Accessing Scripts

From your laptop:
```bash
cd aws-agentic-ai-pr-reviewer/troubleshooting/scripts/
./verify_vpc_connectivity.sh ...
```

From RHEL instance (via SSH):
```bash
scp -r ../troubleshooting/scripts/ ec2-user@rhel8:/tmp/
ssh ec2-user@rhel8
cd /tmp/scripts
./verify_instance_networking.sh ...
```

Or clone the repo on the instance:
```bash
git clone <repo-url>
cd aws-agentic-ai-pr-reviewer/troubleshooting/scripts/
./verify_instance_networking.sh ...
```

---

## 🔄 Consolidation History

**Consolidated on March 2, 2026:**
- All 6 connectivity scripts were previously duplicated in `/scripts/` and `/troubleshooting/scripts/`
- Consolidated to single source of truth in `/troubleshooting/scripts/`
- Removed duplicates from `/scripts/`
- Enhanced with this documentation

**Why the change?**
- Single location for all EC2 connectivity diagnostics
- Easier maintenance
- Clear documentation of each script's purpose
- Organized troubleshooting workflow

---

**Last Updated:** March 2, 2026

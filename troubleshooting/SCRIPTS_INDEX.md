# Troubleshooting Scripts Index

**Consolidated EC2 connectivity diagnostic scripts** — all in one place for easy access and maintenance.

## 📋 Scripts Overview

All scripts are located in `troubleshooting/scripts/` and are executable from your laptop, EC2 instances, or containers.

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

## 🎯 Quick Reference

| Issue | Try This Script First |
|-------|----------------------|
| Can't ping RHEL8 from RHEL9 | `verify_vpc_connectivity.sh` |
| Ping works but port is blocked | `verify_instance_networking.sh` |
| Port 8080 not responding | `diagnose_rhel8_listener.sh` |
| Need to open port in RHEL8 | `fix_rhel8_port_access.sh --fix` |
| Container can't reach RHEL8 | `test_container_rhel_connectivity.sh` |
| Need detailed diagnostics | `test_rhel_connectivity_advanced.sh` |

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

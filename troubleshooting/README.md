# EC2 Same-Subnet Connectivity Troubleshooting Suite

**Complete guide for debugging RHEL8 ↔ RHEL9 connectivity on the same VPC subnet.**

## 📦 Structure

```
troubleshooting/
├── README.md (this file)
├── QUICK_START.md
├── DECISION_TREE.md
├── AWS_INFRASTRUCTURE_CHECKLIST.md
├── INSTANCE_NETWORKING_CHECKLIST.md
├── COMMON_ISSUES.md
└── scripts/
    ├── verify_vpc_connectivity.sh          (AWS infra check)
    ├── verify_instance_networking.sh       (Instance-level check)
    ├── diagnose_rhel8_listener.sh          (RHEL8-specific check)
    ├── fix_rhel8_port_access.sh            (Auto-fix for RHEL8)
    ├── test_container_rhel_connectivity.sh (Container→RHEL8 test)
    └── test_rhel_connectivity_advanced.sh  (Advanced multi-layer test)
```

---

## 🚀 Quick Start (5 Minutes)

### Step 1: AWS Infrastructure Check  
**Run from your laptop** (requires AWS CLI configured):

```bash
cd troubleshooting/scripts/
./verify_vpc_connectivity.sh i-rhel8-id i-rhel9-id --region us-gov-west-1
```

**This checks:**
- ✓ Both instances running in same VPC/subnet
- ✓ Security groups allow traffic
- ✓ NACLs don't block traffic
- ✓ Route tables configured properly

**If this fails:** Stop here, don't continue to instances. Fix AWS infrastructure first.

---

### Step 2: RHEL8 Instance Check  
**SSH to RHEL8:**

```bash
./verify_instance_networking.sh <RHEL8_IP> <RHEL9_IP> 8080
```

**This checks:**
- ✓ Routing from RHEL8 to RHEL9 works
- ✓ Service listening on port 8080
- ✓ Firewall (firewalld/iptables) allows traffic
- ✓ SELinux not blocking port

**If this fails:** Service not listening or local firewall blocking.

---

### Step 3: RHEL9 Instance Check  
**SSH to RHEL9:**

```bash
./verify_instance_networking.sh <RHEL9_IP> <RHEL8_IP> 8080
```

**This checks:**
- ✓ Can ping RHEL8 (ICMP)
- ✓ TCP port 8080 opens on RHEL8
- ✓ RHEL9's firewall allows outbound

**If successful:** Instances can communicate! ✅

---

## 📊 Decision Tree

```
Does the check PASS?
│
├─ AWS check FAILS?
│  └─ Check docs/AWS_INFRASTRUCTURE_CHECKLIST.md
│     → Fix security groups, NACLs, or routes
│
├─ RHEL8 check FAILS?
│  └─ Check docs/INSTANCE_NETWORKING_CHECKLIST.md#rhel8
│     → Service not listening? Start it
│     → Firewall blocking? Fix with firewall-cmd
│     → SELinux blocking? Fix with semanage
│
└─ RHEL9 check FAILS?
   └─ Check docs/AWS_INFRASTRUCTURE_CHECKLIST.md#security-groups
      → AWS SG not allowing RHEL9→RHEL8? Add rule
```

---

## 📋 Full Documentation

| Guide | Purpose | Who Runs It |
|-------|---------|-------------|
| [QUICK_START.md](QUICK_START.md) | 5-minute first-time run | Everyone |
| [DECISION_TREE.md](DECISION_TREE.md) | What to check based on failure | Everyone |
| [AWS_INFRASTRUCTURE_CHECKLIST.md](AWS_INFRASTRUCTURE_CHECKLIST.md) | Detailed AWS layer checks | Dev lead / DevOps |
| [INSTANCE_NETWORKING_CHECKLIST.md](INSTANCE_NETWORKING_CHECKLIST.md) | Detailed OS-level checks | SRE / Ops |
| [COMMON_ISSUES.md](COMMON_ISSUES.md) | Specific error solutions | Troubleshooter |

---

## 🔧 Scripts Reference

### `verify_vpc_connectivity.sh` (AWS CLI)
**Checks AWS infrastructure:**
- Instance states & types
- VPC/subnet membership
- Security group rules (ingress/egress)
- Network ACL rules
- Route tables
- ENI status

**Usage:**
```bash
./scripts/verify_vpc_connectivity.sh i-rhel8-abc123 i-rhel9-xyz789 --region us-gov-west-1
```

**Output:**
```
[✓] Both instances running
[✓] Same VPC: vpc-123456
[✓] Same subnet: subnet-abcdef
[✓] RHEL8 SG allows RHEL9
[✓] No DENY rules in NACLs
```

---

### `verify_instance_networking.sh` (Run on instance via SSH)
**Checks instance-level networking:**
- IP assignment & interface status
- Routing to target
- ARP resolution (L2)
- ICMP (ping) reachability
- TCP port connectivity
- Local firewall (firewalld/iptables)
- SELinux status
- Service listening on port
- MTU configuration

**Usage:**
```bash
# SSH to RHEL8, then:
./verify_instance_networking.sh 10.0.1.50 10.0.1.100 8080

# SSH to RHEL9, then:
./verify_instance_networking.sh 10.0.1.100 10.0.1.50 8080
```

**Output:**
```
[✓] IP 10.0.1.50 assigned
[✓] Interface eth0 UP
[✓] Route exists to 10.0.1.100
[✓] ARP entry exists
[✓] ICMP ping successful
[✓] TCP port 8080 OPEN
[✓] No DROP/REJECT firewall rules
✓ Disabled SELinux
```

---

### `diagnose_rhel8_listener.sh` (RHEL8 specific)
**Deep-dive diagnostics for RHEL8:**
- What process is listening on port?
- Is firewalld running & allowing port?
- Is iptables blocking?
- SELinux port context check
- Service status & logs

**Usage:**
```bash
./diagnose_rhel8_listener.sh 8080 myservice
```

**Output with fixes:**
```
[✓] Port 8080 found in ss output: 
    LISTEN 0 128 10.0.1.50:8080 0.0.0.0:* pid/myservice

[✗] Port 8080 NOT in firewalld
    Fix: sudo firewall-cmd --permanent --add-port=8080/tcp

[✗] Port 8080 NOT in SELinux policy (Enforcing mode)
    Fix: sudo semanage port -a -t http_port_t -p tcp 8080
```

---

### `fix_rhel8_port_access.sh` (RHEL8, root)
**Auto-fix script for RHEL8.**

**Dry-run (check what would be fixed):**
```bash
sudo ./fix_rhel8_port_access.sh 8080 myservice
```

**Actually apply fixes:**
```bash
sudo ./fix_rhel8_port_access.sh 8080 myservice --fix
```

**What it fixes:**
- ✓ Adds port to firewalld (if needed)
- ✓ Adds port to SELinux policy (if Enforcing)
- ✓ Starts and enables service (if provided)
- ✓ Reloads firewalld

---

### `test_container_rhel_connectivity.sh` (In container)
**Quick container→RHEL8 test.**

**Usage:**
```bash
./test_container_rhel_connectivity.sh 10.0.1.50 8080 myservice
```

**Checks:**
- ICMP reachability
- TCP SYN/ACK
- Container firewall rules
- Container SELinux
- Application-level connection

---

### `test_rhel_connectivity_advanced.sh` (In container, advanced)
**Advanced multi-layer test with packet capture.**

**Usage:**
```bash
./test_rhel_connectivity_advanced.sh 10.0.1.50 8080 tcp
./test_rhel_connectivity_advanced.sh 10.0.1.50 80 http
```

**Captures:**
- ARP cache
- ICMP test output
- TCP test detail
- tcpdump packet capture (if available)
- DNS resolution

---

## 🎯 Common Scenarios

### **Scenario 1: "TCP port opens but service doesn't respond"**

```bash
# From RHEL9:
echo > /dev/tcp/10.0.1.50/8080  # ✓ Succeeds

# But curl fails:
curl http://10.0.1.50:8080/     # ✗ Timeout or connection reset
```

**Root Cause:** Service listening but crashing on request

**Diagnosis:**
```bash
# On RHEL8:
sudo journalctl -u myservice -f
tail -f /var/log/myservice.log
```

**Solution:** Check service logs, fix app config

---

### **Scenario 2: "nc works but curl fails"**

```bash
# From RHEL9:
nc -zv 10.0.1.50 8080           # ✓ Succeeds

# But HTTP fails:
curl http://10.0.1.50:8080/     # ✗ Fails
```

**Root Cause:** L4 open but app doesn't understand HTTP

**Solution:** 
- Verify app is HTTP-capable
- Check app logs for parse errors
- Use `telnet` to inspect raw response

---

### **Scenario 3: "Ping works but TCP port fails"**

```bash
# From RHEL9:
ping 10.0.1.50                  # ✓ Succeeds

# But port fails:
echo > /dev/tcp/10.0.1.50/8080  # ✗ Fails (connection refused)
```

**Root Cause:** Service not listening on that port

**Solutions:**
```bash
# On RHEL8:
sudo systemctl status myservice    # Is it running?
ss -tlnp | grep 8080              # Is it bound to 8080?
sudo firewall-cmd --list-ports    # Is firewall blocking?
```

---

### **Scenario 4: "Ping fails completely"**

```bash
# From RHEL9:
ping 10.0.1.50                  # ✗ Fails (no response)
```

**Root Cause:** AWS security group or NACL blocking ICMP

**Solutions:**
```bash
# From laptop with AWS CLI:
aws ec2 describe-security-groups --group-ids <RHEL8_SG> \
  --query 'SecurityGroups[0].IpPermissions'

# Add rule if needed:
aws ec2 authorize-security-group-ingress \
  --group-id <RHEL8_SG> \
  --protocol all \
  --source-group <RHEL9_SG>
```

---

## 🧪 Testing Workflow

### **Complete validation workflow:**

```bash
# 1. On your laptop:
./scripts/verify_vpc_connectivity.sh i-rhel8 i-rhel9 --region us-gov-west-1
# Expected: All ✓

# 2. SSH to RHEL8:
ssh ec2-user@<RHEL8_IP>
./verify_instance_networking.sh 10.0.1.50 10.0.1.100 8080
# Expected: "All systems GO!"

# 3. SSH to RHEL9 (new terminal):
ssh ec2-user@<RHEL9_IP>
./verify_instance_networking.sh 10.0.1.100 10.0.1.50 8080
# Expected: "All systems GO!"

# 4. From RHEL9, test actual service:
curl http://10.0.1.50:8080/
# Expected: Service responds
```

---

## 🔍 Advanced Debugging

### **If verify scripts pass but connectivity still fails:**

#### Option 1: Packet Capture
```bash
# On RHEL8 (terminal 1):
sudo tcpdump -i any -n 'host 10.0.1.100 and port 8080' -v

# From RHEL9 (terminal 2):
curl http://10.0.1.50:8080/
```

**Look for:**
- ✓ SYN from RHEL9 → SYN-ACK from RHEL8
- ✗ SYN from RHEL9 → RST (port closed)
- ✗ No traffic visible (network layer issue)

#### Option 2: Service Debug Mode
```bash
# On RHEL8, run service in debug mode:
sudo systemctl stop myservice
sudo /opt/myservice/bin/myservice --debug &  # Or similar
```

Then from RHEL9:
```bash
curl -v http://10.0.1.50:8080/
```

Watch RHEL8 logs in real-time for errors.

#### Option 3: Strace the Service
```bash
# On RHEL8:
sudo strace -f -e trace=network -p $(pids -u service-user)

# From RHEL9:
curl http://10.0.1.50:8080/
```

Watch syscalls for socket errors.

---

## 📚 File Reference

| File | Size | Purpose |
|------|------|---------|
| `verify_vpc_connectivity.sh` | 10KB | AWS infra check (AWS CLI) |
| `verify_instance_networking.sh` | 9.6KB | Instance-level check (SSH) |
| `diagnose_rhel8_listener.sh` | 5.9KB | RHEL8 deep-dive (SSH to RHEL8) |
| `fix_rhel8_port_access.sh` | 7.2KB | Auto-fix script (root on RHEL8) |
| `test_container_rhel_connectivity.sh` | 4.8KB | Container→RHEL test |
| `test_rhel_connectivity_advanced.sh` | 7.7KB | Advanced multi-layer test |

---

## 🎓 Learning Path

1. **Start here:** [QUICK_START.md](QUICK_START.md)
2. **Understand the layers:** [DECISION_TREE.md](DECISION_TREE.md)
3. **Deep-dive AWS:** [AWS_INFRASTRUCTURE_CHECKLIST.md](AWS_INFRASTRUCTURE_CHECKLIST.md)
4. **Deep-dive OS:** [INSTANCE_NETWORKING_CHECKLIST.md](INSTANCE_NETWORKING_CHECKLIST.md)
5. **Solve your issue:** [COMMON_ISSUES.md](COMMON_ISSUES.md)

---

## 📞 Getting Help

If scripts/docs don't solve your issue:

1. **Run verify script with increased verbosity** (add `-v` flags)
2. **Capture tcpdump output** while reproducing issue
3. **Collect service logs** from RHEL8 (`journalctl -u service -n 100`)
4. **Check AWS CloudTrail** for API errors
5. **Share the output** from all `verify_*` scripts

---

**Last Updated:** March 2, 2026

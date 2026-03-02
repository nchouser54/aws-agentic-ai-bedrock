# RHEL8 ↔ Container Connectivity Troubleshooting Guide

This directory contains diagnostic scripts for troubleshooting connectivity issues between a RHEL9 container and a RHEL8 custom image. Specifically designed for the case where:
- `nc` and `tcpdump` show traffic arriving on RHEL8
- But normal application connections fail

## Quick Diagnosis Flow

```
Container-side test → "OK"?
  ├─ Yes → Issue is on RHEL8 (service not listening or firewall)
  └─ No → Network-level issue (routing, VPC, security group)

RHEL8-side test → "Port listening"?
  ├─ Yes with "Normal traffic fails" → SELinux or app-level issue
  ├─ No → Service not running or port not bound
  └─ Check → Firewalld / iptables blocking
```

## Scripts Overview

### 1. **test_container_rhel_connectivity.sh** (Run FROM container/RHEL9)
**Purpose**: Quick connectivity test at multiple layers

**Usage**:
```bash
# On RHEL9 container
./test_container_rhel_connectivity.sh 10.0.1.50 8080 myservice
./test_container_rhel_connectivity.sh 192.168.1.100 443   # HTTPS
./test_container_rhel_connectivity.sh hostname.local 80    # HTTP
```

**What it checks**:
- ICMP (ping) reachability
- TCP SYN/ACK (port open?)
- Firewall rules in container (iptables)
- SELinux context in container
- Application-level connectivity (HTTP/HTTPS/raw)

**Example output**:
```
[✓] ICMP reachable
[✓] TCP port 8080 open (SYN ACK received)
[✗] HTTP connection failed or no response
→ Indicates: network path is OK, but service not responding properly
```

---

### 2. **diagnose_rhel8_listener.sh** (Run ON RHEL8)
**Purpose**: Check service binding, firewall, and SELinux on RHEL8

**Usage**:
```bash
# SSH to RHEL8, then:
./diagnose_rhel8_listener.sh 8080 myservice
./diagnose_rhel8_listener.sh 443
./diagnose_rhel8_listener.sh 5432 postgresql
```

**What it checks**:
- Is a process listening on the port? (`ss -tlnp`)
- Is firewalld allowing the port? (`firewall-cmd --list-ports`)
- Is SELinux blocking the port? (`semanage port -l`)
- Is the service running? (`systemctl status`)
- Can localhost reach the port?

**Example output**:
```
[✓] Port 8080 found in ss output
[✗] Port 8080 is NOT explicitly allowed in firewalld
[✗] SELinux is Enforcing — may block traffic
→ Indicates: Service bound, but firewall + SELinux blocking external traffic
```

---

### 3. **test_rhel_connectivity_advanced.sh** (Run FROM container/RHEL9)
**Purpose**: Multi-layer troubleshooting with packet capture

**Usage**:
```bash
./test_rhel_connectivity_advanced.sh 10.0.1.50 8080 tcp
./test_rhel_connectivity_advanced.sh 10.0.1.50 80 http
./test_rhel_connectivity_advanced.sh 10.0.1.50 443 https
```

**What it does**:
- LAYER 2-3: ARP, ICMP tests
- LAYER 4: TCP SYN/ACK test
- Packet capture (if tcpdump available)
- DNS/hostname resolution
- Network interface and routing checks
- Logs all results to `/tmp` for review

**Use when**:
- `test_container_rhel_connectivity.sh` output is confusing
- You need packet-level diagnostics
- Troubleshooting intermittent issues

---

### 4. **fix_rhel8_port_access.sh** (Run ON RHEL8, as root)
**Purpose**: Automatically identify and fix common RHEL8 port access issues

**Usage**:
```bash
# Dry-run (show what would be fixed):
sudo ./fix_rhel8_port_access.sh 8080 myservice

# Actually apply fixes:
sudo ./fix_rhel8_port_access.sh 8080 myservice --fix
```

**What it fixes** (in `--fix` mode):
- Adds port to firewalld (if not already there)
- Adds port to SELinux policy (if needed)
- Starts and enables the service (if SERVICE_NAME provided)
- Reloads firewalld

**Service name mappings** (auto-detected):
- `nginx`, `httpd`, `apache` → `http_port_t`
- `postgresql`, `postgres` → `postgresql_port_t`
- `mysql` → `mysqld_port_t`
- `mongodb` → `mongod_port_t`
- `redis` → `redis_port_t`
- ...and more

---

## Common Scenarios & Solutions

### Scenario 1: "nc works but HTTP fails"
**Root cause**: Service likely not listening or crashing

```bash
# On RHEL9 container:
./test_container_rhel_connectivity.sh 10.0.1.50 8080

# Output shows:
[✓] TCP port 8080 open (SYN ACK received)
[✗] HTTP connection failed

# On RHEL8:
./diagnose_rhel8_listener.sh 8080
ps aux | grep myservice  # Is it actually running?
```

**Fix**: Restart service and check logs
```bash
sudo systemctl restart myservice
sudo journalctl -u myservice -f
```

---

### Scenario 2: "Permission denied" or SELinux errors
**Root cause**: SELinux blocking the port

```bash
# On RHEL8:
sudo ./fix_rhel8_port_access.sh 8080 myservice --check
# Output shows: [✗] Port 8080/tcp NOT in SELinux policy

sudo ./fix_rhel8_port_access.sh 8080 myservice --fix
```

**Verify**:
```bash
sudo semanage port -l | grep 8080
# Should show: myapp_port_t  tcp  8080
```

---

### Scenario 3: "Connection refused" from container
**Root cause**: Firewall blocking, or port not listening

```bash
# On RHEL9 container:
./test_container_rhel_connectivity.sh 10.0.1.50 8080
# Output shows: [✗] TCP port 8080 closed or not responding

# On RHEL8, check what's listening:
./diagnose_rhel8_listener.sh 8080
# Check output for:
# - Is firewalld active?
# - Is the port in firewall rules?
# - Is a process actually listening?

# If firewall issue:
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload
```

---

### Scenario 4: "Connection timeout" (no response at all)
**Root cause**: Network path issue or service completely down

```bash
# On RHEL9 container:
./test_rhel_connectivity_advanced.sh 10.0.1.50 8080 tcp

# Look for:
# - ICMP passes? → Network routing OK
# - TCP fails? → Service not listening or firewall
# - Packet capture shows RST? → Firewall resetting
```

---

## Typical Troubleshooting Flow

### Step 1: Container-side quick test
```bash
cd scripts/
./test_container_rhel_connectivity.sh 10.0.1.50 8080
```

**If ICMP and TCP pass but app fails** → Issue is on RHEL8

### Step 2: RHEL8 diagnostics
```bash
ssh rhel8-host
cd scripts/
./diagnose_rhel8_listener.sh 8080 myservice
```

**Check the output for**:
- Is port in `ss -tlnp` output? (service running)
- Is port in firewall allow list?
- Is SELinux blocking it?

### Step 3: Apply fixes
```bash
# On RHEL8
sudo ./fix_rhel8_port_access.sh 8080 myservice --fix
```

### Step 4: Re-test
```bash
# Back to RHEL9 container
./test_container_rhel_connectivity.sh 10.0.1.50 8080
```

---

## Detailed Troubleshooting Checklist

**Network Layer (ICMP)**
- [ ] Ping test passes
- [ ] Can see routes: `ip route get <RHEL8_IP>`
- [ ] ARP entry exists: `arp -n | grep <RHEL8_IP>`

**Transport Layer (TCP)**
- [ ] TCP SYN/ACK test passes (port open)
- [ ] Can connect: `echo | nc -w 1 <RHEL8_IP> 8080`
- [ ] tcpdump shows SYN → SYN-ACK pattern

**RHEL8 Service**
- [ ] Service running: `systemctl is-active myservice`
- [ ] Port bound: `ss -tlnp | grep 8080`
- [ ] No errors: `journalctl -u myservice -n 50`

**RHEL8 Firewall (firewalld)**
- [ ] firewalld running: `systemctl is-active firewalld`
- [ ] Port in allow list: `firewall-cmd --list-ports`
- [ ] Add if missing: `firewall-cmd --permanent --add-port=8080/tcp && firewall-cmd --reload`

**RHEL8 SELinux**
- [ ] Check status: `getenforce` (should be "Disabled" or "Permissive")
- [ ] If Enforcing, check port context: `semanage port -l | grep 8080`
- [ ] Add if missing: `semanage port -a -t http_port_t -p tcp 8080`

**Application Level**
- [ ] Service config binds to correct IP/port
- [ ] Service not crashing on startup
- [ ] Logs available: `/var/log/myservice.log` or `journalctl -u myservice`

---

## Advanced Debugging

### Capture full tcpdump session
```bash
# On RHEL8, capture in one terminal:
sudo tcpdump -i any -n 'host 10.0.1.100 and port 8080' -v

# From container in another terminal:
curl http://10.0.1.50:8080/
```

### Check SELinux violations
```bash
# On RHEL8:
sudo journalctl | grep -i selinux
sudo ausearch -m avc | grep -i "denied.*port.*8080"
```

### Monitor service startup
```bash
# On RHEL8, watch logs while restarting:
sudo journalctl -u myservice -f &
sudo systemctl restart myservice
# Watch for errors in the logs
```

### Network namespace inspection (container)
```bash
# Inside container:
ip netns list
ip link show
ip route show
ss -tlnp
```

---

## Files Created

```
scripts/
├── test_container_rhel_connectivity.sh      (4.8K, container side)
├── diagnose_rhel8_listener.sh               (5.9K, RHEL8 side)
├── test_rhel_connectivity_advanced.sh       (7.7K, container side, advanced)
├── fix_rhel8_port_access.sh                 (7.2K, RHEL8 side, auto-fix)
└── RHEL8_TROUBLESHOOTING_GUIDE.md          (this file)
```

---

## Quick Reference: Common Ports

| Port  | Service      | SELinux Type       | Notes |
|-------|--------------|-------------------|-------|
| 22    | SSH          | ssh_port_t        | |
| 80    | HTTP         | http_port_t       | |
| 443   | HTTPS        | http_port_t       | |
| 3000  | Node/App     | http_port_t       | |
| 5432  | PostgreSQL   | postgresql_port_t | |
| 3306  | MySQL        | mysqld_port_t     | |
| 6379  | Redis        | redis_port_t      | |
| 27017 | MongoDB      | mongod_port_t     | |
| 8000  | Custom App   | http_port_t       | Assume HTTP-like |
| 8080  | Custom App   | http_port_t       | Assume HTTP-like |
| Custom| Custom       | (manual)          | Run diagnose script to determine |

---

## Help / Manual Pages

Each script supports `--help` or `-h`:
```bash
./test_container_rhel_connectivity.sh --help
./diagnose_rhel8_listener.sh --help
./test_rhel_connectivity_advanced.sh --help
./fix_rhel8_port_access.sh --help
```

---

**Last Updated**: March 2, 2026

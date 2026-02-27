# Network Test Scripts — EC2 ↔ EC2 and EC2 ↔ Podman Container

Scripts for testing and debugging TCP connectivity between:

- **Two plain EC2 instances** (multi-port testing)
- **An EC2 (RHEL8) and a Podman container on another EC2 (RHEL9)**

Designed to diagnose the specific symptom where `tcpdump` sees traffic arriving
but `nc` still reports a timeout — which almost always means a firewall, SELinux,
or Podman networking configuration issue rather than a routing problem.

---

## Folder Structure

```
network-test-scripts/
├── ec2-to-ec2/
│   ├── server.sh              # nc listener on the receiver EC2
│   ├── client.sh              # nc connect from the sender EC2
│   └── multi_port_test.sh     # scan multiple ports at once
│
├── ec2-to-podman/
│   ├── podman_server_setup.sh # launch an nc listener container on RHEL9
│   ├── client_test.sh         # connect from RHEL8 to the Podman container
│   └── check_podman_config.sh # inspect Podman networking config
│
├── diagnostics/
│   ├── full_diagnostic.sh     # run everything and save a report
│   ├── tcpdump_capture.sh     # capture + interpret traffic on a port
│   ├── check_firewall.sh      # inspect firewalld / iptables / nftables
│   ├── check_selinux.sh       # check SELinux status and denials
│   └── check_iptables.sh      # show Podman iptables/nftables chains
│
└── fixes/
    ├── fix_podman_firewall.sh     # fix firewalld, masquerade, Netavark
    ├── fix_selinux_podman.sh      # fix SELinux booleans and port labels
    └── restart_podman_network.sh  # clean restart of container + networking
```

---

## Quick Start

### Make scripts executable (run once)

```bash
chmod +x network-test-scripts/**/*.sh
```

---

## Scenario A: EC2 to EC2 Testing

**On the receiver EC2 (RHEL8):**
```bash
./ec2-to-ec2/server.sh 9000
```

**On the sender EC2:**
```bash
./ec2-to-ec2/client.sh <RECEIVER_IP> 9000
```

**Test multiple ports at once:**
```bash
./ec2-to-ec2/multi_port_test.sh <RECEIVER_IP> 8080,9000,9090,5000
```

---

## Scenario B: EC2 (RHEL8) → Podman Container on RHEL9

### 1. Start the test container on RHEL9

```bash
./ec2-to-podman/podman_server_setup.sh 9000
```

This launches an `nc` listener container with `-p 0.0.0.0:9000:9000` so it
binds to all interfaces on the RHEL9 host (critical — `127.0.0.1` binding is
a common failure cause).

### 2. Verify Podman config on RHEL9

```bash
./ec2-to-podman/check_podman_config.sh nc-test-server
```

### 3. Test from RHEL8

```bash
./ec2-to-podman/client_test.sh <RHEL9_IP> 9000
```

---

## Diagnosing the "tcpdump sees traffic but nc times out" Problem

This symptom means packets reach the NIC but are dropped **before** the
application receives them. The capture point is:

```
[Remote sender] → [NIC] → [tcpdump captures here] → [iptables/nftables] → [application]
                                                              ↑
                                                     DROP happens here
```

### Step 1 — Capture on both hosts simultaneously

**On RHEL9 (Podman host) — watch what leaves:**
```bash
./diagnostics/tcpdump_capture.sh 9000
```

**On RHEL8 (receiver) — watch what arrives:**
```bash
./diagnostics/tcpdump_capture.sh 9000
```

Then trigger the nc test from RHEL8 in a third terminal.

### Step 2 — Full diagnostic report

Run on **both** hosts and compare:
```bash
./diagnostics/full_diagnostic.sh <OTHER_HOST_IP> 9000
```
Output is saved to `/tmp/network_diag_<hostname>_<timestamp>.log`.

### Step 3 — Check firewall

```bash
./diagnostics/check_firewall.sh 9000     # run on RHEL9
./diagnostics/check_firewall.sh 9000     # run on RHEL8
```

### Step 4 — Check SELinux

```bash
./diagnostics/check_selinux.sh 9000      # run on RHEL9 (Podman host)
```

### Step 5 — Check iptables/nftables Podman chains

```bash
./diagnostics/check_iptables.sh 9000     # run on RHEL9
```

---

## Applying Fixes

### Fix 1: firewalld + masquerade + Netavark (most common cause)

```bash
# On RHEL9 as root:
./fixes/fix_podman_firewall.sh 9000
```

This applies:
- `firewall-cmd --zone=public --add-port=9000/tcp --permanent`
- `firewall-cmd --zone=public --add-masquerade --permanent`
- Adds Podman subnet `10.88.0.0/16` to the trusted zone
- Enables `net.ipv4.ip_forward`

### Fix 2: SELinux denials

```bash
# Dry-run (diagnose only):
./fixes/fix_selinux_podman.sh 9000 diagnose

# Apply fixes:
./fixes/fix_selinux_podman.sh 9000 fix
```

### Fix 3: Clean restart of Podman + networking

```bash
./fixes/restart_podman_network.sh nc-test-server 9000
```

---

## Root Causes Addressed

| Symptom | Root Cause | Fix Script |
|---------|-----------|------------|
| tcpdump sees SYN but no SYN-ACK | firewalld blocking port | `fix_podman_firewall.sh` |
| No packets seen at all on receiver | Podman container traffic not leaving RHEL9 | `fix_podman_firewall.sh` (masquerade) |
| Packets arrive, nc still times out | SELinux denying bind/accept | `fix_selinux_podman.sh` |
| Works as root but not as user | Rootless Podman slirp4netns limitation | Use `--network=host` or run as root |
| Intermittent timeouts | Netavark/firewalld nftables conflict | `fix_podman_firewall.sh` (trusted zone) |
| Port published to 127.0.0.1 only | Missing `0.0.0.0` in `-p` flag | `podman_server_setup.sh` (re-run) |

---

## AWS Security Group Requirements

Ensure the following inbound rules exist on each EC2's Security Group:

| EC2 | Direction | Port | Source |
|-----|-----------|------|--------|
| RHEL9 (Podman host) | Inbound | your test port (e.g. 9000) | RHEL8 private IP or SG |
| RHEL8 | Inbound | your test port | RHEL9 private IP or SG |

Security Group rules are checked **before** traffic reaches the instance, so
`tcpdump` will NOT see packets blocked by a Security Group (unlike firewalld).

---

## Podman Networking Notes (RHEL9)

- Podman 4+ on RHEL9 uses **Netavark** (replaces CNI plugins) with an **nftables** backend
- firewalld on RHEL9 also uses **nftables** — they can conflict
- Rootless Podman uses **slirp4netns** or **pasta** for networking, which means:
  - Published ports are proxied through userspace, not the kernel
  - Ports may NOT appear in `ss -tlnp` output even when working
  - Run containers as root (`sudo podman`) or with `--network=host` for simpler debugging

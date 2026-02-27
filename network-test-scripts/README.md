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
│   ├── multi_port_test.sh     # scan multiple ports at once
│   └── alt_connect_test.sh    # alternative connection methods (curl, socat, etc.)
│
├── ec2-to-podman/
│   ├── podman_server_setup.sh # launch an nc listener container on RHEL9
│   ├── client_test.sh         # connect from RHEL8 to the Podman container
│   └── check_podman_config.sh # inspect Podman networking config (incl.
│                              #   aardvark-dns, Docker daemon conflict, CNI)
│
├── diagnostics/
│   ├── full_diagnostic.sh     # run ALL checks below and save a report
│   ├── tcpdump_capture.sh     # capture + interpret traffic on a port
│   ├── check_firewall.sh      # inspect firewalld / iptables / nftables
│   ├── check_selinux.sh       # check SELinux status and denials
│   ├── check_iptables.sh      # show Podman iptables/nftables chains
│   ├── check_conntrack.sh     # conntrack table usage + stale entries
│   ├── check_tcp_wrappers.sh  # hosts.allow / hosts.deny (RHEL8 receiver)
│   ├── check_custom_rhel8.sh  # hardening checks: fail2ban, ipset, rp_filter,
│   │                          #   FIPS, EDR agents, eBPF/XDP, tc filters, VPN
│   └── check_debian_pod.sh    # Debian container: ufw, AppArmor, iptables
│                              #   variant, nc flavour, DNS resolution
│
└── fixes/
    ├── fix_podman_firewall.sh     # fix firewalld, masquerade, Netavark
    ├── fix_selinux_podman.sh      # fix SELinux booleans and port labels (RHEL)
    ├── fix_apparmor_podman.sh     # fix AppArmor confinement (Debian container)
    ├── fix_conntrack.sh           # flush stale conntrack entries, tune limits
    └── restart_podman_network.sh  # clean restart of container + networking
```

---

## Quick Start

### 1. Configure once with `test.env`

All scripts read from a shared config file so you never have to repeat IPs or
ports on the command line.

```bash
# One-time setup — fill in your actual IPs
cp test.env.example test.env
$EDITOR test.env
```

`test.env` is gitignored (contains host-specific IPs). The file you edit looks like:

```bash
RHEL8_IP="10.0.0.10"          # RHEL8 EC2 (nc receiver / client)
RHEL9_IP="10.0.0.20"          # RHEL9 EC2 (Podman host / server)
TEST_PORT="21240"              # Port the container publishes
CONTAINER_NAME="nc-test-server"
CONTAINER_IMAGE="registry.access.redhat.com/ubi9/ubi-minimal"
CONTAINER_PORT="${TEST_PORT}"  # Port inside the container
TIMEOUT_SECS="5"
CAPTURE_DURATION="30"
```

### 2. Make scripts executable (run once)

```bash
chmod +x run.sh **/*.sh
```

### 3. Use `run.sh` for common workflows

```bash
./run.sh config          # verify active configuration
./run.sh server          # start nc container on RHEL9 (Podman host)
./run.sh test            # test connectivity from RHEL8 → RHEL9
./run.sh diag            # full diagnostic report
./run.sh selinux-fix     # diagnose SELinux issues (dry-run)
./run.sh help            # list all commands
```

CLI arguments still override `test.env` values in every script:

```bash
# Override just the port for this one run
./run.sh test
# … or call the script directly
./ec2-to-podman/client_test.sh 1.2.3.4 9000
```

---

## Scenario A: EC2 to EC2 Testing

**On the receiver EC2 (RHEL8):**
```bash
./ec2-to-ec2/server.sh         # uses TEST_PORT from test.env
./ec2-to-ec2/server.sh 9000    # or specify port explicitly
```

**On the sender EC2:**
```bash
./ec2-to-ec2/client.sh                         # uses RHEL9_IP + TEST_PORT
./ec2-to-ec2/client.sh <RECEIVER_IP> 9000      # or specify explicitly
```

**Test multiple ports at once:**
```bash
./ec2-to-ec2/multi_port_test.sh                           # uses RHEL9_IP
./ec2-to-ec2/multi_port_test.sh <RECEIVER_IP> 8080,9000,9090,5000
```

---

## Scenario B: EC2 (RHEL8) → Podman Container on RHEL9

### 1. Start the test container on RHEL9

```bash
./run.sh server                    # uses test.env
./ec2-to-podman/podman_server_setup.sh 9000   # or explicit port
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
./run.sh test                            # uses RHEL9_IP + TEST_PORT from test.env
./ec2-to-podman/client_test.sh <RHEL9_IP> 9000   # or explicit args
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
./run.sh tcpdump                     # uses TEST_PORT + CAPTURE_DURATION from test.env
./diagnostics/tcpdump_capture.sh 9000   # or explicit port
```

**On RHEL8 (receiver) — watch what arrives:**
```bash
./run.sh tcpdump
./diagnostics/tcpdump_capture.sh 9000
```

Then trigger the nc test from RHEL8 in a third terminal.

### Step 2 — Full diagnostic report

Run on **both** hosts and compare:
```bash
./run.sh diag            # on RHEL8: targets RHEL9_IP from test.env
./run.sh diag rhel9      # on RHEL9: targets RHEL8_IP from test.env
./diagnostics/full_diagnostic.sh <OTHER_HOST_IP> 9000 [CONTAINER_NAME]  # explicit
```
Output is saved to `/tmp/network_diag_<hostname>_<timestamp>.log`.

This now automatically runs all specialized sub-scripts below (conntrack,
firewall, SELinux, iptables, TCP wrappers, RHEL8 hardening, Podman config,
and the Debian pod check if the container is running).

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

### Step 6 — Check conntrack (silent drops when table is full)

```bash
./diagnostics/check_conntrack.sh 9000    # run on either host
```

### Step 7 — Check TCP Wrappers (RHEL8 receiver)

```bash
./diagnostics/check_tcp_wrappers.sh <RHEL9_IP>   # run on RHEL8
```

### Step 8 — Check custom RHEL8 hardening (fail2ban, eBPF, VPN, EDR)

```bash
./diagnostics/check_custom_rhel8.sh <RHEL9_IP> 9000   # run on RHEL8
```

### Step 9 — Check Debian developer pod (AppArmor, iptables variant, DNS)

```bash
./diagnostics/check_debian_pod.sh dev-pod 9000 <RHEL8_IP>   # run on RHEL9
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

| Symptom | Root Cause | Script |
|---------|-----------|--------|
| tcpdump sees SYN but no SYN-ACK | firewalld blocking port | `fix_podman_firewall.sh` |
| No packets seen at all on receiver | Podman container traffic not leaving RHEL9 | `fix_podman_firewall.sh` (masquerade) |
| Packets arrive, nc still times out | SELinux denying bind/accept | `fix_selinux_podman.sh` |
| Works as root but not as user | Rootless Podman slirp4netns limitation | Use `--network=host` or run as root |
| Intermittent timeouts | Netavark/firewalld nftables conflict | `fix_podman_firewall.sh` (trusted zone) |
| Port published to 127.0.0.1 only | Missing `0.0.0.0` in `-p` flag | `podman_server_setup.sh` (re-run) |
| Connection reset after repeated failures | fail2ban banned the sender IP | `check_custom_rhel8.sh` [1] |
| Intermittent drops, no firewall rule match | conntrack table full (stale NAT entries) | `fix_conntrack.sh` |
| RHEL8 nc accepts then immediately closes | TCP Wrappers `hosts.deny ALL:ALL` | `check_tcp_wrappers.sh` |
| Container cannot resolve hostnames | aardvark-dns not running | `check_podman_config.sh` |
| Container nc works but app connections fail | Docker daemon iptables conflict | `check_podman_config.sh` |
| Packets dropped before iptables on RHEL8 | XDP/eBPF program on NIC or tc ingress filter | `check_custom_rhel8.sh` [15] |
| Traffic rerouted through VPN tunnel | VPN client (OpenVPN/WireGuard/AnyConnect) running | `check_custom_rhel8.sh` [16] |
| nc works, app still times out | AppArmor confining nc inside Debian container | `fix_apparmor_podman.sh` |
| iptables rules invisible / no effect | iptables-nft vs iptables-legacy mismatch in container | `check_debian_pod.sh` |

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

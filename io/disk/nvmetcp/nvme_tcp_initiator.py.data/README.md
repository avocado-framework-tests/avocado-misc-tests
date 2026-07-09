# NVMe/TCP Initiator Configuration Test

## Overview

Configures NVMe/TCP initiator on Linux to connect to NVMe/TCP targets. Supports single-path and multipath configurations with persistence across reboots.

## Prerequisites

- Linux kernel >= 5.0 with NVMe/TCP support
- RHEL-based or SUSE-based distribution
- Root/sudo access
- Pre-configured NVMe/TCP target accessible on port 4420

## Configuration

Edit `nvme_tcp_initiator.yaml`:

```yaml
# Required parameters
primary_ip: '192.168.1.10'              # Initiator primary IP
primary_interface: 'eth0'               # Primary network interface
primary_subnet: '255.255.255.0'         # Primary subnet mask
primary_gateway: '192.168.1.1'          # Primary gateway
target_ips: '192.168.1.20'              # Target IP(s) - space-separated
subsystem_nqn: 'nqn.2024-01.com.example:nvme:target1'  # Target subsystem NQN
target_port: 4420                       # Target port

# Optional (for multipath)
secondary_ip: '192.168.2.10'            # Initiator secondary IP
secondary_interface: 'eth1'             # Secondary network interface
secondary_subnet: '255.255.255.0'       # Secondary subnet mask
secondary_gateway: '192.168.2.1'        # Secondary gateway
```

## Usage

### Single-Path
```bash
avocado run nvme_tcp_initiator.py \
    --mux-yaml nvme_tcp_initiator.py.data/nvme_tcp_initiator.yaml
```

### Multipath
Configure both `primary_ip` and `secondary_ip` in YAML, then run same command.

### Override Parameters
```bash
avocado run nvme_tcp_initiator.py \
    --mux-yaml nvme_tcp_initiator.py.data/nvme_tcp_initiator.yaml \
    -p primary_ip=192.168.1.10 \
    -p target_ips='192.168.1.20' \
    -p subsystem_nqn='nqn.2024-01.com.example:nvme:target1'
```

## Test Flow

1. **Prerequisites**: Install nvme-cli, load nvme-tcp module
2. **Network Validation**: Verify IP configuration and connectivity
3. **Discovery**: Discover NVMe/TCP targets
4. **Connection**: Connect to target subsystem
5. **Multipath**: Enable native multipathing (if configured)
6. **Persistence**: Configure `/etc/nvme/discovery.conf` and systemd service
7. **Validation**: Verify controllers, namespaces, and paths
8. **Report**: Generate configuration status report

## References

- [Red Hat NVMe/TCP Documentation](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/managing_storage_devices/configuring-nvme-over-fabrics-using-nvme-tcp_managing-storage-devices)
- [SUSE NVMe-oF Documentation](https://documentation.suse.com/sles/15-SP7/html/SLES-all/cha-nvmeof.html)
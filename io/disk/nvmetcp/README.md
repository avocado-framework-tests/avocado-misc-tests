# NVMe/TCP Soft Target Automation

Configures a remote Linux host as an NVMe/TCP soft target to expose NVMe namespaces over TCP/IP.

## Quick Start

```bash
# Edit configuration
vi nvme_tcp_soft_target.py.data/nvme_tcp_soft_target.yaml

# Run test
avocado run nvme_tcp_soft_target.py \
    --mux-yaml nvme_tcp_soft_target.py.data/nvme_tcp_soft_target.yaml
```

## Configuration

### SSH Connection
```yaml
soft_target_host_ip: "192.168.1.100"
user_name: "root"
password: "abc1234"
```

### Network (Primary Required, Secondary Optional)
```yaml
network_config_primary_interface: "eth0"
network_config_primary_ip: "192.168.10.100"
network_config_primary_netmask: "255.255.255.0"
network_config_primary_mtu: 9000
```

### Namespace Mode

**Create New:**
```yaml
namespace_config_mode: "create"
namespace_config_nvme_controller: "/dev/nvme0"
namespace_config_number_of_namespaces: null  # Integer, e.g., 4
namespace_config_namespace_size: null        # null = equal split
```

**Select Existing:**
```yaml
namespace_config_mode: "select"
namespace_config_namespaces: "nvme0n1 nvme0n2"
```

### NVMe Target
```yaml
nvmet_config_subsystem_nqn: null  # Auto-generate
nvmet_config_port_id_start: 1
nvmet_config_tcp_port: 4420
nvmet_config_allow_any_host: true
```

## What It Does

1. Configures network interfaces (nmcli)
2. Loads kernel modules (nvmet, nvmet_tcp)
3. Creates/selects namespaces
4. Configures NVMe target via configfs
5. Sets up persistence (systemd + nvmet-cli)
6. Validates configuration

## Prerequisites

- Linux kernel with NVMe target support
- SSH access with passwordless sudo
- Auto-installs: nvme-cli, nvmetcli, NetworkManager

## Verification

### On Target Host
```bash
nvme list-subsys
ss -tlnp | grep 4420
systemctl status nvmet-restore.service
```

### From Initiator
```bash
nvme discover -t tcp -a 192.168.10.100 -s 4420
nvme connect -t tcp -n <nqn> -a 192.168.10.100 -s 4420
nvme list
```

## Cleanup

```bash
sudo systemctl stop nvmet-restore.service
sudo systemctl disable nvmet-restore.service
sudo rm /etc/systemd/system/nvmet-restore.service
sudo rm /etc/nvmet/config.json
sudo rm -rf /sys/kernel/config/nvmet/subsystems/*
sudo rm -rf /sys/kernel/config/nvmet/ports/*
sudo modprobe -r nvmet_tcp nvmet
```

## Troubleshooting

| Issue | Check |
|-------|-------|
| SSH fails | Verify IP, credentials, sshd_config allows password auth |
| Network fails | Verify interface names, NetworkManager running |
| Namespace fails | Check controller exists, sufficient capacity |
| Port not listening | Check `lsmod \| grep nvmet`, `dmesg \| grep nvmet` |

## Security Notes

**Test Configuration:**
- Password authentication
- `allow_any_host: true`
- No TLS encryption

**Production:**
- Use SSH keys
- Configure host ACLs
- Enable firewall rules
- Consider TLS

## License

GNU General Public License v2 or later

## Copyright

2026 IBM
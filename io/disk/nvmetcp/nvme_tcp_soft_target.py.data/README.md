# NVMe/TCP Soft Target Automation

Configures a remote Linux host as an NVMe/TCP soft target to expose NVMe namespaces over TCP/IP.

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
namespace_config_number_of_namespaces: 4
namespace_config_namespace_size: null  # null = equal split of available capacity
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

Verify the NVMe subsystem is registered in configfs and the target is
advertising the correct NQN:
```bash
nvme list-subsys
```

Verify the TCP listener is active on the configured port (default 4420),
confirming the target is ready to accept initiator connections:
```bash
ss -tlnp | grep 4420
```

Verify the systemd service was created and is active, confirming the
configuration will survive a reboot:
```bash
systemctl status nvmet-restore.service
```

### From Initiator

Verify the target is discoverable over TCP from the initiator side,
confirming network reachability and NQN advertisement:
```bash
nvme discover -t tcp -a 192.168.10.100 -s 4420
```

Connect to the target and verify the namespace appears as a block device
on the initiator:
```bash
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

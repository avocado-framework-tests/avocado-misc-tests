# NVMe/TCP Soft Target Automation

This test configures a remote Linux host as an NVMe/TCP soft target, enabling it to expose NVMe namespaces over TCP/IP network.

## Overview

The test performs the following operations:
1. Configures network interfaces on the remote host using nmcli
2. Loads required kernel modules (nvmet, nvmet_tcp)
3. Creates new namespaces or selects existing ones
4. Configures NVMe target subsystem via configfs
5. Sets up persistent configuration using systemd and nvmet-cli
6. Validates the configuration

## Prerequisites

### Remote Host Requirements
- Linux kernel with NVMe target support (CONFIG_NVME_TARGET, CONFIG_NVME_TARGET_TCP)
- Supported package manager: dnf, yum, or apt
- Passwordless sudo or root access via SSH

**Note:** The test automatically installs required packages if missing:
- `nvme-cli` - NVMe command-line tools
- `nvmetcli` - NVMe target configuration tool
- `NetworkManager` - Network configuration (nmcli)

The test will only fail if package installation fails. If packages are already installed, they will be skipped.

## Configuration

Edit the YAML configuration file: `nvme_tcp_soft_target.py.data/nvme_tcp_soft_target.yaml`

**Note:** The YAML uses a flattened format compatible with Avocado's parameter system.

### SSH Connection
```yaml
soft_target_host_ip: "192.168.1.100"
user_name: "root"
password: "abc1234"
```

### Network Configuration
```yaml
# Primary Interface (Required)
network_config_primary_interface: "eth0"
network_config_primary_ip: "192.168.10.100"
network_config_primary_netmask: "255.255.255.0"
network_config_primary_gateway: "192.168.10.1"  # Optional
network_config_primary_mtu: 9000                 # Optional

# Secondary Interface (Optional, for multipath)
network_config_secondary_interface: "eth1"
network_config_secondary_ip: "192.168.10.101"
network_config_secondary_netmask: "255.255.255.0"
network_config_secondary_gateway: "192.168.10.1"  # Optional
network_config_secondary_mtu: 9000                 # Optional
```

### Namespace Configuration

#### Mode 1: Create New Namespaces
```yaml
namespace_config_mode: "create"
namespace_config_nvme_controller: "/dev/nvme0"
namespace_config_number_of_namespaces: 4
namespace_config_namespace_size: null  # null = equal split
```

#### Mode 2: Select Existing Namespaces
```yaml
namespace_config_mode: "select"
namespace_config_namespaces: "nvme0n1 nvme0n2 nvme0n3 nvme0n4"
```

### NVMe Target Configuration
```yaml
nvmet_config_subsystem_nqn: null  # Auto-generate if null
nvmet_config_port_id_start: 1
nvmet_config_tcp_port: 4420       # Standard NVMe/TCP port
nvmet_config_allow_any_host: true # Security consideration
```

**Why Flattened Format?**
Avocado's parameter system works best with flat key-value pairs. Nested dictionaries can cause parsing issues. The test code reconstructs the nested structure internally.

## Usage

### Run the Test
```bash
cd avocado-misc-tests/io/disk/nvmetcp
avocado run nvme_tcp_soft_target.py \
    --mux-yaml nvme_tcp_soft_target.py.data/nvme_tcp_soft_target.yaml
```

### Run with Custom Configuration
```bash
avocado run nvme_tcp_soft_target.py \
    --mux-yaml /path/to/custom_config.yaml
```

### Run with Specific Variant
```bash
avocado run nvme_tcp_soft_target.py \
    --mux-yaml nvme_tcp_soft_target.py.data/nvme_tcp_soft_target.yaml \
    --mux-filter-only /run/variant_name
```

## Validation

The test performs minimal validation:
- Verifies configfs structure exists
- Checks TCP port is listening
- Logs configuration summary

## Post-Test Verification

### On Remote Host

Check NVMe target status:
```bash
# List subsystems
nvme list-subsys

# Check configfs structure
ls -la /sys/kernel/config/nvmet/subsystems/

# Verify ports listening
ss -tlnp | grep 4420

# Check systemd service
systemctl status nvmet-restore.service
```

### From Initiator Host

Discover targets:
```bash
nvme discover -t tcp -a 192.168.10.100 -s 4420
```

Connect to target:
```bash
nvme connect -t tcp -n <subsystem_nqn> -a 192.168.10.100 -s 4420
```

List connected namespaces:
```bash
nvme list
```

## Persistence

The test creates:
1. **Configuration File**: `/etc/nvmet/config.json` (nvmet-cli format)
2. **Systemd Service**: `/etc/systemd/system/nvmet-restore.service`

Configuration persists across reboots via the systemd service.

## Troubleshooting

### SSH Connection Fails
- Verify remote host IP is reachable
- Check SSH credentials (password authentication)
- Ensure SSH service is running on remote host
- Verify SSH allows password authentication (check sshd_config)

### Network Configuration Fails
- Verify interface names are correct
- Check NetworkManager is running
- Ensure no conflicting network configurations

### Namespace Creation Fails
- Verify NVMe controller exists on remote host
- Check sufficient capacity available
- Review FLBAS compatibility (test auto-detects)

### Port Not Listening
- Check kernel modules are loaded: `lsmod | grep nvmet`
- Verify configfs structure: `ls /sys/kernel/config/nvmet/`
- Check for errors in dmesg: `dmesg | grep nvmet`

### Configuration Not Persistent
- Verify nvmet-cli is installed
- Check systemd service status
- Review service logs: `journalctl -u nvmet-restore.service`

## Security Considerations

### Current Implementation
- Password authentication (acceptable for test automation)
- `allow_any_host: true` (allows any initiator to connect)
- No TLS encryption
- Passwordless sudo required

### Production Recommendations
1. Use SSH key authentication instead of passwords
2. Set `allow_any_host: false` and configure specific host ACLs
3. Use firewall rules to restrict access to NVMe/TCP ports
4. Consider TLS for NVMe/TCP connections
5. Implement proper authentication mechanisms

## Cleanup

The test does NOT automatically clean up configuration. To manually remove:

```bash
# On remote host
sudo systemctl stop nvmet-restore.service
sudo systemctl disable nvmet-restore.service
sudo rm /etc/systemd/system/nvmet-restore.service
sudo rm /etc/nvmet/config.json

# Remove configfs configuration
sudo rm -rf /sys/kernel/config/nvmet/subsystems/*
sudo rm -rf /sys/kernel/config/nvmet/ports/*

# Unload modules
sudo modprobe -r nvmet_tcp nvmet
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Test Execution Flow                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. setUp()                                                   │
│     ├─ Parse YAML configuration                              │
│     ├─ Establish SSH connection                              │
│     └─ Verify prerequisites                                  │
│                                                               │
│  2. configure_network()                                       │
│     ├─ Configure primary interface (nmcli)                   │
│     └─ Configure secondary interface (optional)              │
│                                                               │
│  3. load_kernel_modules()                                    │
│     ├─ modprobe nvmet                                        │
│     └─ modprobe nvmet_tcp                                    │
│                                                               │
│  4. create_or_select_namespaces()                            │
│     ├─ Mode: create                                          │
│     │   ├─ Calculate equal namespace sizes                   │
│     │   ├─ Create namespaces with FLBAS auto-detection      │
│     │   └─ Attach namespaces to controller                   │
│     └─ Mode: select                                          │
│         └─ Verify existing namespaces                        │
│                                                               │
│  5. configure_nvmet_subsystem()                              │
│     ├─ Create subsystem in configfs                          │
│     ├─ Add namespaces to subsystem                           │
│     └─ Configure TCP ports                                   │
│                                                               │
│  6. setup_persistence()                                      │
│     ├─ Generate nvmet-cli JSON config                        │
│     ├─ Create systemd service                                │
│     └─ Enable and start service                              │
│                                                               │
│  7. validate_configuration()                                 │
│     ├─ Verify configfs structure                             │
│     ├─ Check TCP port listening                              │
│     └─ Log configuration summary                             │
│                                                               │
│  8. tearDown()                                               │
│     └─ Close SSH connection gracefully                       │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## References

- [NVMe Specification](https://nvmexpress.org/specifications/)
- [Linux NVMe Target Documentation](https://www.kernel.org/doc/html/latest/nvme/nvme-target.html)
- [nvme-cli GitHub](https://github.com/linux-nvme/nvme-cli)
- [Avocado Test Framework](https://avocado-framework.github.io/)

## License

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

## Author

Copyright: 2026 IBM
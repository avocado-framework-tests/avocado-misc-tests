# Network HTX Test

This configuration runs HTX on network interfaces for network stress testing across single or multiple systems.

## Overview

The network HTX test allows you to stress test network interfaces using HTX with automated topology detection. It includes safety features to automatically skip the default management network interface.

## Configuration File

### htx_network.yaml

Configuration for network HTX testing with build_net automation.

**Key Parameters:**
- `mdt_file`: MDT file for network (default: net.mdt)
- `host_public_ip`: Public IP address of host
- `peer_public_ip`: Public IP address of peer (for multi-system tests)
- `peer_user`: Username for peer system
- `peer_password`: Password for peer system
- `htx_host_interfaces`: Space-separated list of host interfaces
- `peer_interfaces`: Space-separated list of peer interfaces
- `time_limit`: Duration to run the test (in minutes)
- `htx_rpm_link`: URL to HTX RPM repository

**Build_net Automation Parameters:**
- `onesys_test`: 'y' for single system, 'n' for multi-system (default: 'n')
- `walk_zero`: 'y' to run WALKZERO pattern, 'n' otherwise (default: 'n')
- `force_defaults`: 'y' for default ethernet params (default: 'y')
- `use_automation`: 'y' to auto-detect topology (default: 'y')
- `seed`: Seed value for network configuration (default: '1234')

## Network Test Modes

### Single-System Test (`onesys_test: 'y'`)
- Tests network interfaces on a single system
- No peer system required
- Interfaces are looped back for testing

### Multi-System Test (`onesys_test: 'n'`)
- Tests network interfaces across two systems
- Requires peer system with SSH access
- Interfaces are connected between host and peer

## Interface Specification

**Supported Formats:**
- Interface names: `eth0 eth1 ens3 ens4`
- MAC addresses: Automatically resolved to interface names

## Safety Features

### Automatic Default Interface Protection

The test automatically:
1. Detects the default network interface via `ip route show default`
2. Removes default interface from HTX bpt file
3. Prevents testing management/SSH interface
4. Logs all modifications made to bpt file

**Example Log:**
```
Default network interface detected: eth0
Removed critical devices from bpt file: default interface: eth0
```

## Latest HTX Build_net Automation

### Automated Network Topology Detection

When `use_automation: 'y'` (default):

1. Build_net configures IP addresses on all available ethernet adapters
2. Runs automatic detection to identify network connections
3. Displays detected network topology (e.g., "en2 : en8")
4. Automatically configures netid's in bpt file
5. Runs `build_net bpt` to configure test networks
6. Verifies with `pingum` that all networks ping successfully

### Build_net Command Syntax

```bash
build_net help <onesys> <walk_zero> patent <force_defaults> <seed> <use_automation>
```

### Example Automation Output

```
Do you want automation scripts to automatically detect network topology, enter yes(y) or no(n)
y
Automation script will now try to detect your network topology.
Configuring ip address to all the available ethernet adapters on system ....
Your network setup looks like ....
en2 : en8
en4 : en5
Running build_net bpt to configure test networks ....
All networks ping ok
```

## Usage Examples

### Multi-System Test (Default with Automation)
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_network.yaml \
    -p peer_public_ip=192.168.1.20 \
    -p peer_password=mypassword \
    -p htx_host_interfaces="eth0 eth1" \
    -p peer_interfaces="eth0 eth1"
```

### Single-System Test
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_network.yaml \
    -p onesys_test=y \
    -p htx_host_interfaces="eth1 eth2"
```

### Manual Network Configuration (No Automation)
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_network.yaml \
    -p use_automation=n \
    -p peer_public_ip=192.168.1.20
```

### Custom Duration
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_network.yaml \
    -p peer_public_ip=192.168.1.20 \
    -p time_limit=60
```

## Test Phases

1. **test_start**: 
   - Setup HTX on both host and peer
   - Disable firewall
   - Flush IP addresses on test interfaces
   - Run build_net automation
   - Remove default interface from bpt file
   - Verify with pingum
   - Start HTX on both systems

2. **test_check**: 
   - Monitor test execution every 60 seconds
   - Check error logs on host and peer
   - Query device status on both systems

3. **test_stop**: 
   - Shutdown HTX on both systems
   - Restore network configuration
   - Close remote session

## Network Configuration

### Automatic Topology Detection
- Build_net automatically detects which interfaces are connected
- No manual bpt file editing required
- Automatic IP address assignment
- Verification with pingum

### Manual Configuration Fallback
If automation fails or `use_automation: 'n'`:
1. User can manually edit the bpt file
2. Run `build_net bpt` to apply manual configuration
3. Verify with `pingum`

## Requirements

- **Platform**: Power Architecture (ppc64/ppc64le)
- **Operating Systems**: RHEL, CentOS, Fedora, Ubuntu, SLES
- **HTX Installation**: RPM or Git source
- **Multi-System**: SSH access to peer system
- **Network**: Physical network connections between test interfaces

## Error Handling

The test monitors HTX error logs (`/tmp/htxerr`) on both systems and fails if:
- HTX reports any errors during execution
- Network topology setup fails
- Pingum verification fails
- SSH connection to peer fails
- HTX daemon fails to start

## Troubleshooting

### Network Topology Configuration Failed
- Verify network cables are properly connected
- Check network interfaces are up: `ip link show`
- Verify no IP conflicts exist
- Ensure firewall is disabled on both systems
- Check build_net logs for detailed error messages

### Peer Connection Failed
- Verify peer IP address is correct
- Check SSH credentials
- Ensure peer system is accessible
- Verify firewall allows SSH

### Pingum Verification Failed
- Check physical network connections
- Verify interfaces are up
- Check for IP conflicts
- Review build_net output for errors
- Try manual configuration with `use_automation: n`

### Default Interface Warning
- This is normal - default interface is automatically excluded for safety
- Specify other interfaces in `htx_host_interfaces` parameter
- Ensure test interfaces are different from management interface

## Best Practices

1. **Always exclude default interface** - Automatic, but verify in logs
2. **Use dedicated test interfaces** - Don't use management/SSH interface
3. **Physical connections** - Ensure cables are properly connected
4. **Automation first** - Use `use_automation: y` for easier setup
5. **Monitor both systems** - Check logs on host and peer
6. **Long duration tests** - Network tests can run for extended periods

## Manual Configuration

If you need to manually configure network topology:

1. Set `use_automation: n`
2. Edit `/tmp/bpt` file with your network configuration
3. Run `build_net bpt` to apply configuration
4. Verify with `pingum`
5. Start HTX test

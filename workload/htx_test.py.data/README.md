# Unified HTX Test Suite

This directory contains the unified HTX test framework that consolidates generic, storage, and network HTX testing into a single test file.

## Quick Start

The unified test (`workload/htx_test.py`) automatically detects the test type based on parameters or you can explicitly specify it.

## Test Types

### 1. Generic HTX Test
For memory, CPU, and general system stress testing.

📖 **See [README_generic.md](README_generic.md) for detailed documentation**

**Quick Example:**
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_generic.yaml
```

### 2. Storage HTX Test
For block device stress testing with automatic root disk protection.

📖 **See [README_storage.md](README_storage.md) for detailed documentation**

**Quick Example:**
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_storage.yaml \
    -p htx_disks="sdb sdc"
```

### 3. Network HTX Test
For network interface stress testing with automated topology detection.

📖 **See [README_network.md](README_network.md) for detailed documentation**

**Quick Example:**
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_network.yaml \
    -p peer_public_ip=192.168.1.20 \
    -p peer_password=mypassword
```

## Configuration Files

- `htx_generic.yaml` - Generic HTX configuration
- `htx_storage.yaml` - Storage HTX configuration
- `htx_storage_all_devices.yaml` - All devices storage configuration
- `htx_network.yaml` - Network HTX configuration

## Safety Features

- ✅ Automatic root disk detection and exclusion (storage tests)
- ✅ Automatic default interface detection and exclusion (network tests)
- ✅ Latest HTX build_net automation support
- ✅ Comprehensive error handling and logging

## Requirements

- Platform: Power Architecture (ppc64/ppc64le)
- Operating Systems: RHEL, CentOS, Fedora, Ubuntu, SLES
- HTX Installation: RPM or Git source

## Support

For detailed information about each test type, refer to the specific README files:
- [Generic HTX Documentation](README_generic.md)
- [Storage HTX Documentation](README_storage.md)
- [Network HTX Documentation](README_network.md)

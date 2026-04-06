# Storage HTX Test

## Overview

HTX (Hardware Test eXecutive) is a test tool suite used by various System p validation labs to verify hardware design. It is used during processor bring up, hardware system integration, I/O Verification (IOV), characterization and manufacturing. The goal of HTX is to stress test the system by exercising all hardware components concurrently to uncover any hardware design flaws and hardware-hardware or hardware-software interaction issues.

The storage HTX test allows you to stress test specific block devices or all available disks using HTX. It includes safety features to automatically skip the root/boot disk.

HTX runs on AIX, Bare Metal Linux (BML) and distribution Linux. HTX offers a lightweight HTX daemon (HTXD) which supports command line interface and menu-based user interactive interface.

## Configuration Files

### htx_storage.yaml
Configuration for testing specific block devices.

**Key Parameters:**
- `htx_disks`: Space-separated list of block devices to test (e.g., 'sdb sdc')
- `all`: Set to False to test specific disks only (default: False)
- `mdt_file`: MDT file for storage (default: mdt.hd)
- `time_limit`: Duration to run the test in hours (default: 1)
- `run_type`: Installation method - 'rpm' or 'git' (default: 'rpm')
- `htx_rpm_link`: URL to HTX RPM repository (required for rpm installation)

### htx_storage_all_devices.yaml
Configuration for testing all available disks in the MDT file.

**Key Parameters:**
- `all`: Set to True to test all disks (overrides htx_disks parameter)
- `time_limit`: 24 hours by default for comprehensive testing

## Device Specification

**Supported Formats:**
- **Device names**: `sda sdb sdc`
- **NVMe devices**: `nvme0n1 nvme1n1` (must pass namespaces, not just nvme0)
- **Device mapper**: `dm-0 dm-1`
- **Multipath**: `/dev/mapper/mpathX`
- **By-id**: `/dev/disk/by-id/...`
- **By-path**: `/dev/disk/by-path/...`
- **By-uuid**: `/dev/disk/by-uuid/...`

**Input Format:**
```yaml
htx_disks: '/dev/sdb /dev/sdc'  # Standard disks
htx_disks: '/dev/mapper/mpatha /dev/mapper/mpathb'  # Multipath
htx_disks: 'nvme0n1 nvme1n1'  # NVMe namespaces
```

## Safety Features

### Automatic Root Disk Protection

The test automatically:
1. Detects the root/boot disk via `df /boot` or `df /`
2. Excludes root disk from the test device list
3. Handles multipath and NVMe devices correctly
4. Logs warnings when root disk is excluded
5. Cancels test if no valid disks remain after exclusion

**Example Log:**
```
Root/boot disk detected: sda
Skipping root/boot disk: sda
Block devices to test: sdb sdc sdd
```

## Usage Examples

### Test Specific Disks
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_storage.yaml \
    -p htx_disks="sdb sdc"
```

### Test NVMe Devices
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_storage.yaml \
    -p htx_disks="nvme0n1 nvme1n1"
```

### Test Multipath Devices
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_storage.yaml \
    -p htx_disks="/dev/mapper/mpatha /dev/mapper/mpathb"
```

### Test All Disks (24-hour stress)
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_storage_all_devices.yaml
```

### Custom Duration
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_storage.yaml \
    -p htx_disks="sdb sdc" \
    -p time_limit=4
```

### Git Installation
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_storage.yaml \
    -p htx_disks="sdb sdc" \
    -p run_type="git"
```

## Test Phases

1. **test_start**: 
   - Setup HTX
   - Detect and exclude root disk
   - Create/select MDT file (e.g., mdt.hd, mdt.io)
   - Verify devices in MDT
   - Suspend all devices
   - Activate specified devices
   - Start HTX

2. **test_check**: 
   - Monitor test execution every 60 seconds
   - Check error logs
   - Query device status

3. **test_stop**: 
   - Suspend active devices
   - Shutdown HTX
   - Cleanup

## Device Management

### Device Activation
- Only specified devices are activated for testing
- All other devices in MDT are suspended
- Verification ensures devices are active before starting

### Device Verification
- Checks if specified devices exist in MDT file
- Validates device activation status
- Fails test if devices cannot be activated

## Requirements

- **Platform**: Power Architecture (ppc64/ppc64le)
- **Operating Systems**: RHEL, CentOS, Fedora, Ubuntu, SLES
- **HTX Installation**: RPM or Git source
- **Permissions**: Root access required for disk operations
- **Dependencies**: 
  - For RPM: gcc-c++, ncurses-devel, tar
  - For Ubuntu: libncurses5, g++, ncurses-dev, libncurses-dev, tar
  - For SUSE: libncurses6, gcc-c++, ncurses-devel, tar

## Error Handling

The test monitors HTX error logs (`/tmp/htxerr`) and fails if:
- HTX reports any errors during execution
- Devices fail to activate
- Devices are not found in MDT file
- No valid devices remain after excluding root disk

## Troubleshooting

### Device Not Found in MDT
- Verify device names are correct
- Check devices exist: `ls -l /dev/`
- Ensure devices are not in use
- Try creating MDT manually: `htxcmdline -createmdt -mdt mdt.hd`

### Device Activation Fails
- Check device is not mounted
- Verify device is not part of RAID/LVM
- Ensure device has no active I/O
- Check HTX logs for detailed errors

### Root Disk Warning
- This is normal - root disk is automatically excluded for safety
- Specify other disks in `htx_disks` parameter
- Use `all: True` to test all non-root disks

### All Devices Excluded
- Occurs when only root disk is specified
- Add additional disks to test
- Verify other disks are available: `lsblk`

## Best Practices

1. **Always exclude root disk** - Automatic, but verify in logs
2. **Unmount test disks** - Ensure disks are not mounted before testing
3. **Backup data** - HTX will overwrite data on test disks
4. **Monitor logs** - Check `/tmp/htxerr` regularly during test execution
5. **Long duration tests** - Use `htx_storage_all_devices.yaml` for comprehensive testing
6. **SMT changes** - The test can change SMT values while HTX is running based on YAML configuration

## Additional Notes

- The test also supports changing SMT (Simultaneous Multi-Threading) values while HTX is running, based on input from the user in the YAML file
- HTX exercises all hardware components concurrently to uncover hardware design flaws and interaction issues
- For NVMe drives, always pass namespaces (nvme0n1, nvme1n1) not just the controller (nvme0)

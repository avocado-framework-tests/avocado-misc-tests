# Spyre EEH (Enhanced Error Handling) Test

## Overview

This test suite validates EEH (Enhanced Error Handling) functionality for Spyre AIU (AI Unit) devices on IBM Power systems. EEH is a PowerPC-specific feature that provides error detection and recovery for PCIe devices, ensuring system reliability and availability.

## Table of Contents

- [Features](#features)
- [Test Scenarios](#test-scenarios)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Usage](#usage)
- [Test Details](#test-details)
- [Examples](#examples)

## Features

- **EEH Enablement Verification**: Validates EEH is enabled on the system
- **Max Freeze Count Validation**: Verifies EEH max freeze count configuration
- **Error Injection**: Injects EEH errors to single or multiple PCI devices
- **Automatic PCI Detection**: Detects Spyre PCI buses using `lsslot` command
- **Kernel Message Validation**: Monitors dmesg for EEH event messages
- **Device Recovery Verification**: Confirms devices remain accessible after EEH events
- **Container Restart Validation**: Optional validation of container restart after EEH

## Test Scenarios

### 1. EEH Enablement Check (`test_eeh_enabled`)

**Purpose**: Verify that EEH is enabled on the system

**Validation**: 
- Checks `/sys/kernel/debug/powerpc/eeh_enable` for value `0x1`

**Expected Result**: EEH should be enabled (value = 0x1)

### 2. EEH Max Freeze Count Validation (`test_eeh_max_freezes`)

**Purpose**: Verify EEH max freeze count configuration

**Validation**:
- Checks `/sys/kernel/debug/powerpc/eeh_max_freezes` matches expected value

**Expected Result**: Value should match the configured `MAX_FREEZES` parameter (default: 5)

### 3. Single PCI Device EEH Injection (`test_eeh_inject_single_pci`)

**Purpose**: Test EEH error injection and recovery for a single PCIe device

**Steps**:
1. Inject EEH error to the first configured PCI device
2. Validate EEH message appears in kernel logs (dmesg)
3. Validate device is still present in `lspci` output
4. Validate container restart (if configured)

**Expected Result**: Device should recover and remain accessible

### 4. Multiple PCI Devices EEH Injection (`test_eeh_inject_all_pci`)

**Purpose**: Test EEH error injection and recovery for all configured PCIe devices

**Steps**:
1. Sequentially inject EEH errors to each configured PCI device
2. Validate EEH message in kernel logs for each device
3. Validate each device is still present in `lspci` output
4. Validate container restart after all injections (if configured)

**Expected Result**: All devices should recover and remain accessible

## Prerequisites

### System Requirements

- **Platform**: IBM Power system (ppc64/ppc64le architecture)
- **Kernel**: Linux kernel with EEH support enabled
- **Access**: Root/sudo access for EEH operations
- **debugfs**: Mounted at `/sys/kernel/debug`

### Software Requirements

- Avocado Test Framework
- Python 3.6+
- `lspci` utility (pciutils package)
- `podman` (if testing container restart)

### Kernel Configuration

Ensure the following kernel parameters are set:

```bash
# Check if EEH is enabled
cat /sys/kernel/debug/powerpc/eeh_enable
# Should return: 0x1

# Check max freeze count
cat /sys/kernel/debug/powerpc/eeh_max_freezes
# Should return: 5 (or your configured value)
```

## Configuration

### YAML Parameters

Configure the test using a YAML file (e.g., `spyre_eeh_test.py.data/spyre_eeh.yaml`):

```yaml
# Space-separated PCI addresses for AIU cards
# Format: XXXX:XX:XX.X (domain:bus:device.function)
PCI_ADDRESSES: "0382:60:00.0 0382:70:00.0 0383:60:00.0 0383:70:00.0"

# Expected EEH max freeze count (default: 5)
MAX_FREEZES: 5

# Optional: Container name for restart validation
CONTAINER_NAME: "spyre-vllm-container"
```

### Parameter Details

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `PCI_ADDRESSES` | String | Yes | - | Space-separated list of PCI addresses to test |
| `MAX_FREEZES` | Integer | No | 5 | Expected EEH max freeze count |
| `CONTAINER_NAME` | String | No | "" | Container name for restart validation (optional) |

## Usage

### Basic Test Execution

Run all EEH tests:

```bash
avocado run spyre_eeh_test.py --mux-yaml spyre_eeh_test.py.data/spyre_eeh.yaml
```

### Run Specific Tests

Run only EEH enablement check:

```bash
avocado run spyre_eeh_test.py:SpyreEEHTest.test_eeh_enabled \
    --mux-yaml spyre_eeh_test.py.data/spyre_eeh.yaml
```

Run only single PCI injection test:

```bash
avocado run spyre_eeh_test.py:SpyreEEHTest.test_eeh_inject_single_pci \
    --mux-yaml spyre_eeh_test.py.data/spyre_eeh.yaml
```

Run only multiple PCI injection test:

```bash
avocado run spyre_eeh_test.py:SpyreEEHTest.test_eeh_inject_all_pci \
    --mux-yaml spyre_eeh_test.py.data/spyre_eeh.yaml
```

### Advanced Options

Run with verbose output:

```bash
avocado run spyre_eeh_test.py --mux-yaml spyre_eeh_test.py.data/spyre_eeh.yaml \
    --show-job-log
```

Run with custom results directory:

```bash
avocado run spyre_eeh_test.py --mux-yaml spyre_eeh_test.py.data/spyre_eeh.yaml \
    --job-results-dir /tmp/eeh-results
```

## Test Details

### EEH Error Injection Process

#### How EEH Injection Works

1. **Error Injection**: Write PCI address to `/sys/kernel/debug/powerpc/eeh_dev_break`
   ```bash
   echo "0382:60:00.0" > /sys/kernel/debug/powerpc/eeh_dev_break
   ```

2. **Kernel Detection**: Kernel detects the injected error and logs it
   ```
   vfio-pci 0382:60:00.0: Going to break:
   ```

3. **Recovery**: EEH subsystem attempts to recover the device
   - Device is temporarily isolated
   - Device state is saved
   - Device is reset
   - Device state is restored
   - Device is brought back online

4. **Validation**: Test verifies device is still accessible via `lspci`

### Expected Kernel Messages

After EEH injection, you should see messages like:

```
[timestamp] vfio-pci 0382:60:00.0: Going to break:
[timestamp] EEH: Frozen PE#xxx on PHB#xxx detected
[timestamp] EEH: PE location: N/A, PHB location: N/A
[timestamp] EEH: This PCI device has failed 1 time in the last hour
[timestamp] EEH: Notify device driver to resume
```

### Example Output

```
JOB ID     : <job-id>
JOB LOG    : /home/user/avocado/job-results/job-<timestamp>/job.log
 (1/4) spyre_eeh_test.py:SpyreEEHTest.test_eeh_enabled: PASS (2.34 s)
 (2/4) spyre_eeh_test.py:SpyreEEHTest.test_eeh_max_freezes: PASS (1.12 s)
 (3/4) spyre_eeh_test.py:SpyreEEHTest.test_eeh_inject_single_pci: PASS (45.67 s)
 (4/4) spyre_eeh_test.py:SpyreEEHTest.test_eeh_inject_all_pci: PASS (180.23 s)
RESULTS    : PASS 4 | ERROR 0 | FAIL 0 | SKIP 0 | WARN 0 | INTERRUPT 0 | CANCEL 0
```

## Related Documentation

- [IBM Power EEH Documentation](https://www.kernel.org/doc/html/latest/powerpc/eeh-pci-error-recovery.html)
- [Spyre AIU Documentation](https://www.ibm.com/docs/en/power-systems)
- [Avocado Test Framework](https://avocado-framework.readthedocs.io/)
- [Linux PCI Error Recovery](https://www.kernel.org/doc/Documentation/PCI/pci-error-recovery.txt)

## Support

For issues or questions:

- Check Avocado test logs in `~/avocado/job-results/`
- Review kernel logs: `dmesg | grep -i eeh`
- Contact IBM Power support for EEH-related issues
- Report test framework issues to the Avocado project

## Author

Abdul Haleem <abdhalee@linux.vnet.ibm.com>

## License

GNU General Public License v2.0 or later

# Spyre EEH (Enhanced Error Handling) Test

## Overview

This test suite validates EEH (Enhanced Error Handling) functionality for Spyre AIU (AI Unit) devices on IBM Power systems. EEH is a PowerPC-specific feature that provides error detection and recovery for PCIe devices, ensuring system reliability and availability.

## Features

- **EEH Enablement & Configuration Verification**: Validates EEH is enabled and max freeze count is properly set
- **Linux DebugFS Error Injection**: Injects EEH errors across Spyre PCI devices via `eeh_dev_break`
- **RTAS errinjct Error Injection**: Injects `ioa-bus-error-64` errors via the `errinjct` tool across Spyre BAR memory regions and function codes
- **PHYP Console Error Injection**: Injects PCIe switch mode errors via from the FSP/PHYP console over SSH 
- **Automatic PCI Detection**: Detects Spyre PCI devices (`1014:06a7`) dynamically using `lspci`
- **Kernel Message Monitoring**: Checks `dmesg` for EEH event logs (without blocking test progression if absent)
- **PCIe Device Recovery Verification**: Confirms devices recover and remain accessible via `lspci`
- **Non-root Container & vLLM Lifecycle Validation**: Validates that non-root Podman containers transition down upon error injection, recover back to `UP` state, and vLLM application startup completes successfully (`wait_for_vllm_startup`)

## Test Scenarios

### 1. EEH Enablement & Configuration Check (`test_eeh_enabled`)

**Purpose**: Verify that EEH is enabled and maximum freeze count is configured on the system

**Validation**:
- Checks `/sys/kernel/debug/powerpc/eeh_enable` for value `0x1`
- Checks `/sys/kernel/debug/powerpc/eeh_max_freezes` matches the configured `MAX_FREEZES` parameter (default: 5)

**Expected Result**: EEH is enabled (`0x1`) and max freeze count matches expected value

---

### 2. PCI Devices EEH Injection via Linux DebugFS (`test_linux_eeh`)

**Purpose**: Test EEH error injection and recovery sequentially across all configured/detected Spyre PCIe devices

**Steps**:
1. Pre-check non-root user Podman containers are `UP` and running
2. Sequentially inject EEH error to each PCI device via `/sys/kernel/debug/powerpc/eeh_dev_break`
3. Validate containers go `DOWN` upon error injection
4. Check kernel logs (`dmesg`) for EEH event messages
5. Validate each device recovers and is present in `lspci` output
6. Validate container recovers back to `UP` state and vLLM starts up after each/all injections

**Expected Result**: All PCIe devices recover, containers restart, and vLLM service returns to healthy state

---

### 3. RTAS errinjct Tool EEH Injection (`test_errinjct_tool_eeh`)

**Purpose**: Inject `ioa-bus-error-64` RTAS errors using the `errinjct` tool across Spyre BAR memory regions and configurable function codes

**Steps**:
1. Verify `errinjct` is installed (`powerpc-utils`)
2. For each Spyre device, resolve the physical slot location code via `lspci -v` or `lsslot -c pci`
3. Retrieve physical bus addresses for Spyre BAR regions via `lspci -bvs`; apply fixed hardware masks:
   - Region 0 (4 MB): mask `0xffffffffffc00000`
   - Region 2 (2 GB): mask `0xffffffff80000000`
   - Region 4 (32 MB): mask `0xfffffffffe000000`
4. Execute `errinjct ioa-bus-error-64 -k 1 -p <loc_code> -a <bus_addr> -m <mask> -f <func>` for one region/function per card
5. Validate container goes `DOWN`, check `dmesg` for EEH messages, verify PCI device presence in `lspci`, and confirm container and vLLM recovery

**Function codes** (configurable via `ERRINJCT_FUNCTIONS` YAML parameter):

| Code | Description |
|------|-------------|
| 0    | Load Memory Address Parity |
| 1    | Load Memory Data Parity |
| 6    | Store Memory Address Parity |
| 7    | Store Memory Data Parity |

**Expected Result**: RTAS injection succeeds, EEH recovery completes, and container/vLLM return to healthy state

---

### 4. PHYP Console EEH Switch Mode Error Injection (`test_phyp_eeh`)

**Purpose**: Inject PCIe switch mode errors from the FSP/PHYP console using `xmswitchmodeinjecterror`

**Steps**:
1. Ensure container and vLLM are healthy before injection
2. Connect to PHYP console via SSH on port 2201 using FSP credentials from YAML
3. Run `xmquery -q allslots -d 2` to discover Switch DRC values for each Spyre PCI device
4. Inject error on each unique Switch DRC: `xmswitchmodeinjecterror -d <switch_drc> -p 0 UERR -b 17 -ds`
5. Verify `Port Error Injection` appears in PHYP command output
6. Check the **last 2 new dmesg lines** for EEH kernel events (avoids false matches from stale/old log entries)
7. Verify PCI device presence via `lspci`
8. Validate container recovers to `UP` state and vLLM starts up successfully

**Note**: `FSP_IP`, `FSP_USER`, and `FSP_PASSWORD` must all be set in the YAML; test is skipped if any are missing.

**Expected Result**: Switch mode error injection completes, EEH recovery observed in dmesg, devices and containers recover successfully

---

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
- `powerpc-utils` package with `errinjct` (required for `test_errinjct_tool_eeh`)
- SSH access to FSP on port 2201 (required for `test_phyp_eeh`)
- `pexpect` Python package (required for `test_phyp_eeh`)

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

Configure the test using `spyre_EEH_test.py.data/spyre_EEH_test.yaml`.

# EEH Parameters
- `PCI_ADDRESSES`: Space-separated PCI addresses of Spyre AIU cards (e.g. "0382:60:00.0 0382:70:00.0"); auto-discovered if empty
- `MAX_FREEZES`: Expected value in `/sys/kernel/debug/powerpc/eeh_max_freezes` (default: 5)

# errinjct Parameters
- `ERRINJCT_FUNCTIONS`: Space-separated errinjct function codes for `ioa-bus-error-64` injection (default: "0 1 6 7")

# FSP / PHYP Parameters
- `FSP_IP`: FSP IP address for PHYP console SSH connection (port 2201)
- `FSP_USER`: FSP SSH username
- `FSP_PASSWORD`: FSP SSH password

# User Configuration
- `USER`: Non-root user running Spyre container workloads (e.g. "senuser"); auto-detected if empty

## Usage

### Basic Test Execution

Run all EEH tests:

```bash
avocado run spyre_EEH_test.py --mux-yaml spyre_EEH_test.py.data/spyre_EEH_test.yaml
```

### Run Specific Tests

```bash
# EEH enablement check only
avocado run spyre_EEH_test.py:SpyreEEHTest.test_eeh_enabled \
    --mux-yaml spyre_EEH_test.py.data/spyre_EEH_test.yaml

# Linux debugfs EEH injection
avocado run spyre_EEH_test.py:SpyreEEHTest.test_linux_eeh \
    --mux-yaml spyre_EEH_test.py.data/spyre_EEH_test.yaml

# RTAS errinjct EEH injection
avocado run spyre_EEH_test.py:SpyreEEHTest.test_errinjct_tool_eeh \
    --mux-yaml spyre_EEH_test.py.data/spyre_EEH_test.yaml

# PHYP console EEH injection
avocado run spyre_EEH_test.py:SpyreEEHTest.test_phyp_eeh \
    --mux-yaml spyre_EEH_test.py.data/spyre_EEH_test.yaml
```

### Advanced Options

Run with verbose output:

```bash
avocado run spyre_EEH_test.py --mux-yaml spyre_EEH_test.py.data/spyre_EEH_test.yaml \
    --show-job-log
```

Run with custom results directory:

```bash
avocado run spyre_EEH_test.py --mux-yaml spyre_EEH_test.py.data/spyre_EEH_test.yaml \
    --job-results-dir /tmp/eeh-results
```

### Example Output

```
JOB ID     : <job-id>
JOB LOG    : /home/user/avocado/job-results/job-<timestamp>/job.log
 (1/4) spyre_EEH_test.py:SpyreEEHTest.test_eeh_enabled:          PASS (2.34 s)
 (2/4) spyre_EEH_test.py:SpyreEEHTest.test_linux_eeh:            PASS (180.23 s)
 (3/4) spyre_EEH_test.py:SpyreEEHTest.test_errinjct_tool_eeh:    PASS (240.10 s)
 (4/4) spyre_EEH_test.py:SpyreEEHTest.test_phyp_eeh:             PASS (300.45 s)
RESULTS    : PASS 4 | ERROR 0 | FAIL 0 | SKIP 0 | WARN 0 | INTERRUPT 0 | CANCEL 0
```

## Test Details

### EEH Error Injection Process

#### Linux DebugFS Injection

```bash
echo "0382:60:00.0" > /sys/kernel/debug/powerpc/eeh_dev_break
```

#### RTAS errinjct Injection

```bash
errinjct open
errinjct ioa-bus-error-64 -k 1 -p <loc_code> -a <bus_addr> -m <mask> -f <func>
errinjct close -k 1
```

#### PHYP Console Injection

```
# SSH to FSP on port 2201, then:
xmquery -q allslots -d 2
xmswitchmodeinjecterror -d <switch_drc> -p 0 UERR -b 17 -ds
```

### dmesg Validation Behaviour

All tests record the dmesg line count before injection and check only new lines emitted after that point. The **PHYP test additionally restricts the check to the last 2 new lines** — this prevents false-positive matches against older EEH messages that may already be present in the ring buffer from prior test runs or system events.

### Expected Kernel Messages

After EEH injection, you may see messages like:

```
[timestamp] vfio-pci 0382:60:00.0: Going to break:
[timestamp] EEH: Frozen PE#xxx on PHB#xxx detected
[timestamp] EEH: PE location: N/A, PHB location: N/A
[timestamp] EEH: This PCI device has failed 1 time in the last hour
[timestamp] EEH: Notify device driver to resume
[timestamp] EEH: Beginning recovery
[timestamp] EEH: Recovery successful
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
Sai Janani C <jananic@linux.ibm.com>

## License

GNU General Public License v2.0 or later

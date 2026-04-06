# PPC64_CPU Test Suite

## Overview
Comprehensive test suite for PowerPC `ppc64_cpu` utility, testing SMT (Simultaneous Multi-Threading) operations, core hotplug functionality, and system state validation.

## Test Coverage

### Original Tests (Existing)
1. **test_build_upstream** - Build and install upstream powerpc-utils
2. **test_cmd_options** - Test various ppc64_cpu command options
3. **test_smt_loop** - Loop test for SMT on/off operations
4. **test_single_core_smt** - Test SMT changes with single core online

### New Enhanced Tests

#### 1. test_smt_with_core_operations
Tests SMT changes with various core configurations:
- Tests different core counts: 10%, 25%, 50%, 75%, 100% of total cores
- For each core count, tests all SMT values: off, 2, 4, on
- Validates system state after each operation
- Ensures CPU count = Cores × SMT threads

**Use Case**: Verify SMT operations work correctly with different core configurations

#### 2. test_parallel_smt_core_stress
Stress test with random SMT and core operations:
- Performs random operations: SMT change, core change, or both
- Validates system state after each operation
- Cross-validates that SMT changes don't affect core count
- Cross-validates that core operations don't change SMT state
- Configurable iterations via YAML

**Use Case**: Stress testing to catch race conditions and state inconsistencies

#### 3. test_core_range_operations
Tests core operations with specific counts:
- Tests with 1, 2, 4, 8 cores (or max available)
- Validates core count matches expected
- Verifies system state consistency

**Use Case**: Verify core hotplug operations work correctly

## New Helper Methods

### Validation Helpers

#### parse_lscpu_output()
- Parses `lscpu` output to get online CPU count
- Handles CPU ranges (e.g., "0-79" or "0-39,80-119")
- Returns total online CPU count

#### get_online_cpus_from_sysfs()
- Reads `/sys/devices/system/cpu/online`
- Parses CPU ranges
- Returns online CPU count

#### get_online_cpus_from_proc()
- Reads `/proc/cpuinfo`
- Counts processor entries
- Returns CPU count

#### parse_ppc64_cpu_info()
- Parses `ppc64_cpu --info` output
- Extracts per-core thread information
- Categorizes cores as online/offline
- Detects SMT inconsistencies
- Returns detailed core information dictionary

#### verify_system_state()
- Comprehensive system state validation
- Validates SMT mode matches expected
- Validates core count matches expected
- Checks SMT consistency among online cores
- Verifies CPU count formula: Online CPUs = Online Cores × SMT threads
- Cross-validates CPU counts from multiple sources (lscpu, sysfs, /proc/cpuinfo)
- Logs detailed validation results

#### get_cores_info()
- Gets current cores online and cores present
- Returns dictionary with core information

## Key Features

### 1. Dynamic Core Count
- No hardcoded values
- Automatically detects total cores from system
- Calculates test values as percentages of total cores

### 2. Comprehensive Validation
- Validates from multiple sources (lscpu, sysfs, /proc/cpuinfo, ppc64_cpu)
- Cross-validates consistency across sources
- Checks mathematical relationship: CPUs = Cores × SMT

### 3. Proper Offline Core Handling
- Offline cores (0 threads) are treated as VALID
- Only online cores checked for SMT consistency
- Prevents false "inconsistent state" errors

### 4. Cross-Validation
- Verifies SMT changes don't affect core count
- Verifies core operations don't change SMT state
- Ensures operations are independent

## Configuration (ppc64_cpu_test.yaml)

### Parameters

```yaml
# Original ppc64_cpu_test.py parameters
test_loop: 10                    # Iterations for test_smt_loop

# Number of iterations for basic tests
iteration: 5

# Iteration parameters
stress_iterations: 20            # Iterations for stress tests
parallel_iterations: 3           # Iterations for parallel operations
random_iterations: 50            # Iterations for random stress test
num_parallel_threads: 4          # Number of parallel threads

# Test execution flags (set to false to skip specific tests)
run_all_smt_operations: true
run_dynamic_core_operations: true
run_smt_core_interaction: true
run_random_stress: true
run_parallel_operations: true
run_progressive_core_online: true
run_specific_cores_offline: true

# Verification options
enable_comprehensive_verification: true
verify_after_each_operation: true

# Timing options (in seconds)
sleep_after_smt_change: 1
sleep_after_core_change: 1
sleep_between_operations: 0.3

# Logging options
verbose_logging: true
log_dmesg: true

# Build type configuration (original ppc64_cpu_test.py feature)
run_type: !mux
    upstream:
        ppcutils_url: 'https://github.com/ibm-power-utilities/powerpc-utils/archive/refs/heads/master.zip'
        type: 'upstream'
    distro:
        type: 'distro'
```

### Parameter Details

**Iteration Parameters:**
- `test_loop`: Number of iterations for original SMT loop test
- `iteration`: Number of iterations for basic tests
- `stress_iterations`: Used by stress-related tests
- `parallel_iterations`: Number of iterations in parallel operation tests
- `random_iterations`: Number of iterations in random stress test
- `num_parallel_threads`: Number of concurrent threads in parallel tests

**Test Execution Flags:**
- Set any flag to `false` to skip that specific test
- Useful for running only specific test scenarios
- All tests enabled by default

**Timing Options:**
- Adjust sleep durations based on system responsiveness
- Faster systems may use shorter sleep times
- Slower systems may need longer sleep times

**Logging Options:**
- `verbose_logging`: Enables detailed logging output
- `log_dmesg`: Captures dmesg output for debugging

**Build Type:**
- `upstream`: Test with upstream powerpc-utils from GitHub
- `distro`: Test with distribution-provided powerpc-utils

## Usage Examples

### Run all tests
```bash
avocado run ppc64_cpu_test.py
```

### Run specific test
```bash
avocado run ppc64_cpu_test.py:PPC64Test.test_smt_with_core_operations
```

### Run with specific variant
```bash
avocado run ppc64_cpu_test.py --mux-yaml ppc64_cpu_test.py.data/ppc64_cpu_test.yaml --mux-filter-only /run/test_variants/stress
```

### Run stress test with custom iterations
```bash
avocado run ppc64_cpu_test.py:PPC64Test.test_parallel_smt_core_stress -p stress_iterations=50
```

### Run with upstream powerpc-utils
```bash
avocado run ppc64_cpu_test.py --mux-yaml ppc64_cpu_test.py.data/ppc64_cpu_test.yaml --mux-filter-only /run/run_type/upstream
```

## Expected Output

### Successful Test
```
SYSTEM STATE VERIFICATION
============================================================
Current SMT mode: 4
Cores online: 10
Online CPUs (lscpu): 40
Online CPUs (sysfs): 40
Online CPUs (/proc/cpuinfo): 40
Total cores detected: 20
Online cores: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
Offline cores: [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
============================================================
✓ VALIDATION PASSED
============================================================
```

### Failed Test (Example)
```
SYSTEM STATE VERIFICATION
============================================================
Current SMT mode: 4
Cores online: 10
Online CPUs (lscpu): 38
...
ERROR: CPU count mismatch! Expected: 40 (cores=10 × smt=4), Got: 38
============================================================
✗ VALIDATION FAILED
============================================================
```

## Validation Logic

### SMT Consistency Check
- Only checks online cores (cores with >0 threads)
- Offline cores (0 threads) are excluded from consistency check
- All online cores must have same number of threads

### CPU Count Formula
```
Online CPUs = Online Cores × SMT threads per core
```

### Multi-Source Validation
- lscpu: Parses "On-line CPU(s) list"
- sysfs: Reads /sys/devices/system/cpu/online
- /proc/cpuinfo: Counts processor entries
- All sources should report same count

## Requirements

- PowerPC architecture (ppc64/ppc64le)
- powerpc-utils package installed
- Root/sudo privileges (for SMT and core operations)
- Avocado test framework

## Troubleshooting

### "Machine is not SMT capable"
- System doesn't support SMT
- Test will be cancelled

### "Inconsistent state" at startup
- System has mixed ST and SMT cores
- Test will be cancelled
- Check system configuration

### Validation failures
- Check dmesg for kernel messages
- Verify no other processes changing SMT/cores
- Ensure sufficient permissions

## Technical Details

### SMT Values
- `off` or `1`: Single thread per core
- `2`: 2 threads per core
- `4`: 4 threads per core
- `on`: Maximum threads (system dependent)

### Core Operations
- `--cores-on=N`: Online N cores
- `--cores-on=all`: Online all cores
- `--cores-present`: Show total cores
- `--cores-off=N`: Offline N cores

## Author
- Original: Narasimhan V <sim@linux.vnet.ibm.com>
- Enhanced: Samir M <samir@linux.ibm.com>

## License
GNU General Public License v2.0

# PPC64_CPU Test Suite

## Overview
Comprehensive test suite for PowerPC `ppc64_cpu` utility, testing SMT (Simultaneous Multi-Threading) operations, core hotplug functionality, and system state validation.

## Recent Updates (PR #3124)

### Code Improvements
1. **Simplified Configuration**: YAML parameters grouped into logical categories (functional, stress, verification, timing, logging)
2. **Framework Integration**: Replaced custom CPU counting functions with avocado's `cpu.online_count()`
3. **Cleaner Code**: Removed duplicate failure tracking, using single `self.failures` list
4. **Optimized Tests**: Simplified `test_cmd_options()` to focus on DSCR testing only
5. **Enhanced Cleanup**: Improved `tearDown()` to restore both cores and SMT state

## Test Coverage

### Original Tests
1. **test_build_upstream** - Build and install upstream powerpc-utils
2. **test_cmd_options** - Tests DSCR (Data Stream Control Register) functionality
   - *Note: SMT, core, subcore, and threads_per_core tests now covered by comprehensive test methods*
3. **test_smt_loop** - Loop test for SMT on/off operations
4. **test_single_core_smt** - Test SMT changes with single core online

### Enhanced Tests

#### 1. test_all_smt_operations
Tests ALL SMT operations dynamically:
- Tests all possible SMT values: off, 2, 3, 4, ..., max_smt, on
- No hardcoded SMT values - adapts to system capabilities
- Validates system state after each SMT change
- Ensures CPU count = Cores × SMT threads

**Use Case**: Comprehensive SMT functionality validation

#### 2. test_dynamic_core_operations
Tests core online/offline operations with dynamically generated scenarios:
- Tests with specific percentages: 10%, 25%, 50%, 75%, 100% of total cores
- Tests edge cases: single core, two cores
- Validates core count matches expected
- *Note: Focuses solely on core operations without SMT changes*

**Use Case**: Verify core hotplug operations work correctly

#### 3. test_smt_with_core_operations
Tests SMT changes with various core configurations:
- Tests different core counts: 10%, 25%, 50%, 75%, 100% of total cores
- For each core count, tests SMT values: off, 2, 4, on
- Validates system state after each operation
- *Note: For combined SMT+core testing*

**Use Case**: Verify SMT operations work correctly with different core configurations

#### 4. test_smt_core_interaction
Tests interaction between SMT and core operations:
- Validates that SMT changes don't affect core count
- Validates that core operations don't change SMT state
- Ensures operations are independent
- Configurable iterations via YAML

**Use Case**: Verify independence of SMT and core operations

#### 5. test_random_stress
Random stress test with all possible SMT states and core configurations:
- Performs random operations: SMT change, core change, or verify
- Validates system state after each operation
- Cross-validates operation independence
- Configurable iterations via YAML

**Use Case**: Stress testing to catch race conditions and state inconsistencies

#### 6. test_progressive_core_online_with_smt
Progressive test starting with minimal cores:
- Starts with 1 core, tests all SMT operations
- Progressively brings cores online (2, 3, half, three-quarter, all)
- Tests all SMT operations at each core count
- Validates cores don't change during SMT operations

**Use Case**: Verify SMT operations work correctly as cores are progressively enabled

#### 7. test_specific_cores_offline_with_smt
Advanced test with randomly offline specific cores:
- Randomly selects 20-40% of cores to offline
- Performs all SMT operations with offline cores
- Validates offline cores remain offline after SMT changes
- Multiple iterations with different offline core combinations

**Use Case**: Verify SMT operations don't affect offline core state

## Helper Methods

### Validation Helpers

#### parse_ppc64_cpu_info()
- Parses `ppc64_cpu --info` output
- Extracts per-core thread information
- Categorizes cores as online/offline
- Detects SMT inconsistencies
- Returns detailed core information dictionary

#### verify_system_state()
- Comprehensive system state validation using `cpu.online_count()`
- Validates SMT mode matches expected
- Validates core count matches expected
- Checks SMT consistency among online cores
- Verifies CPU count formula: Online CPUs = Online Cores × SMT threads
- Logs detailed validation results

#### get_cores_info()
- Gets current cores online and cores present
- Returns dictionary with core information

## Key Features

### 1. Dynamic System Adaptation
- No hardcoded values
- Automatically detects total cores and max SMT from system
- Calculates test values as percentages of total cores
- Generates all possible SMT values dynamically

### 2. Framework Integration
- Uses avocado's `cpu.online_count()` for CPU counting
- Cleaner code with better maintainability
- Reduced code duplication

### 3. Comprehensive Validation
- Validates from multiple sources using framework utilities
- Checks mathematical relationship: CPUs = Cores × SMT
- Cross-validates operation independence

### 4. Proper Offline Core Handling
- Offline cores (0 threads) are treated as VALID
- Only online cores checked for SMT consistency
- Prevents false "inconsistent state" errors

### 5. Enhanced Cleanup
- tearDown() restores both cores (to "all") and SMT (to original value)
- Provides safety net even if tests fail before their own cleanup
- Uses `ignore_status=True` for robustness

## Configuration (ppc64_cpu_test.yaml)

### Simplified Structure

The configuration has been simplified for better usability:

```yaml
# Essential parameters (visible)
test_loop: 10

functional:
  iteration: 5  # Number of iterations for functional tests

stress:
  iterations: 20  # Number of iterations for stress tests

run_type: !mux
    upstream:
        ppcutils_url: 'https://github.com/ibm-power-utilities/powerpc-utils/archive/refs/heads/master.zip'
        type: 'upstream'
    distro:
        type: 'distro'

# Advanced Configuration (commented out, uncomment to customize)
# functional:
#   run_all_smt_operations: true
#   run_dynamic_core_operations: true
#   run_smt_core_interaction: true
#
# stress:
#   parallel_iterations: 3
#   random_iterations: 50
#   num_parallel_threads: 4
#   run_random_stress: true
#   run_parallel_operations: true
#   run_progressive_core_online: true
#   run_specific_cores_offline: true
#
# verification:
#   enable_comprehensive: true
#   verify_after_each_operation: true
#
# timing:
#   sleep_after_smt_change: 1
#   sleep_after_core_change: 1
#   sleep_between_operations: 0.3
#
# logging:
#   verbose: true
#   log_dmesg: true
```

### Parameter Categories

**Functional Tests:**
- `iteration`: Number of iterations for basic functional tests
- Test execution flags to enable/disable specific functional tests

**Stress Tests:**
- `iterations`: Number of stress test iterations
- `parallel_iterations`: Iterations for parallel operations
- `random_iterations`: Iterations for random stress test
- `num_parallel_threads`: Number of concurrent threads
- Test execution flags to enable/disable specific stress tests

**Verification Options:**
- `enable_comprehensive`: Enable comprehensive validation
- `verify_after_each_operation`: Verify after each operation

**Timing Options:**
- Adjust sleep durations based on system responsiveness
- Faster systems may use shorter sleep times

**Logging Options:**
- `verbose`: Enables detailed logging output
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
avocado run ppc64_cpu_test.py:PPC64Test.test_all_smt_operations
```

### Run with custom functional iterations
```bash
avocado run ppc64_cpu_test.py -p functional/iteration=10
```

### Run stress test with custom iterations
```bash
avocado run ppc64_cpu_test.py:PPC64Test.test_random_stress -p stress/iterations=50
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
Online CPUs: 40
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
Online CPUs: 38
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

### Framework Integration
- Uses avocado's `cpu.online_count()` for accurate CPU counting
- Cleaner, more maintainable validation code

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
- `3`: 3 threads per core (if supported)
- `4`: 4 threads per core
- `8`: 8 threads per core (if supported)
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

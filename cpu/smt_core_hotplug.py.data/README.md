# SMT Core Hotplug Optimized Test

## Overview
Comprehensive test suite for validating SMT (Simultaneous Multi-Threading) operations combined with CPU core online/offline operations on PowerPC systems.

## Test Methods

### 1. `test_all_smt_operations()`
Tests all SMT states dynamically detected from the system (off, 2, 3, 4, ..., max_smt, on).

### 2. `test_dynamic_core_operations()`
Tests various core online/offline configurations based on system capabilities.

### 3. `test_smt_core_interaction()`
Validates that SMT changes don't affect core count and core operations don't change SMT state.

### 4. `test_progressive_core_online_with_smt()`
Progressive test starting from minimal cores, gradually bringing cores online while testing all SMT states at each step.

### 5. `test_specific_cores_offline_with_smt()`
Advanced test that randomly offlines specific cores and performs SMT operations:
- Randomly selects and offlines specific cores (e.g., cores 2, 5, 7 from 10 online)
- Performs all SMT operations with those cores offline
- Validates that offline cores remain offline after SMT changes
- Validates that online cores maintain correct SMT state
- Next iteration: brings back previously offline cores, offlines different ones
- Tests various SMT operations with different core online/offline combinations

### 6. `test_random_stress()`
Random stress test with all possible SMT states and core configurations.

### 7. `test_parallel_operations()`
Parallel SMT and core operations to stress test the system.

## Configuration

All test parameters are configurable via YAML file:

```yaml
# Number of iterations
iteration: 5
parallel_iterations: 3
random_iterations: 50
num_parallel_threads: 4

# Enable/disable specific tests
run_all_smt_operations: true
run_dynamic_core_operations: true
run_smt_core_interaction: true
run_progressive_core_online_with_smt: true
run_specific_cores_offline_with_smt: true
run_random_stress: true
run_parallel_operations: true
```

## Command Syntax Reference

### SMT Operations
```bash
ppc64_cpu --smt=off          # Disable SMT (1 thread per core)
ppc64_cpu --smt=2            # 2 threads per core
ppc64_cpu --smt=4            # 4 threads per core
ppc64_cpu --smt=on           # Maximum SMT (system dependent)
```

### Core Operations
```bash
# Bring N cores online (N is a number)
ppc64_cpu --cores-on=5       # Bring 5 cores online
ppc64_cpu --cores-on=all     # Bring all cores online

# Bring specific cores online (comma-separated list)
ppc64_cpu --online-cores=1,2,3,4,5

# Take specific cores offline (comma-separated list)
ppc64_cpu --offline-cores=6,7,8,9
```

### Query Operations
```bash
ppc64_cpu --cores-present    # Show total cores
ppc64_cpu --cores-on         # Show cores online
ppc64_cpu --offline-cores    # Show offline cores
ppc64_cpu --info             # Detailed core/thread info
```

## Validation

The test performs comprehensive validation using multiple sources:
- **lscpu**: CPU topology and online CPU list
- **ppc64_cpu --info**: Per-core thread status
- **/proc/cpuinfo**: Processor entries
- **sysfs**: /sys/devices/system/cpu/online

All sources must agree on:
- Online CPUs = Cores Online × SMT Threads
- SMT consistency across all online cores
- Core count stability during SMT changes
- SMT state stability during core operations

## Running the Test

```bash
# Run with default configuration
avocado run smt_core_hotplug_optimized.py

# Run with custom YAML
avocado run smt_core_hotplug_optimized.py --mux-yaml smt_core_hotplug_optimized.yaml

# Run with specific parameters
avocado run smt_core_hotplug_optimized.py --mux-inject iteration:10 random_iterations:100
```

## System Requirements

- PowerPC architecture (ppc64/ppc64le)
- SMT-capable processor
- powerpc-utils package installed
- Root/sudo privileges for core and SMT operations

## Features

- Fully dynamic - no hardcoded values
- Adapts to any system configuration
- Tests all possible SMT states
- Comprehensive validation from multiple sources
- Configurable via YAML
- Detailed logging and error tracking

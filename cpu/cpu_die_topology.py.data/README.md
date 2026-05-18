# CPU Die Topology Test

## Overview

This test validates the CPU die topology support added by Linux kernel
commit **fb2ff9fa72e2** 
("powerpc/topology: Implement cpu_die_mask()/cpu_die_id()").

## Purpose

The test validates the following aspects of die topology on PowerPC systems:

1. **die_id sysfs interface**: Verifies that
   `/sys/devices/system/cpu/cpuX/topology/die_id` exists and returns
   valid values for all online CPUs.

2. **die_cpumask sysfs interface**: Verifies that
   `/sys/devices/system/cpu/cpuX/topology/die_cpus` and `die_cpus_list`
   exist and contain consistent information.

3. **die_id validity**: Ensures die_id values are either -1 (no coregroup
   support) or >= 0 (valid die identifier).

4. **die_cpumask consistency**: Verifies that all CPUs within the same die
   report the same die_cpumask.

5. **die-package relationship**: Ensures that all CPUs in the same die
   belong to the same physical package.

6. **cpu_die_mask() function**: Validates the kernel function behavior
   through sysfs.

7. **Performance validation** (optional): Demonstrates the practical benefits
   of die topology information by comparing workload performance when pinned
   to CPUs within the same die versus across multiple dies using the hackbench
   benchmark.

## Kernel Commit Details

**Commit**: fb2ff9fa72e2  
**Title**: powerpc/topology: Implement cpu_die_mask()/cpu_die_id()  
**Description**: This commit added support for die_id and die_cpumask on
PowerPC systems. On systems with coregroup support (multiple coregroups
within a package), die_id represents the coregroup ID. On systems without
coregroup support, die_id returns -1 and die_mask equals the package mask.

## Test Execution

### Basic topology validation only
```bash
avocado run cpu/cpu_die_topology.py
```

### With performance validation enabled
```bash
avocado run cpu/cpu_die_topology.py --mux-yaml cpu/cpu_die_topology.py.data/cpu_die_topology.yaml:performance_enabled
```

## Expected Behavior

### Systems WITH Coregroup Support
- `die_id` should be >= 0 for all CPUs
- `die_cpus` and `die_cpus_list` should contain CPUs in the same coregroup
- Multiple dies may exist within a single package

### Systems WITHOUT Coregroup Support
- `die_id` should be -1 for all CPUs
- `die_cpus` should match the package CPU mask
- Only one die per package

## Test Output

The test provides detailed logging including:
- Number of online CPUs tested
- die_id values for each CPU
- die_cpumask consistency checks
- die-package relationship validation
- Performance comparison results (if enabled):
  - Same-die execution times
  - Cross-die execution times
  - Performance degradation percentage
  - Analysis of cross-die penalty
- Summary of pass/fail status

## Requirements

- **Platform**: PowerPC (ppc64/ppc64le)
- **Privileges**: Root/sudo (for accessing all sysfs files)
- **Kernel**: Linux kernel with commit fb2ff9fa72e2 or later
- **Dependencies**: avocado-framework

## Troubleshooting

### die_id Returns -1
This is expected behavior on systems without coregroup support. The test
will pass as long as the value is consistent across all CPUs.

### Missing Sysfs Files
If die_id or die_cpus files are missing, the kernel may not have the
required commit. Verify kernel version and configuration.

### Performance Test Skipped
The performance test requires:
- At least 2 dies with sufficient CPUs (16+ CPUs per die recommended)
- hackbench benchmark (automatically downloaded and built from LTP)
- gcc and make packages installed

If the system doesn't meet these requirements, the performance test will
be skipped with an informational message.

## Performance Test Details

The performance validation test demonstrates the practical benefits of die
topology information by:

1. **Selecting CPU sets**: Identifies two sets of 16 CPUs:
   - Same-die set: All CPUs from a single die
   - Cross-die set: CPUs spanning multiple dies

2. **Running hackbench**: Executes the hackbench scheduler benchmark with
   CPU affinity using `taskset` to pin workloads to specific CPU sets

3. **Comparing results**: Measures execution time for both scenarios across
   multiple iterations and calculates the performance difference

4. **Expected results**: Workloads pinned to CPUs within the same die
   typically show 20-50% better performance compared to cross-die execution,
   validating the importance of die topology information for optimal workload
   placement.

### Performance Test Parameters

The test accepts the following parameters (configured via YAML):

- `run_performance_test`: Enable/disable performance test (default: False)
- `hackbench_groups`: Number of hackbench groups (default: "20")
- `hackbench_loops`: Number of loops per group (default: "2000")
- `hackbench_iterations`: Number of test iterations (default: "4")
- `ltp_url`: URL to download LTP source (default: LTP GitHub master)

### Example Performance Output

```
Performance Analysis
============================================================
Same-die execution:
  Times: ['2.644', '2.661', '2.659', '2.648']
  Average: 2.653 sec
  Min: 2.644 sec, Max: 2.661 sec
Cross-die execution:
  Times: ['3.764', '3.774', '3.736', '3.723']
  Average: 3.749 sec
  Min: 3.723 sec, Max: 3.774 sec
------------------------------------------------------------
Performance Impact:
  Cross-die execution is 41.3% slower than same-die
  SIGNIFICANT: Cross-die penalty > 10%
  This validates the importance of die topology
  information for workload placement
============================================================
```

## References

- Kernel commit: fb2ff9fa72e2
- PowerPC topology documentation: Documentation/powerpc/topology.rst
- Sysfs CPU topology: Documentation/ABI/testing/sysfs-devices-system-cpu

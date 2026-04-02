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

## Kernel Commit Details

**Commit**: fb2ff9fa72e2  
**Title**: powerpc/topology: Implement cpu_die_mask()/cpu_die_id()  
**Description**: This commit added support for die_id and die_cpumask on
PowerPC systems. On systems with coregroup support (multiple coregroups
within a package), die_id represents the coregroup ID. On systems without
coregroup support, die_id returns -1 and die_mask equals the package mask.

## Test Execution

### From avocado-misc-tests directory
```bash
avocado run cpu/cpu_die_topology.py
```

## Expected Behavior

### Systems WITH Coregroup Support (POWER9/POWER10)
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
- Summary of pass/fail status

## Requirements

- **Platform**: PowerPC (ppc64/ppc64le)
- **Privileges**: Root/sudo (for accessing all sysfs files)
- **Kernel**: Linux kernel with commit fb2ff9fa72e2 or later
- **Dependencies**: avocado-framework

## Troubleshooting

### Test Skipped
If the test is skipped with "Test is specific to PowerPC architecture",
ensure you're running on a PowerPC system.

### die_id Returns -1
This is expected behavior on systems without coregroup support. The test
will pass as long as the value is consistent across all CPUs.

### Missing Sysfs Files
If die_id or die_cpus files are missing, the kernel may not have the
required commit. Verify kernel version and configuration.

## References

- Kernel commit: fb2ff9fa72e2
- PowerPC topology documentation: Documentation/powerpc/topology.rst
- Sysfs CPU topology: Documentation/ABI/testing/sysfs-devices-system-cpu

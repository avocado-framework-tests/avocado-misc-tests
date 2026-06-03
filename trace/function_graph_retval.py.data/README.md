# Function Graph Return Value Tracing Test

## Overview

This test validates the function graph return value tracing support
for ppc64le architecture, which was added by kernel commit
`d733f18a6da6fb719450d5122162556d785ed580`.

## Kernel Commit Details

**Commit:** d733f18a6da6fb719450d5122162556d785ed580  
**Title:** powerpc/ftrace: support CONFIG_FUNCTION_GRAPH_RETVAL

This commit enables function graph return value tracing on PowerPC
by:
- Adding `HAVE_FUNCTION_GRAPH_FREGS` configuration support
- Implementing `ftrace_regs_get_return_value()` to return GPR3
  (return value register)
- Implementing `ftrace_regs_get_frame_pointer()` to return GPR1
  (stack pointer)
- Allocating proper stack space (SWITCH_FRAME_SIZE) for ftrace
  operations
- Using predefined offsets (GPR3, GPR4) for consistent register
  access

## Test Strategy

The test uses a **kernel module approach** to validate the feature:

1. Copies pre-built kernel module source (`retval_test.c`) and
   `Makefile` from the `.data/` directory to a temporary build
   directory
2. Customizes the Makefile with the actual build directory path
3. Builds the kernel module with test functions that return
   specific values
4. Loads the module while ftrace is capturing with funcgraph-retval
   enabled
5. Traces the module's functions to verify return values are
   displayed correctly
6. Validates that disabling funcgraph-retval prevents return value
   display

## Test Components

### 1. function_graph_retval.py
Main Avocado test file that:
- Checks kernel configuration for required features
- Verifies architecture is ppc64le
- Checks for secure boot (must be disabled to load modules)
- Installs build dependencies (gcc, make, kernel-devel)
- Copies test module source and Makefile from `.data/` directory
- Builds the test kernel module with known return values
- Sets up function graph tracer with return value tracing
- Loads the module and captures trace output
- Validates return values are correctly displayed in trace
- Tests that disabling funcgraph-retval prevents return value
  display

### 2. retval_test.c
Pre-written kernel module source file containing test functions:

- `test_retval_func(int input)` - Returns `input * 2 + 42`
- `test_retval_large()` - Returns large value
  `0x123456789ABCDEF0L`
- `test_retval_zero()` - Returns `0`
- `test_retval_negative()` - Returns `-42`

These functions are marked with `noinline` attribute to ensure they
appear in the trace. They are called during module initialization
(`test_retval_init`), generating traceable kernel activity with
known return values.

### 3. Makefile
Kernel module build file that uses a placeholder (`MODULE_DIR`)
which is replaced at runtime with the actual temporary build
directory path. This ensures the module builds correctly regardless
of where the test is run.

### 4. function_graph_retval.yaml
Configuration file for test parameters (currently minimal, contains
only documentation comments).

## Requirements

### Kernel Configuration
- `CONFIG_FUNCTION_GRAPH_TRACER=y`
- `CONFIG_HAVE_FUNCTION_GRAPH_FREGS=y`
- `CONFIG_FTRACE=y`
- `CONFIG_DYNAMIC_FTRACE=y`

### Architecture
- PowerPC 64-bit Little Endian (ppc64le)
- PowerPC 64-bit Big Endian (ppc64) also supported

### System Requirements
- Root/sudo access (for ftrace operations and module loading)
- Kernel debugfs mounted at `/sys/kernel/debug`
- **Secure boot must be disabled** (for loading unsigned kernel
  modules)
- GCC compiler
- Make utility
- Kernel headers/development packages (kernel-devel,
  kernel-headers, or linux-headers)

## Running the Test

### Using Avocado

```bash
# Run the test
avocado run function_graph_retval.py

```

### Manual Testing

```bash
# Check secure boot status
lsprop /proc/device-tree/ibm,secure-boot

# Use the provided retval_test.c and Makefile from this directory
# Copy them to a temporary directory
mkdir -p /tmp/test_module
cp retval_test.c /tmp/test_module/
cp Makefile /tmp/test_module/
cd /tmp/test_module

# Update Makefile to use current directory
sed -i 's/MODULE_DIR/\/tmp\/test_module/g' Makefile

# Build module
make

# Set up function graph tracer
echo 0 > /sys/kernel/debug/tracing/tracing_on
echo function_graph > /sys/kernel/debug/tracing/current_tracer
echo 1 > /sys/kernel/debug/tracing/options/funcgraph-retval
echo > /sys/kernel/debug/tracing/trace
echo 1 > /sys/kernel/debug/tracing/tracing_on

# Load module (this triggers the traced functions)
insmod test_retval.ko

# Disable tracing
echo 0 > /sys/kernel/debug/tracing/tracing_on

# Check trace output (should show return values)
cat /sys/kernel/debug/tracing/trace | grep test_retval

# Unload module
rmmod test_retval

# Cleanup
echo nop > /sys/kernel/debug/tracing/current_tracer
echo > /sys/kernel/debug/tracing/set_ftrace_filter
```

## Expected Output

When funcgraph-retval is enabled, the trace output should contain
return values in the format:

```
 0)               |  test_retval_init() {
 0)               |    test_retval_func() {
 0)   0.123 us    |    } /* test_retval_func = 0x44 */
 0)               |    test_retval_large() {
 0)   0.234 us    |    } /* test_retval_large = 0x123456789abcdef0 */
 0)               |    test_retval_zero() {
 0)   0.345 us    |    } /* test_retval_zero = 0x0 */
 0)               |    test_retval_negative() {
 0)   0.456 us    |    } /* test_retval_negative = 0xffffffffffffffd6 */
 0)   2.345 us    |  } /* test_retval_init = 0x0 */
```

The return values shown are:
- `test_retval_func(10)` returns `0x44` (68 decimal = 10 * 2 + 42)
- `test_retval_large()` returns `0x123456789abcdef0`
- `test_retval_zero()` returns `0x0`
- `test_retval_negative()` returns `0xffffffffffffffd6` (-42 in
  two's complement)
- `test_retval_init()` returns `0x0` (successful initialization)

## Troubleshooting

### Secure boot is enabled
**Error:** "Secure boot is enabled, cannot load kernel modules"

**Solution:**
- Disable secure boot in firmware settings, or
- Sign the kernel module with a valid key

### Module build fails
**Error:** "Failed to build kernel module"

**Solutions:**
- Install kernel-devel: `yum install kernel-devel`
  (RHEL/CentOS) or `apt install linux-headers-$(uname -r)`
  (Ubuntu)
- Ensure gcc and make are installed
- Verify kernel headers match running kernel: `uname -r` vs
  `/lib/modules/$(uname -r)/build`

### Module load fails
**Error:** "Failed to load module"

**Solutions:**
- Check dmesg for error messages: `dmesg | tail -20`
- Verify module was built: `ls -l test_retval.ko`
- Check for module signature issues: `modinfo test_retval.ko`
- Ensure no conflicting module is loaded:
  `lsmod | grep test_retval`

### No trace output captured
**Error:** "No trace output captured"

**Solutions:**
- Check if ftrace is mounted: `mount | grep tracefs`
- Verify tracing is enabled:
  `cat /sys/kernel/debug/tracing/tracing_on`
- Check function filter:
  `cat /sys/kernel/debug/tracing/set_ftrace_filter`
- Verify module loaded successfully: `lsmod | grep test_retval`
- Check dmesg for module messages: `dmesg | grep test_retval`

### Return values not found in trace
**Error:** "No return values found in trace output"

**Solutions:**
- Verify kernel configuration:
  `grep FUNCTION_GRAPH /boot/config-$(uname -r)`
- Check if funcgraph-retval option exists:
  `ls /sys/kernel/debug/tracing/options/funcgraph-retval`
- Ensure the kernel has the required commit:
  `git log --oneline --grep="CONFIG_FUNCTION_GRAPH_RETVAL"`
- Verify function was actually traced: look for function name in
  trace output

### Test fails on non-ppc64le
**Error:** "Test is specific to PowerPC architecture"

**Explanation:**
- This test validates a ppc64le-specific kernel feature
- The commit being tested added support specifically for PowerPC
  architecture
- Run the test on a ppc64le system

## Test Validation

The test performs these validations:

1. **Architecture Check**: Confirms system is ppc64le or ppc64
2. **Secure Boot Check**: Ensures modules can be loaded
3. **Kernel Config Check**: Verifies required ftrace features are
   enabled
4. **Module Build**: Confirms kernel module builds successfully
   from `.data/` directory files
5. **Module Load**: Verifies module loads without errors
6. **Trace Capture**: Confirms trace data is captured
7. **Return Value Format**: Validates return values match regex
   pattern `/* function = 0xVALUE */`
8. **Return Value Presence**: Confirms test module functions are
   found with return values
9. **Option Control**: Verifies disabling funcgraph-retval
   prevents return value display

## References

- Kernel commit: d733f18a6da6fb719450d5122162556d785ed580
- ftrace documentation: Documentation/trace/ftrace.rst in kernel
  source
- Kernel module programming: Documentation/kbuild/modules.rst in
  kernel source
- PowerPC ftrace: arch/powerpc/kernel/trace/ftrace.c in kernel
  source

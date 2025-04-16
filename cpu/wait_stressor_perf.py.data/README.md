# Wait Stressor Performance Test

## Overview

This test validates Linux kernel scheduler load balancing performance by running the `wait_stressor.c` program while monitoring scheduler functions with `perf`. The test ensures that critical scheduler functions consume minimal CPU cycles during load balancing operations.

**Note: This test is only applicable for SUSE Linux distributions.**

## Performance Optimization

The test uses targeted perf analysis with `--symbol-filter` to query only specific scheduler functions, making it fast and efficient:
- Avoids generating massive full perf reports
- Queries only the 2 target functions: `enqueue_task_fair` and `newidle_balance`
- Completes analysis in seconds instead of minutes
- Keeps logs clean and readable

## Test Description

The test performs the following steps:

1. **Compiles wait_stressor.c** - A stress test program that creates 100 child processes, each spawning runner and killer processes that continuously send SIGSTOP/SIGCONT signals
2. **Runs wait_stressor** - Generates load balancing stress by creating multiple processes that exercise the wait system call
3. **Captures perf data** - Records performance data using `perf record` during the stress test execution
4. **Analyzes results** - Uses `perf report --symbol-filter` to efficiently query only the target scheduler functions and extract their cycle percentages

## Target Functions

The test monitors two critical scheduler functions:

1. **enqueue_task_fair** - Handles task enqueueing in the Completely Fair Scheduler (CFS)
2. **newidle_balance** - Performs load balancing when a CPU becomes idle

## Expected Results

Both functions should consume **less than 2.0%** of CPU cycles:

```
Expected output example:
0.09%  swapper  [kernel.vmlinux]  [k] enqueue_task_fair
0.09%  wait     [kernel.vmlinux]  [k] newidle_balance
```

If either function exceeds the 2.0% threshold, it indicates potential scheduler inefficiency or load balancing issues.

## Source

The wait_stressor.c program is based on Aboorva Devarajan's implementation:
- Original source: https://gist.github.ibm.com/abodevar/d135e83e2a9db38be024b9f715085751

## Prerequisites

### Required Packages

- **gcc** - For compiling wait_stressor.c
- **make** - Build tools
- **perf** - Linux performance analysis tool (SUSE package)

### System Requirements

- **SUSE Linux distribution** (SLES, openSUSE)
- Linux kernel with scheduler tracepoints enabled
- Root or CAP_SYS_ADMIN privileges for perf recording
- Sufficient CPU cores for load balancing (recommended: 4+ cores)

## Configuration

The test can be configured using the YAML file (`wait_stressor_perf.yaml`):

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `duration` | 30 | Test duration in seconds |
| `threshold` | 2.0 | Maximum acceptable cycle percentage |

### Configuration Variants

#### Default Configuration
```yaml
duration: 30
threshold: 2.0
```

#### Short Test
```yaml
duration: 15
threshold: 2.0
```

#### Long Test with Relaxed Threshold
```yaml
duration: 60
threshold: 4.0
```

## Running the Test

### Basic Execution

```bash
avocado run wait_stressor_perf.py
```

### With Custom Configuration

```bash
avocado run wait_stressor_perf.py --mux-yaml wait_stressor_perf.py.data/wait_stressor_perf.yaml
```

### With Specific Variant

```bash
avocado run wait_stressor_perf.py --mux-yaml wait_stressor_perf.py.data/wait_stressor_perf.yaml --mux-filter-only /run/duration/long
```

### With Custom Parameters

```bash
avocado run wait_stressor_perf.py -p duration=45 -p threshold=3.5
```

## Output

### Test Logs

The test generates the following output files in the test log directory:

1. **perf_report.txt** - Full perf report output
2. **test.log** - Detailed test execution log
3. **debug.log** - Debug information

### Console Output

```
INFO | Analyzing perf data for target scheduler functions
INFO | Found enqueue_task_fair: 0.09%
INFO | Found newidle_balance: 0.09%
INFO | ============================================================
INFO | RESULTS:
INFO | ============================================================
INFO | enqueue_task_fair: 0.09% [PASS]
INFO | newidle_balance: 0.09% [PASS]
INFO | ============================================================
INFO | Threshold: < 2.0%
INFO | ============================================================
INFO | SUCCESS: All functions below threshold
```

### Log Files

The test generates minimal log output:
- **debug.log** - Contains only targeted function analysis (not full perf report)
- **test.log** - Test execution summary
- No separate perf_report.txt file (optimization to reduce disk I/O)

## Troubleshooting

### Permission Denied for perf

If you encounter permission errors:

```bash
# Temporarily allow perf for non-root users
sudo sysctl -w kernel.perf_event_paranoid=-1

# Or run test with sudo
sudo avocado run wait_stressor_perf.py
```

### Functions Not Found in perf Report

If a function shows 0.0% or "Not detected":
- The function consumed less than 0.01% of cycles (excellent performance)
- The load may be too low to trigger significant scheduler activity
- Kernel symbols may not be available

This is typically a PASS condition as it indicates minimal scheduler overhead.

To increase scheduler activity, try:
- Increasing test duration
- Running on a system with more CPU cores
- Ensuring the system has other background load

### Compilation Errors

Ensure gcc and development headers are installed on SUSE:

```bash
# SUSE/openSUSE
sudo zypper install gcc make perf
```

### Test Skipped on Non-SUSE Systems

This test will be automatically skipped (cancelled) if run on non-SUSE distributions with the message:
```
CANCEL: This test is only applicable for SUSE Linux distributions
```

## Test Tags

- `cpu` - CPU/scheduler related test
- `scheduler` - Scheduler specific test
- `perf` - Uses perf tool
- `loadbalancing` - Load balancing validation
- `suse` - SUSE Linux specific test

## References

- Linux Scheduler Documentation: https://www.kernel.org/doc/html/latest/scheduler/
- Perf Wiki: https://perf.wiki.kernel.org/
- CFS Scheduler: https://www.kernel.org/doc/Documentation/scheduler/sched-design-CFS.txt

## Author

- Aboorva Devarajan <aboorvad@linux.ibm.com>
- Samir M <samir@linux.ibm.com>

## License

This test is part of avocado-misc-tests and is licensed under the GNU General Public License v2.0 or later.

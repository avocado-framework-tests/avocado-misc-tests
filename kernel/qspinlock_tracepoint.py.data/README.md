# QSpinlock Tracepoint Test - Lockstorm Integration

## Overview

This test validates the PowerPC queued spinlock contention tracepoints added in Linux kernel commit 4f61d54d2245c15b23ad78a89f854fb2496b6216 ("powerpc/qspinlock: Add spinlock contention tracepoint").

The test use the lockstorm benchmark module (from https://github.com/npiggin/lockstorm.git) as a test vehicle and uses lockstorm's `cpulist` parameter.


## Test Configuration

The test is configured via `qspinlock_tracepoint.yaml`:

```yaml
# Functional test - basic validation with lockstorm
functional:
    test_type: functional
    cpu_list: 0  # 0 means all CPUs; change to "0-3" or "0,2,4" as needed
    lockstorm_timeout: 10  # Duration in seconds (default: 10)

# Stress test - heavy spinlock contention with lockstorm
stress:
    test_type: stress
    cpu_list: 0  # 0 means all CPUs; change to "0-3" or "0,2,4" as needed
    lockstorm_timeout: 20  # Duration in seconds (default: 20 for stress)
```

### Parameters

Both `functional` and `stress` test types support the following parameters:

- `test_type`: Either "functional" or "stress"
  - functional: Basic validation with shorter duration
  - stress: Extended test with longer duration and minimum event threshold

- `cpu_list`: Controls which CPUs lockstorm runs on (applicable to both
  test types)
  - `0`: Run on all CPUs (default)
  - `"0-3"`: Run on specific CPU range (CPUs 0, 1, 2, 3)
  - `"0,2,4"`: Run on specific non-contiguous CPUs

- `lockstorm_timeout`: Duration in seconds for lockstorm to run (default: 10
  for functional, 20 for stress)
  - Controls how long the lockstorm benchmark runs
  - Longer durations generate more spinlock contention and capture
    more tracepoint events
  - Perf recording time is automatically adjusted (timeout + buffer seconds)
  - Examples: 10, 20, 30, 60 seconds

## What the Test Validates

1. Tracepoint Availability: Verifies that `lock:contention_begin` and
  `lock:contention_end` tracepoints exist
2. Tracepoint Enable/Disable: Tests that tracepoints can be enabled and
  disabled via sysfs
3. Event Capture: Uses perf to capture tracepoint events during lockstorm
  execution
4. Event Analysis: Validates that contention events are properly recorded
5. __lockfunc Annotation: Verifies the annotation is working correctly

## Running the Test

### Customizing Test Behavior

To customize test behavior, modify parameters in the YAML file:

```yaml
# Example 1: Test on CPU range 0-3 with 15-second duration
functional:
    test_type: functional
    cpu_list: "0-3"
    lockstorm_timeout: 15

# Example 2: Stress test on specific CPUs with 30-second duration
stress:
    test_type: stress
    cpu_list: "0,2,4"
    lockstorm_timeout: 30

# Example 3: Long-duration stress test on all CPUs
stress:
    test_type: stress
    cpu_list: 0
    lockstorm_timeout: 60  # 1 minute of continuous spinlock contention
```

Then run the test normally - it will use your modified configuration.

### Understanding Lockstorm Timeout

The `lockstorm_timeout` parameter directly controls the lockstorm module's
`timeout` parameter:
- Shorter durations (10-15s): Quick validation, fewer events captured
- Medium durations (20-30s): Balanced testing, good event coverage
- Longer durations (60s+): Extensive stress testing, maximum event capture

The test automatically adjusts perf recording time to match:
- Functional tests: `lockstorm_timeout + 2 seconds` buffer
- Stress tests: `lockstorm_timeout + 5 seconds` buffer

## Test Output

The test captures:
- Tracepoint availability status
- Perf event counts (lock:contention_begin and lock:contention_end)
- Lockstorm performance statistics from dmesg
- Perf report for detailed analysis

## Troubleshooting

If the test fails:

1. Module Load Failure: Check if secure boot is preventing module loading
2. No Events Captured: Verify queued spinlocks are enabled in kernel config
3. Build Failure: Ensure kernel-devel packages match running kernel version
4. Tracepoints Missing: Kernel may not have the tracepoint patches applied

# Linux Scheduler Tunables Test Suite

## Overview

This test suite validates the behavior of the Linux CFS (Completely Fair Scheduler) by testing the **top 4 most important and verifiable scheduler tunables**:

1. **`base_slice_ns`** - Controls the base time slice for CFS scheduler
2. **`sched_migration_cost_ns`** - Controls task migration cost threshold
3. **`sched_nr_migrate`** - Controls number of tasks to migrate at once
4. **`sched_schedstats`** - Enables scheduler statistics (required for verification)

## Test Strategy

The test suite uses a **before/after comparison approach** with averaged metrics to validate tunable behavior:

- **Baseline Test**: Establishes reference metrics with default system tunables
- **Low Latency Test**: Reduces time slices to test responsiveness impact
- **High Throughput Test**: Increases time slices to test throughput impact
- **Migration Behavior Test**: Tests task migration patterns

Each test:
1. Runs workload with **default tunables** (baseline)
2. Changes tunables to **test configuration**
3. Runs same workload with **modified tunables**
4. **Compares metrics** to validate expected behavior

## Test Execution

### Prerequisites

```bash
# Install required packages
sudo dnf install stress-ng perf  # RHEL/Fedora
sudo apt install stress-ng linux-tools-common  # Ubuntu/Debian
sudo zypper install stress-ng perf  # SUSE

# Mount debugfs (if not already mounted)
sudo mount -t debugfs none /sys/kernel/debug

# Enable scheduler statistics (optional but recommended)
echo 1 | sudo tee /proc/sys/kernel/sched_schedstats
```

### Running Tests

```bash
# Run all tests
sudo avocado run scheduler_tunables_test.py

# Run specific test
sudo avocado run scheduler_tunables_test.py:SchedulerTunablesTest.test_01_baseline

# Run with custom parameters
sudo avocado run scheduler_tunables_test.py \
    --mux-yaml scheduler_tunables_test.py.data/scheduler_tunables_test.yaml \
    -- test_duration:20 stress_workers:64
```

### Test Parameters (YAML Configuration)

- **`test_duration`**: Duration of each workload run (default: 10 seconds)
- **`stress_workers`**: Number of stress-ng workers (default: 0 = auto-calculate as 8x CPU count)

## Test Cases

### Test 1: Baseline (Default Tunables)

**Purpose**: Establish reference metrics with system default tunables

**Workload**: Mixed CPU + I/O

**Validation**:
- All tunables are readable
- Context switches detected (scheduler is working)
- CPU migrations detected (load balancing is working)
- Metrics stored for comparison in subsequent tests

### Test 2: Low Latency Configuration

**Purpose**: Test scheduler behavior with reduced time slices

**Workload**: Pure CPU-bound

**Tunable Changes**:
- `base_slice_ns`: Reduced to 25% of baseline (min 0.75ms)
- `sched_migration_cost_ns`: Reduced to 10% of baseline (min 50μs)

**Expected Behavior**:
- **More context switches** (smaller time slices = more frequent preemption)
- Better responsiveness for interactive workloads
- Slightly higher scheduling overhead

**Validation**: Compares context switches before/after tunable changes

### Test 3: High Throughput Configuration

**Purpose**: Test scheduler behavior with increased time slices

**Workload**: Context-switch intensive

**Tunable Changes**:
- `base_slice_ns`: Increased to 3x baseline
- `sched_migration_cost_ns`: Increased to 2x baseline

**Expected Behavior**:
- **Fewer context switches** (larger time slices = less preemption)
- Higher throughput for CPU-bound workloads
- Reduced scheduling overhead

**Validation**: Compares context switches and CPU migrations before/after tunable changes

### Test 4: Migration Behavior

**Purpose**: Test task migration patterns with different `sched_nr_migrate` values

**Workload**: Fork-heavy (creates many tasks)

**Tunable Changes**:
- `sched_nr_migrate`: Increased to 2x baseline (max 128)

**Expected Behavior**:
- More tasks migrated per load balancing operation
- Better load distribution across CPUs
- May increase migration overhead

**Validation**: Compares CPU migrations before/after tunable changes

## Metrics Collected

The test suite uses `perf stat` to collect scheduler metrics:

- **Context switches**: Number of times tasks were switched
- **CPU migrations**: Number of times tasks moved between CPUs
- **Page faults**: Memory access patterns
- **Task clock**: Total CPU time used
- **CPUs utilized**: Average CPU utilization
- **Instructions per cycle (IPC)**: CPU efficiency metric

### Derived Metrics

- **Migrations per 1000 context switches**: Migration efficiency ratio
- **Standard deviation**: Measurement reliability (10 iterations averaged)

## Understanding Results

### Low Latency Test

```
Context Switches:
  Baseline (default): 50000
  Low Latency: 75000
  Change: +50.0%
  ✓ EXPECTED: More context switches with smaller time slices
```

**Interpretation**: Reducing time slices increases preemption frequency, which is expected for low-latency configurations.

### High Throughput Test

```
Context Switches:
  Baseline: 50000
  High Throughput: 30000
  Change: -40.0%
```

**Interpretation**: Larger time slices reduce context switching overhead, improving throughput.

### Migration Behavior Test

```
CPU migrations: 5000 (baseline) -> 7500 (aggressive nr_migrate)
Change: +50.0%
```

**Interpretation**: Higher `sched_nr_migrate` allows more tasks to be migrated per balancing operation.

## Tunable Reference

### base_slice_ns

- **Path**: `/sys/kernel/debug/sched/base_slice_ns`
- **Unit**: Nanoseconds
- **Typical Range**: 750,000 - 6,000,000 (0.75ms - 6ms)
- **Impact**: Controls how long a task runs before being preempted
- **Lower values**: Better responsiveness, higher overhead
- **Higher values**: Better throughput, less responsive

### sched_migration_cost_ns

- **Paths**: 
  - `/proc/sys/kernel/sched_migration_cost_ns`
  - `/sys/kernel/debug/sched/migration_cost_ns`
- **Unit**: Nanoseconds
- **Typical Range**: 50,000 - 5,000,000 (50μs - 5ms)
- **Impact**: Threshold for considering task migration
- **Lower values**: More aggressive migration, better load balancing
- **Higher values**: Less migration, lower overhead

### sched_nr_migrate

- **Paths**:
  - `/proc/sys/kernel/sched_nr_migrate`
  - `/sys/kernel/debug/sched/nr_migrate`
- **Unit**: Number of tasks
- **Typical Range**: 8 - 128
- **Impact**: How many tasks to migrate per load balancing operation
- **Lower values**: Less aggressive balancing
- **Higher values**: More aggressive balancing, better distribution

### sched_schedstats

- **Path**: `/proc/sys/kernel/sched_schedstats`
- **Unit**: Boolean (0 or 1)
- **Impact**: Enables/disables scheduler statistics collection
- **Note**: Required for detailed scheduler analysis

## System Requirements

- **OS**: Linux with CFS scheduler (kernel 2.6.23+)
- **Packages**: `stress-ng`, `perf`
- **Permissions**: Root or sudo access
- **CPUs**: Minimum 2 CPUs (more CPUs = better test coverage)
- **Kernel Features**: 
  - `CONFIG_SCHEDSTATS` (optional but recommended)
  - debugfs mounted at `/sys/kernel/debug`

## Troubleshooting

### Tunables Not Found

```bash
# Check if debugfs is mounted
mount | grep debugfs

# Mount debugfs if needed
sudo mount -t debugfs none /sys/kernel/debug

# Check kernel config
grep CONFIG_SCHEDSTATS /boot/config-$(uname -r)
```

### Permission Denied

```bash
# Run with sudo
sudo avocado run scheduler_tunables_test.py

# Or add user to appropriate groups
sudo usermod -aG wheel $USER  # RHEL/Fedora
```

### stress-ng Not Found

```bash
# Install stress-ng
sudo dnf install stress-ng  # RHEL/Fedora
sudo apt install stress-ng  # Ubuntu/Debian
sudo zypper install stress-ng  # SUSE
```

### perf Not Available

```bash
# Install perf
sudo dnf install perf  # RHEL/Fedora
sudo apt install linux-tools-common linux-tools-$(uname -r)  # Ubuntu
sudo zypper install perf  # SUSE
```

## References

- [Linux Scheduler Documentation](https://www.kernel.org/doc/html/latest/scheduler/index.html)
- [CFS Scheduler Design](https://www.kernel.org/doc/html/latest/scheduler/sched-design-CFS.html)
- [Scheduler Tunables](https://www.kernel.org/doc/html/latest/admin-guide/sysctl/kernel.html)
- [stress-ng Documentation](https://wiki.ubuntu.com/Kernel/Reference/stress-ng)

## Author

- **Samir** <samir@linux.ibm.com>
- **Copyright**: 2026 IBM
- **License**: GNU General Public License v2.0

## Notes

- Tests automatically restore original tunable values after completion
- Each test runs 10 iterations and reports averaged metrics for reliability
- Standard deviation is calculated for key metrics to assess measurement quality
- Tests are designed to be non-destructive and safe for production systems

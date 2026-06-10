# Spyre Observability Tests

This test suite validates the observability functionality on Spyre AIU devices by capturing metrics and analyzing trace data during inference workload execution in a containerized VLLM environment.

## Observability Tools

### AIU-SMI Monitor
The **aiu-smi** tool is a command line tool which collects metrics information from the Spyre card, also referred to as AIU (Artificial Intelligence Unit), and prints a performance summary. It stands for AIU System Management Interface. The metrics are per Spyre card.

### Acelyzer (Trace Analyzer)
**Acelyzer** is a tool to post-process JSON trace files for IBM-AIU performance analysis. It enhances the traces with additional statistics extracted from the trace data itself and (optionally) by combining it with additional output from running a workload.

## Overview

The test suite includes two tests:

### Test 1: AIU-SMI Observability (`test_aiu_smi`)
1. Sets up servicereport and spyre group access as root user
2. Creates a Podman container with `DTCOMPILER_KEEP_EXPORT=true`
3. Waits for the VLLM server to start up
4. Starts continuous inference in the background
5. Runs aiu-smi continuously for a specified duration and captures all output at the end
6. Validates that metrics are successfully captured and contain valid data
7. Test passes if metrics are captured; fails if no metrics are captured

### Test 2: Acelyzer (`test_trace_analyzer`)
1. Stops any existing containers
2. Clones the aiu-trace-analyzer repository from GitHub
3. Creates a Podman container with FLEX environment variables for trace generation
4. Copies aiu-trace-analyzer to the container
5. Verifies FLEX environment variables are set correctly
6. Installs acelyzer in the container
7. Waits for VLLM to start
8. Generates trace files by sending inference requests
9. Runs acelyzer to analyze the trace files
10. Verifies output files contain valid performance data
11. Test passes if trace files are generated and analyzed successfully

## Test Purpose

### AIU-SMI Test
This test validates the **aiu-smi** monitoring tool by:
- Ensuring aiu-smi can be executed inside the container
- Verifying that metrics are being collected during active inference
- Validating the format and content of the captured metrics
- Confirming observability tools are functioning correctly

### Acelyzer Test
This test validates **Acelyzer** by:
- Ensuring trace files are generated with FLEX timing enabled
- Verifying acelyzer can process trace files
- Validating performance metrics extraction
- Confirming trace analysis tools are functioning correctly
- Measuring AIU device utilization and kernel execution times

## Prerequisites

- Power platform (ppc64le)
- Podman installed
- Root access
- Spyre AIU devices configured
- VLLM container image available with aiu-monitor installed
- Python3 with requests library

## Required Parameters

### Core Parameters
- `SPYRE_GROUP`: Group name for Spyre device access (e.g., "spyre")
- `AIU_PCIE_IDS`: PCIe IDs of AIU devices (e.g., "0301:50:00.0")
- `AIU_WORD_SIZE`: Number of AIU cards (e.g., "1")
- `HOST_MODELS_DIR`: Host directory containing models (e.g., "/opt/ibm/spyre/models")
- `VLLM_MODEL_PATH`: Path to model inside container (e.g., "/models/granite-3.3-8b-instruct")

### Model Configuration
- `MAX_MODEL_LEN`: Maximum model context length (e.g., "32768")
- `MAX_BATCH_SIZE`: Maximum batch size (e.g., "32")
- `MEMORY`: Container memory limit (e.g., "200G")
- `SHM_SIZE`: Shared memory size (e.g., "2G")

### Container Configuration
- `CONTAINER_URL`: Container registry URL
- `CONTAINER_TAG`: Container image tag
- `API_KEY`: Container registry API key (optional)
- `DEVICE`: Device to mount (default: "/dev/vfio")
- `PRIVILEGED`: Run privileged (default: "true")
- `PIDS_LIMIT`: Process limit (default: "0")
- `USERNS`: User namespace (default: "keep-id")
- `GROUP_ADD`: Additional groups (default: "keep-groups")
- `PORT_MAPPING`: Port mapping (default: "127.0.0.1::8000")

### VLLM Options
- `VLLM_SPYRE_USE_CB`: Enable Spyre callback (e.g., "1")
- `VLLM_DT_CHUNK_LEN`: Data transfer chunk length (optional)
- `VLLM_SPYRE_USE_CHUNKED_PREFILL`: Enable chunked prefill (optional)
- `ENABLE_PREFIX_CACHING`: Enable prefix caching (true/false)
- `ADDITIONAL_VLLM_ARGS`: Additional VLLM arguments (space-separated)

### Observability-Specific Parameters
- `METRICS_DURATION`: Duration to capture metrics in seconds (default: "30") - for aiu-smi test
- `TRACE_NUM_REQUESTS`: Number of inference requests for trace generation (default: "10") - for Acelyzer test

## Example YAML Configuration

```yaml
observability:
    vms:
        - observability:
            SPYRE_GROUP: "spyre"
            AIU_PCIE_IDS: "0301:50:00.0"
            AIU_WORD_SIZE: "1"
            HOST_MODELS_DIR: "/opt/ibm/spyre/models"
            VLLM_MODEL_PATH: "/models/granite-3.3-8b-instruct"
            MAX_MODEL_LEN: "32768"
            MAX_BATCH_SIZE: "32"
            MEMORY: "200G"
            SHM_SIZE: "2G"
            CONTAINER_URL: "container-url"
            CONTAINER_TAG: "container-tag"
            API_KEY: "your-api-key-here"
            VLLM_SPYRE_USE_CB: "1"
            ENABLE_PREFIX_CACHING: "true"
            DEVICE: "/dev/vfio"
            PRIVILEGED: "true"
            PIDS_LIMIT: "0"
            USERNS: "keep-id"
            GROUP_ADD: "keep-groups"
            PORT_MAPPING: "127.0.0.1::8000"
            METRICS_DURATION: "30"
```

## Usage

Run all observability tests:
```bash
avocado run spyre_observability_tests.py -m spyre_observability_tests.py.data/spyre_observability_tests.yaml
```

Run only the AIU-SMI test:
```bash
avocado run spyre_observability_tests.py:ObservabilityTests.test_aiu_smi -m spyre_observability_tests.py.data/spyre_observability_tests.yaml
```

Run only the Acelyzer test:
```bash
avocado run spyre_observability_tests.py:ObservabilityTests.test_trace_analyzer -m spyre_observability_tests.py.data/spyre_observability_tests.yaml
```

## Test Flow

The test follows this flow:

1. **Setup Phase (Root User)**
   - Install required packages (podman, python3-requests, etc.)
   - Download and extract ServiceReport
   - Run `servicereport -r -p spyre` to configure spyre devices
   - Run `servicereport -v -p spyre` to verify configuration
   - Add root user to spyre group
   - Verify VFIO devices exist and have correct group ownership
   - Login to container registry (if API_KEY provided)
   - Pull container image

2. **Container Creation (Root User)**
   - Create container as root user with VLLM and Spyre configuration
   - Set `DTCOMPILER_KEEP_EXPORT=true` environment variable
   - Mount AIU devices (`/dev/vfio`)
   - Mount models directory
   - Start VLLM server with specified model

3. **VLLM Startup Wait**
   - Monitor container logs for "Application startup complete"
   - Timeout after 300 seconds if VLLM doesn't start
   - Check for VFIO-related errors in logs

4. **Continuous Inference**
   - Start background Python process sending inference requests
   - Uses rotating prompts to keep AIU devices active
   - Runs continuously during metrics collection
   - Requests sent every 5 seconds

5. **Metrics Collection**
   - Wait 10 seconds for inference to generate load
   - Execute `timeout 30 podman exec container_id bash --login -c "source /opt/aiu-monitor/bin/activate && while true; do aiu-smi; sleep 1; done"`
   - Command runs continuously for 30 seconds (configurable via METRICS_DURATION)
   - All metrics output is captured and displayed at the end
   - Display all captured metrics in test logs

6. **Metrics Validation**
   - Verify metrics contain required headers (ID, Date, Time, hostcpu, hostmem, pwr, gtemp, busy, rdmem, wrmem, etc.)
   - Verify at least one data line exists
   - Parse and validate numeric values (CPU%, memory%, power, temperature)
   - Test PASSES if valid metrics are captured
   - Test FAILS if no metrics are captured

7. **Cleanup**
   - Stop continuous inference process
   - Collect final container logs
   - Stop and remove container

## Expected Metrics Output

Example of captured aiu-smi metrics:

```
#MetricFiles
# 0 /tmp/metrics.0301:50:00.0
#ID Date      Time      hostcpu hostmem    pwr  gtemp   busy    rdmem    wrmem    rxpci    txpci   rdrdma   wrrdma   rsvmem
#   YYYYMMDD  HH:MM:SS        %       %      W      C      %     GB/s     GB/s     GB/s     GB/s     GB/s     GB/s       MB
  0 20260610  06:38:45     15.0     5.4   18.9   30.8      0    0.000    0.000    0.000    0.000    0.000    0.000    0.000
  0 20260610  06:38:46      4.6     5.4   19.0   30.8      0    0.000    0.000    0.000    0.000    0.000    0.000    0.000
  0 20260610  06:38:47      6.2     5.4   19.0   30.8      0    0.000    0.000    0.000    0.000    0.000    0.000    0.000
  0 20260610  06:38:48      3.6     5.4   18.9   30.8      0    0.000    0.000    0.000    0.000    0.000    0.000    0.000
```

### Metrics Explanation

- **ID**: Device ID (0, 1, 2, etc.)
- **Date**: Date in YYYYMMDD format
- **Time**: Time in HH:MM:SS format
- **hostcpu**: Host CPU utilization percentage
- **hostmem**: Host memory utilization percentage
- **pwr**: Power consumption in Watts
- **gtemp**: GPU/AIU temperature in Celsius
- **busy**: Device busy percentage
- **rdmem**: Memory read bandwidth in GB/s
- **wrmem**: Memory write bandwidth in GB/s
- **rxpci**: PCIe receive bandwidth in GB/s
- **txpci**: PCIe transmit bandwidth in GB/s
- **rdrdma**: RDMA read bandwidth in GB/s
- **wrrdma**: RDMA write bandwidth in GB/s
- **rsvmem**: Reserved memory in MB

## Acelyzer Test Details

### FLEX Environment Variables

The Acelyzer test sets these environment variables in the container:
- `ENABLE_FLEX_TIMING=1`: Enable timing instrumentation
- `FLEX_PRINT_END_TO_END_BREAKDOWN=1`: Print detailed timing breakdown
- `FLEX_SKIP_TIMESTAMP_CALIBRATION=0`: Enable timestamp calibration
- `FLEX_SCHEDULER_PRINT_RAW_TIMESTAMPS=1`: Print raw timestamps
- `FLEX_GLOBAL_PROFILE_PREFIX="granite-8b-flex"`: Prefix for trace files

### Expected Trace Files

Trace files are generated in `/opt/app-root/` with naming pattern:
```
granite-8b-flex-101-job-1.json
granite-8b-flex-101-job-2.json
...
```

### Acelyzer Output Files

After analysis, acelyzer creates these files in `/tmp/`:
- `out.json`: Enhanced trace data with computed metrics
- `out_summary.csv`: Overall performance summary
- `out_active.csv`: AIU active time analysis
- `out_categories.csv`: Kernel category breakdown
- `out_categories.txt`: Human-readable category summary
- `out_ts_analysis.csv`: Detailed timestamp analysis

### Example Acelyzer Output

**out_summary.csv:**
```
Time      Total Time      Calls    Mean        Median      Min         Max         StDev       pid    Name
100.00    102687103.722   884      116161.882  112250.665  111329.604  473618.536  37693.002   0      embedding Cmpt Exec
```

**out_active.csv:**
```
Total Kernel Time    Elapsed Time      Start Time           End Time             Active percentage    pid
102687103.722        444060205.598     343908112200.159     344352172405.757     23.12                0
```

Key metrics:
- **Total Kernel Time**: Actual compute time on AIU (in nanoseconds)
- **Elapsed Time**: Wall clock time (in nanoseconds)
- **Active percentage**: AIU utilization percentage
- **Calls**: Number of kernel operations

## Pass/Fail Criteria

### AIU-SMI Test PASSES if:
- Container starts successfully
- VLLM server starts within timeout
- Continuous inference starts successfully
- aiu-smi command executes without errors
- At least one valid metrics data line is captured
- Metrics contain all required headers
- Numeric values can be parsed from metrics

### AIU-SMI Test FAILS if:
- Container fails to start
- VLLM fails to start within timeout
- aiu-smi command fails to execute
- No metrics are captured during the test duration
- Metrics are missing required headers
- Metrics data cannot be parsed

### Acelyzer Test PASSES if:
- aiu-trace-analyzer repository clones successfully
- Container starts with FLEX environment variables
- All FLEX variables are verified in container
- Acelyzer installs successfully
- VLLM server starts within timeout
- Inference requests complete successfully
- Trace files are generated (at least 1 file)
- Acelyzer processes trace files without errors
- Output files (`out.json`, `out_summary.csv`, `out_active.csv`) are created
- Output contains valid performance data

### Acelyzer Test FAILS if:
- Failed to clone aiu-trace-analyzer repository
- Container fails to start
- FLEX environment variables not set correctly
- Acelyzer installation fails
- VLLM fails to start within timeout
- No trace files are generated
- Acelyzer analysis fails
- Output files are missing or empty
- Output data cannot be parsed

## Troubleshooting

### AIU-SMI Test Issues

#### Container fails to start
- Check VFIO device permissions: `ls -l /dev/vfio`
- Verify spyre group membership: `groups`
- Check container logs: `podman logs <container_id>`
- Verify AIU_PCIE_IDS are correct: `lspci | grep AIU`

#### VLLM startup timeout
- Check if model path is correct
- Verify sufficient memory allocated
- Check AIU devices are accessible
- Review container logs for errors

#### aiu-smi command fails
- Verify aiu-monitor is installed in container
- Check if `/opt/aiu-monitor/bin/activate` exists
- Verify container has access to AIU devices
- Check DTCOMPILER_KEEP_EXPORT is set to true

#### No metrics captured
- Verify inference is running (check inference process logs)
- Check if aiu-smi is producing output manually
- Verify AIU devices are functioning
- Check container resource limits

#### Inference fails
- Check VLLM server is running: `podman logs {container_id}`
- Verify port mapping is correct
- Check model is loaded properly
- Ensure python3-requests is installed on host

### Acelyzer Test Issues

#### Failed to clone aiu-trace-analyzer
- Check internet connectivity
- Verify GitHub is accessible
- Check if `/tmp` has write permissions
- Try manual clone: `git clone https://github.com/IBM/aiu-trace-analyzer.git`

#### FLEX variables not set
- Verify container was started with `-e` flags for FLEX variables
- Check with: `podman exec <container_id> bash -c 'cat /proc/1/environ | tr "\0" "\n" | grep FLEX'`
- Restart container with correct environment variables

#### No trace files generated
- Verify FLEX_GLOBAL_PROFILE_PREFIX is set correctly
- Check if ENABLE_FLEX_TIMING=1 is set
- Look for files in different locations: `find / -name "granite-*.json"`
- Check VLLM logs for errors during inference

#### Acelyzer installation fails
- Check if pip is available in container
- Verify `/tmp/aiu-trace-analyzer` exists in container
- Check container logs for Python errors
- Try manual installation: `podman exec <container_id> bash -c 'cd /tmp/aiu-trace-analyzer && pip install .'`

#### Acelyzer analysis fails
- Verify trace files exist and are not empty
- Check trace file format is valid JSON
- Review acelyzer error messages
- Try analyzing a single file first
- Check if enough disk space in `/tmp`

#### Output files missing
- Check if acelyzer completed successfully
- Look for files in `/tmp`: `podman exec <container_id> ls -la /tmp/out*`
- Verify trace files were found by acelyzer
- Check container logs for errors

## Notes

### General
- Tests run as root user for container creation and management
- SELinux is temporarily set to Permissive mode if it's Enforcing
- Required packages are automatically installed during setup (podman, python3-requests, git)
- Containers are automatically cleaned up after test completion
- Tests validate observability functionality, not performance

### AIU-SMI Test Specific
- Container is created with `DTCOMPILER_KEEP_EXPORT=true` environment variable
- Metrics are captured from inside the container using `podman exec`
- aiu-smi runs continuously for the full duration (30 seconds by default)
- All metrics output is captured and displayed at the end (not checked at intervals)
- Metrics are displayed in test logs for manual review

### Acelyzer Test Specific
- Clones aiu-trace-analyzer from GitHub (requires internet connectivity)
- Container is created with FLEX environment variables for trace generation
- Trace files are generated in `/opt/app-root/` directory
- Acelyzer is installed inside the container using pip
- Analysis output files are created in `/tmp/` directory
- Test generates 10 inference requests by default (configurable via TRACE_NUM_REQUESTS)
- Each inference request waits 2 seconds before the next one
- Trace files are automatically found and analyzed
- Performance metrics (AIU utilization, kernel times) are extracted and validated

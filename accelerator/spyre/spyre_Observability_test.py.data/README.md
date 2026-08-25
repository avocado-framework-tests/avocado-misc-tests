# Spyre Observability Tests

This test suite validates the observability functionality on Spyre AIU devices by capturing metrics and analyzing trace data during inference workload execution in a containerized VLLM environment.

# Observability Tools

# AIU-SMI Monitor
The ** aiu-smi ** tool is a command line tool which collects metrics information from the Spyre card, also referred to as AIU(Artificial Intelligence Unit), and prints a performance summary. It stands for AIU System Management Interface. The metrics are per Spyre card.

# Acelyzer (Trace Analyzer)
**Acelyzer ** is a tool to post-process JSON trace files for IBM-AIU performance analysis. It enhances the traces with additional statistics extracted from the trace data itself and (optionally) by combining it with additional output from running a workload.

# Prerequisites

- Power platform(ppc64le)
- Podman installed
- Root access
- Spyre AIU devices configured
- VLLM container image with aiu-monitor
- Python3 with requests library

# Test Structure

The suite includes 4 tests that run sequentially:

1. ** test_aiu_smi_root**: Create root container, capture aiu-smi metrics
2. ** test_trace_analyzer_root**: Use root container, analyze traces with acelyzer
3. ** test_aiu_smi_nonroot**: Create non-root container, capture aiu-smi metrics
4. ** test_trace_analyzer_nonroot**: Use non-root container, analyze traces with acelyzer

# Parameters

# RHAIIS Version Configuration
- `RHAIIS_VERSION`: RHAIIS version string(e.g., "3.5")

# Environment Variables
- `AIU_PCIE_IDS`: PCIe IDs of AIU devices(e.g., "0301:50:00.0")
- `HOST_MODELS_DIR`: Host directory containing models(default: "/opt/ibm/spyre/models/src")
- `VLLM_MODEL_PATH`: Path to model inside container(default: "/models/granite-3.3-8b-instruct")
- `AIU_WORLD_SIZE`: Number of AIU cards(default: "1")
- `MAX_MODEL_LEN`: Maximum model context length(default: "3072")
- `MAX_BATCH_SIZE`: Maximum batch size(default: "16")

# Container Configuration
- `CONTAINER_URL`: Container registry URL
- `CONTAINER_TAG`: Container image tag
- `API_KEY`: Container registry API key(optional)
- `DEVICE`: Device to mount(default: "/dev/vfio")
- `USERNS`: User namespace(default: "keep-id")
- `GROUP_ADD`: Additional groups(default: "keep-groups")
- `SECURITY_OPT`: Security options(default: "label=disable")
- `PIDS_LIMIT`: Process limit(default: "0")
- `MEMORY`: Container memory limit(default: "100G")
- `PORT_MAPPING`: Port mapping(default: "127.0.0.1:8000:8000")

# User Configuration
- `USER`: Non-root username for non-root container tests(e.g., "")
- `SPYRE_GROUP`: Group name for Spyre device access(e.g., "")

# Observability-Specific Parameters
- `METRICS_DURATION`: Duration to capture metrics in seconds(default: "30")
- `TRACE_NUM_REQUESTS`: Number of inference requests for trace generation(default: "10")
- `TRACE_ANALYZER_REPO`: Git repository for acelyzer(default: "https://github.com/IBM/aiu-trace-analyzer.git")

# Quick Start

Run all tests:
```bash
avocado run - -max-parallel-tasks = 1 spyre_Observability_tests.py - m spyre_Observability_tests.py.data/spyre_Observability_tests.yaml
```

Run specific test:
```bash
avocado run spyre_Observability_tests.py: ObservabilityTests.test_aiu_smi_root - m spyre_Observability_tests.py.data/spyre_Observability_tests.yaml
avocado run spyre_Observability_tests.py: ObservabilityTests.test_trace_analyzer_root - m spyre_Observability_tests.py.data/spyre_Observability_tests.yaml
avocado run spyre_Observability_tests.py: ObservabilityTests.test_aiu_smi_nonroot - m spyre_Observability_tests.py.data/spyre_Observability_tests.yaml
avocado run spyre_Observability_tests.py: ObservabilityTests.test_trace_analyzer_nonroot - m spyre_Observability_tests.py.data/spyre_Observability_tests.yaml
```

# Expected Output

# aiu-smi Metrics
```
# ID Date      Time      hostcpu hostmem    pwr  gtemp   busy    rdmem    wrmem
0 20260610  06: 38: 45     15.0     5.4   18.9   30.8      0    0.000    0.000
0 20260610  06: 38: 46      4.6     5.4   19.0   30.8      0    0.000    0.000
```

# Acelyzer Output
- `out.json`: Enhanced trace with metrics
- `out_summary.csv`: Performance summary(kernel times, calls, statistics)
- `out_active.csv`: AIU utilization analysis
- `out_categories.csv`: Kernel category breakdown

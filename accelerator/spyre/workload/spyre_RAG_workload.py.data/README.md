# Spyre RAG Workload Tests

This test suite runs continuous RAG (Retrieval-Augmented Generation) inference workloads against a running Spyre VLLM container while simultaneously collecting AIU performance metrics into Avocado's results directory.

## Files

- `spyre_RAG_workload.yaml`: Avocado test parameters for configuring container name, workload duration, worker concurrency, and metrics commands.
- `rag_prompts.json`: Pre-defined context-question prompt pairs cycled during inference workload runs.

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `USE_CASE` | `rag` | Workload use case name |
| `CONTAINER_NAME` | `spyre-rag` | Name of running target Podman container |
| `WORKLOAD_MINS` | `5` | Workload execution duration in minutes |
| `WORKERS` | `2` | Number of concurrent inference threads |
| `CHECK_INTERVAL` | `30` | Seconds between live throughput/metric snapshots |
| `PROMPTS_FILE` | `rag_prompts.json` | JSON file containing RAG prompt list |
| `STATS_COMMAND` | `aiu-smi --csv` | AIU metrics command to run inside container |
| `METRICS_FILE` | `""` | Optional output file for AIU metrics (defaults to `self.logdir`) |
| `USER` | `""` | User running the container (defaults to current user) |
| `PORT_MAPPING` | `127.0.0.1:8000:8000` | Port mapping fallback |

## Execution

### 1. Timed Workload Execution
```bash
avocado run spyre_RAG_workload.py:SpyreRAGWorkloadTest.test_run_workload \
    -m spyre_RAG_workload.py.data/spyre_RAG_workload.yaml
```

### 2. Explicit Start / Stop Lifecycle
```bash
# Start inference workload & metrics collection in background
avocado run spyre_RAG_workload.py:SpyreRAGWorkloadTest.test_start_RAG_workload \
    -m spyre_RAG_workload.py.data/spyre_RAG_workload.yaml

# Stop workload & metrics collection, calculate throughput, and preserve logs
avocado run spyre_RAG_workload.py:SpyreRAGWorkloadTest.test_stop_RAG_workload \
    -m spyre_RAG_workload.py.data/spyre_RAG_workload.yaml
```

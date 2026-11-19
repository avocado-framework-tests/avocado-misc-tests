# Spyre Entity Extraction Workload Tests

This test suite runs continuous named-entity-extraction inference workloads against a running Spyre VLLM container while simultaneously collecting AIU performance metrics into Avocado's results directory. Each response is validated against the expected entities of the sample.

## Files

- `spyre_Entity_Extract_workload.yaml`: Avocado test parameters for configuring container name, workload duration, worker concurrency, validation threshold, and metrics commands.
- `entity_extraction_prompts.json`: Sample entity dataset (input text plus expected entities) cycled during inference workload runs. Each entry has `name`, `text` and `expected_entities`.

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `USE_CASE` | `entity_extract` | Workload use case name |
| `CONTAINER_NAME` | `spyre-entity-extract` | Name of running target Podman container |
| `WORKLOAD_MINS` | `5` | Workload execution duration in minutes |
| `WORKERS` | `2` | Number of concurrent inference threads |
| `CHECK_INTERVAL` | `30` | Seconds between live throughput/metric snapshots |
| `PROMPTS_FILE` | `entity_extraction_prompts.json` | JSON file containing the sample entity dataset |
| `MIN_ENTITY_MATCH_PCT` | `50` | Minimum % of expected entities found for a response to be valid |
| `STATS_COMMAND` | `aiu-smi --csv` | AIU metrics command to run inside container |
| `METRICS_FILE` | `""` | Optional output file for AIU metrics (defaults to `self.logdir`) |
| `USER` | `""` | User running the container (defaults to current user) |
| `PORT_MAPPING` | `127.0.0.1:8000:8000` | Port mapping fallback |

## Execution

### 1. Timed Workload Execution
```bash
avocado run spyre_Entity_Extract_workload.py:SpyreEntityExtractWorkloadTest.test_run_workload \
    -m spyre_Entity_Extract_workload.py.data/spyre_Entity_Extract_workload.yaml
```

### 2. Explicit Start / Stop Lifecycle
```bash
# Start inference workload & metrics collection in background
avocado run spyre_Entity_Extract_workload.py:SpyreEntityExtractWorkloadTest.test_start_entity_extract_workload \
    -m spyre_Entity_Extract_workload.py.data/spyre_Entity_Extract_workload.yaml

# Stop workload & metrics collection, calculate throughput, and preserve logs
avocado run spyre_Entity_Extract_workload.py:SpyreEntityExtractWorkloadTest.test_stop_entity_extract_workload \
    -m spyre_Entity_Extract_workload.py.data/spyre_Entity_Extract_workload.yaml
```

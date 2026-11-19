# Spyre Embedding Workload Tests

This test suite runs a continuous, concurrent embedding-generation workload against a running Spyre VLLM container (OpenAI-compatible `/v1/embeddings` endpoint) while simultaneously collecting AIU performance metrics into Avocado's results directory. Every response is validated: the number of embeddings must match the batch size, all vectors must have the same dimension, contain only finite numbers, and be non-zero.

## Files

- `spyre_Embedding_workload.yaml`: Avocado test parameters for configuring container name, workload duration, worker concurrency, batch size, and metrics commands.
- `embedding_texts.json`: Sample texts (JSON list of strings) cycled to build the embedding batches.

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `USE_CASE` | `embedding` | Workload use case name |
| `CONTAINER_NAME` | `spyre-embedding` | Name of running target Podman container |
| `WORKLOAD_MINS` | `5` | Workload execution duration in minutes |
| `WORKERS` | `8` | Number of concurrent request threads |
| `CHECK_INTERVAL` | `30` | Seconds between live throughput/metric snapshots |
| `BATCH_SIZE` | `50` | Number of texts per embeddings request |
| `REQUEST_TIMEOUT` | `600` | Per-request timeout in seconds |
| `PROMPTS_FILE` | `embedding_texts.json` | JSON file containing the sample texts |
| `STATS_COMMAND` | `aiu-smi --csv` | AIU metrics command to run inside container |
| `METRICS_FILE` | `""` | Optional output file for AIU metrics (defaults to `self.logdir`) |
| `USER` | `""` | User running the container (defaults to current user) |
| `PORT_MAPPING` | `127.0.0.1:8000:8000` | Port mapping fallback |

## Execution

### 1. Timed Workload Execution
```bash
avocado run spyre_Embedding_workload.py:SpyreEmbeddingWorkloadTest.test_run_workload \
    -m spyre_Embedding_workload.py.data/spyre_Embedding_workload.yaml
```

### 2. Explicit Start / Stop Lifecycle
```bash
# Start embedding workload & metrics collection in background
avocado run spyre_Embedding_workload.py:SpyreEmbeddingWorkloadTest.test_start_embedding_workload \
    -m spyre_Embedding_workload.py.data/spyre_Embedding_workload.yaml

# Stop workload & metrics collection, report throughput, and preserve logs
avocado run spyre_Embedding_workload.py:SpyreEmbeddingWorkloadTest.test_stop_embedding_workload \
    -m spyre_Embedding_workload.py.data/spyre_Embedding_workload.yaml
```

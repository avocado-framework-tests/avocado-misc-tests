# Spyre Reranker Workload Tests

This test suite runs a continuous, concurrent reranker (query/document scoring) workload against a running Spyre VLLM container (`/score` endpoint, BGE reranker) while simultaneously collecting AIU performance metrics into Avocado's results directory.

## Files

- `spyre_Reranker_workload.yaml`: Avocado test parameters for configuring container name, workload duration, worker concurrency, batch size, accuracy threshold, and metrics commands.
- `demo_scoring_dataset.csv`: Sample scoring dataset with columns `document`, `query` and `score` (expected relevance). Requests are built from it by grouping all documents of a query into the same batch.

## Validation

- Every response must contain exactly one finite numeric score per submitted pair.
- For each query with at least two documents, the document with the highest expected score must also get the highest returned score. The run fails if the ranking accuracy is below `MIN_RANK_ACCURACY_PCT`.
- The distance to the dataset's expected scores (average/maximum absolute difference, share of scores within rtol=0.02 / atol=0.03) is reported but does not fail the test, because the dataset scores are reference values.

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `USE_CASE` | `reranker` | Workload use case name |
| `CONTAINER_NAME` | `spyre-reranker` | Name of running target Podman container |
| `WORKLOAD_MINS` | `5` | Workload execution duration in minutes |
| `WORKERS` | `8` | Number of concurrent request threads |
| `CHECK_INTERVAL` | `30` | Seconds between live throughput/metric snapshots |
| `BATCH_SIZE` | `20` | Minimum number of pairs per `/score` request |
| `REQUEST_TIMEOUT` | `600` | Per-request timeout in seconds |
| `DATASET_FILE` | `demo_scoring_dataset.csv` | CSV dataset (`document`, `query`, `score`) |
| `MIN_RANK_ACCURACY_PCT` | `80` | Minimum % of queries ranked correctly |
| `STATS_COMMAND` | `aiu-smi --csv` | AIU metrics command to run inside container |
| `METRICS_FILE` | `""` | Optional output file for AIU metrics (defaults to `self.logdir`) |
| `USER` | `""` | User running the container (defaults to current user) |
| `PORT_MAPPING` | `127.0.0.1:8000:8000` | Port mapping fallback |

## Execution

### 1. Timed Workload Execution
```bash
avocado run spyre_Reranker_workload.py:SpyreRerankerWorkloadTest.test_run_workload \
    -m spyre_Reranker_workload.py.data/spyre_Reranker_workload.yaml
```

### 2. Explicit Start / Stop Lifecycle
```bash
# Start reranker workload & metrics collection in background
avocado run spyre_Reranker_workload.py:SpyreRerankerWorkloadTest.test_start_reranker_workload \
    -m spyre_Reranker_workload.py.data/spyre_Reranker_workload.yaml

# Stop workload & metrics collection, report throughput, and preserve logs
avocado run spyre_Reranker_workload.py:SpyreRerankerWorkloadTest.test_stop_reranker_workload \
    -m spyre_Reranker_workload.py.data/spyre_Reranker_workload.yaml
```

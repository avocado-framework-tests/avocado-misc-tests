# Spyre Vision Workload Tests

This test suite runs a continuous image-question-answering workload against a running Spyre VLLM container serving a vision-language model (`granite-vision-3.3-2b`) through the OpenAI-compatible `/v1/chat/completions` endpoint, while simultaneously collecting AIU performance metrics into Avocado's results directory.

## Files

- `spyre_Vision_workload.yaml`: Avocado test parameters (container name, duration, workers, token limit, validation threshold, metrics command).
- `vision_prompts.json`: Dataset manifest. Each entry has `image` (path relative to the `.data` folder), `question`, `expected_keywords`, `match` (`any` or `all`) and `category`.
- `images/`: 13 small synthetic 384x384 PNG images with unambiguous content: text (OCR), shapes, colors, counting, a bar chart, an invoice, a table, a traffic light, flag stripes, an arrow and a stop sign. The 25 prompts reuse the images, with several questions per image.
- `generate_vision_dataset.py`: Script that regenerates `images/` deterministically (needs Pillow; only required to regenerate, not to run the test). Run `python3 generate_vision_dataset.py [output_dir]`.

## Request format

Each image is base64 encoded once when the dataset is loaded and sent as a data URI:

```json
{"model": "<served model>",
 "messages": [{"role": "user", "content": [
     {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
     {"type": "text", "text": "<question>"}]}],
 "max_tokens": 64, "temperature": 0.0}
```

## Validation

- An answer is valid when it contains at least one (`match: any`) or all (`match: all`) of the expected keywords, compared case-insensitively.
- The run fails if no request succeeds, if no answer is valid, or if the share of valid answers is below `MIN_VALID_PCT`.
- Results are also reported per category (ocr, color, shape, counting, chart, document, table, scene).

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `USE_CASE` | `vision` | Workload use case name |
| `CONTAINER_NAME` | `spyre-vision` | Name of running target Podman container |
| `VLLM_MODEL_PATH` | `/models/granite-vision-3.3-2b` | Model path used when the container was created |
| `HF_MODEL_NAME` | `ibm-granite/granite-vision-3.3-2b` | HuggingFace model name |
| `WORKLOAD_MINS` | `5` | Workload execution duration in minutes |
| `WORKERS` | `2` | Number of concurrent request threads |
| `CHECK_INTERVAL` | `30` | Seconds between live throughput/metric snapshots |
| `MAX_TOKENS` | `64` | Max tokens generated per answer |
| `REQUEST_TIMEOUT` | `120` | Per-request timeout in seconds |
| `PROMPTS_FILE` | `vision_prompts.json` | Dataset manifest |
| `MIN_VALID_PCT` | `50` | Minimum % of valid answers |
| `STATS_COMMAND` | `aiu-smi --csv` | AIU metrics command to run inside container |
| `METRICS_FILE` | `""` | Optional output file for AIU metrics (defaults to `self.logdir`) |
| `USER` | `""` | User running the container (defaults to current user) |
| `PORT_MAPPING` | `127.0.0.1:8000:8000` | Port mapping fallback |

The container itself can be created with `spyre_Entity_Extraction_test.py` using `spyre_EE_test_Granite-Vision-3.3-2b.yaml`, or with any equivalent `podman run` of the vLLM image serving `/models/granite-vision-3.3-2b`.

## Execution

### 1. Timed Workload Execution
```bash
avocado run spyre_Vision_workload.py:SpyreVisionWorkloadTest.test_run_workload \
    -m spyre_Vision_workload.py.data/spyre_Vision_workload.yaml
```

### 2. Explicit Start / Stop Lifecycle
```bash
# Start vision workload & metrics collection in background
avocado run spyre_Vision_workload.py:SpyreVisionWorkloadTest.test_start_vision_workload \
    -m spyre_Vision_workload.py.data/spyre_Vision_workload.yaml

# Stop workload & metrics collection, report throughput, and preserve logs
avocado run spyre_Vision_workload.py:SpyreVisionWorkloadTest.test_stop_vision_workload \
    -m spyre_Vision_workload.py.data/spyre_Vision_workload.yaml
```

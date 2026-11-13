# spyre_RAG_Quadlet_test

Tests the **RAG (Retrieval Augmented Generation)** use case on the Spyre AI
accelerator using a Podman Quadlet systemd user service.

RAG is the only use case that uses **all** available AIU PCIe IDs simultaneously
(multi-device tensor parallelism).

## Test methods

| Method | What it does |
|---|---|
| `test_create_container` | Writes the quadlet `.container` file, starts the systemd user service, and waits up to 600 s for `"Application startup complete."` in the VLLM logs |
| `test_remove_container` | Stops the service, force-removes the container, deletes the quadlet file, and reloads the daemon |

## Usage

```bash
# Run both methods in sequence
avocado run --max-parallel-tasks=1 \
    spyre_RAG_Quadlet_test.py \
    -m spyre_RAG_Quadlet_test.py.data/spyre_RAG_Quadlet_test.yaml

# Run a single method
avocado run --max-parallel-tasks=1 \
    spyre_RAG_Quadlet_test.py:SpyreRAGQuadletTest.test_create_container \
    -m spyre_RAG_Quadlet_test.py.data/spyre_RAG_Quadlet_test.yaml
```

## Required YAML parameters

| Parameter | Description |
|---|---|
| `RHAIIS_VERSION` | RHAIIS version string (`"3.3"`, `"3.4"`, `"3.5"`, `"3.6"`) |
| `AIU_PCIE_IDS` | Space-separated PCIe IDs of all AIU devices |
| `CONTAINER_URL` | Container registry URL |
| `CONTAINER_TAG` | Container image tag |
| `SPYRE_GROUP` | Group that owns the VFIO devices |
| `USER` | Non-root user that runs the Podman session |

## Optional YAML parameters

| Parameter | Default | Description |
|---|---|---|
| `HOST_MODELS_DIR` | `/opt/ibm/spyre/models/src` | Host path for model storage |
| `VLLM_MODEL_PATH` | `/models/granite-3.3-8b-instruct` | Container-side model path |
| `HF_MODEL_NAME` | `ibm-granite/granite-3.3-8b-instruct` | HuggingFace model ID to download if not present |
| `AIU_WORLD_SIZE` | `4` | Tensor parallel size |
| `MAX_MODEL_LEN` | `32768` | Maximum sequence length |
| `MAX_BATCH_SIZE` | `32` | Maximum concurrent sequences |
| `MEMORY` | `200G` | Container memory limit |
| `SHM_SIZE` | `2G` | Shared memory size |
| `PORT_MAPPING` | `127.0.0.1:8000:8000` | Host-to-container port mapping |
| `API_KEY` | _(empty)_ | Container registry API key |

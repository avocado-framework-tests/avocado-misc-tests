# spyre_Embedding_Quadlet_test

Tests the **Embedding** use case on the Spyre AI accelerator using a Podman
Quadlet systemd user service.

Uses the **first AIU PCIe ID only**.

## Test methods

| Method | What it does |
|---|---|
| `test_create_container` | Writes the quadlet `.container` file, starts the systemd user service, and waits up to 600 s for `"Application startup complete."` |
| `test_remove_container` | Stops the service, force-removes the container, deletes the quadlet file, reloads the daemon |

## Usage

```bash
# Run both methods in sequence
avocado run --max-parallel-tasks=1 \
    spyre_Embedding_Quadlet_test.py \
    -m spyre_Embedding_Quadlet_test.py.data/spyre_Embedding_Quadlet_test.yaml

# Run a single method
avocado run --max-parallel-tasks=1 \
    spyre_Embedding_Quadlet_test.py:SpyreEmbeddingQuadletTest.test_create_container \
    -m spyre_Embedding_Quadlet_test.py.data/spyre_Embedding_Quadlet_test.yaml
```

## Required YAML parameters

| Parameter | Description |
|---|---|
| `RHAIIS_VERSION` | RHAIIS version string (`"3.3"`, `"3.4"`, `"3.5"`, `"3.6"`) |
| `AIU_PCIE_IDS` | Space-separated PCIe IDs (first one used) |
| `CONTAINER_URL` | Container registry URL |
| `CONTAINER_TAG` | Container image tag |
| `SPYRE_GROUP` | Group that owns the VFIO devices |
| `USER` | Non-root user that runs the Podman session |

## Optional YAML parameters

| Parameter | Default | Description |
|---|---|---|
| `HOST_MODELS_DIR` | `/opt/ibm/spyre/models/src` | Host path for model storage |
| `VLLM_MODEL_PATH` | `/models/granite-embedding-125m-english` | Container-side model path |
| `HF_MODEL_NAME` | `ibm-granite/granite-embedding-125m-english` | HuggingFace model ID to download if not present |
| `AIU_WORLD_SIZE` | `1` | Tensor parallel size |
| `MAX_MODEL_LEN` | `512` | Maximum sequence length |
| `MAX_BATCH_SIZE` | `4` | Maximum concurrent sequences |
| `MEMORY` | `50G` | Container memory limit |
| `PORT_MAPPING` | `127.0.0.1:8000:8000` | Host-to-container port mapping |
| `API_KEY` | _(empty)_ | Container registry API key |

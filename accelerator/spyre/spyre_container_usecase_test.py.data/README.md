# Spyre Stack Test Suite

This test suite validates various Spyre AI accelerator use cases with different models, batch sizes, and configurations.

## Overview

The Spyre Stack Test Suite provides comprehensive testing for:
- **RAG (Retrieval-Augmented Generation)**: Large language model inference with multi-card support
- **Entity Extraction**: Text processing with chunked prefill optimization
- **RAG Embedding**: Text embedding generation with various batch sizes and prompt lengths
- **Reranker/Scoring**: Document reranking and scoring capabilities

## Test Structure

```
accelerator/spyre/
├── spyre_stack_test.py              # Main test file
└── spyre_stack_test.py.data/        # Configuration files
    ├── README.md                     # This file
    ├── rag_granite_8b.yaml          # RAG configuration
    ├── entity_extraction_granite_8b.yaml  # Entity extraction configuration
    ├── rag_embedding_granite_125m.yaml    # Embedding configuration (template)
    ├── reranker_bge_m3.yaml         # Reranker configuration
    ├── embedding_pl64_bs1.yaml      # Embedding: PL=64, BS=1
    ├── embedding_pl512_bs256.yaml   # Embedding: PL=512, BS=256
    └── ...                          # Additional embedding configurations
```

## Use Cases

### 1. RAG (Retrieval-Augmented Generation)

**Model**: Granite 3.3-8B Instruct  
**Configuration**:
- Batch size: 32
- Max context: 32768 tokens (input/output)
- Cards per container: 4
- Image: ``

**Commands**:
```bash
# Using specific test method
avocado run spyre_stack_test.py:SpyreStackTest.test_rag_granite_8b \
    --mux-yaml spyre_stack_test.py.data/rag_granite_8b.yaml

# Or using generic test method
avocado run spyre_stack_test.py:SpyreStackTest.test_spyre_container \
    --mux-yaml spyre_stack_test.py.data/rag_granite_8b.yaml
```

### 2. Entity Extraction

**Model**: Granite 3.3-8B Instruct  
**Configuration**:
- Batch size: 16
- Max context: 3072 tokens (input/output)
- Cards per container: 1
- Uses chunked prefill (chunk length: 1024)
- Image: `rhaiis:3.3.0-1771459423`

**Commands**:
```bash
# Using specific test method
avocado run spyre_stack_test.py:SpyreStackTest.test_entity_extraction_granite_8b \
    --mux-yaml spyre_stack_test.py.data/entity_extraction_granite_8b.yaml

# Or using generic test method
avocado run spyre_stack_test.py:SpyreStackTest.test_spyre_container \
    --mux-yaml spyre_stack_test.py.data/entity_extraction_granite_8b.yaml
```

### 3. RAG Embedding

**Model**: Granite Embedding 125M English  
**Configuration**:
- Batch sizes: 1, 2, 16, 32, 64, 128, 256
- Prompt lengths: 64, 128, 256, 512 tokens
- Max output: 768 tokens
- Cards per container: 1
- Image: `rhaiis:3.3.0-1771459423`

**Command Examples**:
```bash
# Using specific test method with default config
avocado run spyre_stack_test.py:SpyreStackTest.test_rag_embedding_granite_125m \
    --mux-yaml spyre_stack_test.py.data/rag_embedding_granite_125m.yaml

# Using generic test method with specific embedding configs
# Test with PL=64, BS=1
avocado run spyre_stack_test.py:SpyreStackTest.test_spyre_container \
    --mux-yaml spyre_stack_test.py.data/embedding_pl64_bs1.yaml

# Test with PL=512, BS=256
avocado run spyre_stack_test.py:SpyreStackTest.test_spyre_container \
    --mux-yaml spyre_stack_test.py.data/embedding_pl512_bs256.yaml
```

### 4. Reranker/Scoring

**Model**: BGE Reranker v2-m3  
**Configuration**:
- Batch size: 4
- Max context: 8192 tokens (input/output)
- Cards per container: 1
- Image: ``

**Commands**:
```bash
# Using specific test method
avocado run spyre_stack_test.py:SpyreStackTest.test_reranker_bge_m3 \
    --mux-yaml spyre_stack_test.py.data/reranker_bge_m3.yaml

# Or using generic test method
avocado run spyre_stack_test.py:SpyreStackTest.test_spyre_container \
    --mux-yaml spyre_stack_test.py.data/reranker_bge_m3.yaml
```

## Configuration Parameters

All test configurations are defined in YAML files. Key parameters include:

### Required Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `TEST_NAME` | Unique test identifier | `"RAG_Granite_8B"` |
| `CONTAINER_URL` | Container registry URL | `""` |
| `CONTAINER_TAG` | Container image tag | `""` |
| `AIU_PCIE_IDS` | Space-separated AIU PCIe IDs | `"0233:70:00.0 0234:80:00.0 0234:80:00.0 0234:80:00.0"` |
| `HOST_MODELS_DIR` | Host directory with models | `"/opt/ibm/spyre/models"` |
| `VLLM_MODEL_PATH` | Model path in container | `"/models/granite-3.3-8b-instruct"` |
| `AIU_WORLD_SIZE` | Number of AIU cards | `4` |
| `MAX_MODEL_LEN` | Maximum model context length | `32768` |
| `MAX_BATCH_SIZE` | Maximum batch size | `32` |

### Optional Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `MEMORY` | Container memory limit | `"200G"` |
| `SHM_SIZE` | Shared memory size | `"2G"` |
| `DEVICE` | Device to mount | `"/dev/vfio"` |
| `PRIVILEGED` | Run in privileged mode | `"true"` |
| `PIDS_LIMIT` | PIDs limit | `"0"` (unlimited) |
| `USERNS` | User namespace mode | `"keep-id"` |
| `GROUP_ADD` | Group add mode | `"keep-groups"` |
| `PORT_MAPPING` | Port mapping | `"127.0.0.1::8000"` |
| `VLLM_SPYRE_USE_CB` | Use CB flag | `"1"` |
| `VLLM_DT_CHUNK_LEN` | DT chunk length | `null` |
| `VLLM_SPYRE_USE_CHUNKED_PREFILL` | Use chunked prefill | `null` |
| `ENABLE_PREFIX_CACHING` | Enable prefix caching | `"true"` |
| `STARTUP_TIMEOUT` | Container startup timeout (seconds) | `600` |
| `API_KEY` | Container registry API key | `""` |
| `DOWNLOAD_MODEL` | Enable automatic model download | `"false"` |
| `HF_MODEL_ID` | Hugging Face model ID | `""` |
| `MODEL_NAME` | Local model directory name | `""` |

## Prerequisites

1. **Hardware**: IBM Power system with Spyre AI accelerators
2. **Software**:
   - Podman installed and configured
   - Avocado test framework
   - Access to container registry (with API key)
   - Python pip (for Hugging Face CLI installation)
3. **Models**: Either:
   - Pre-downloaded models in `HOST_MODELS_DIR`, OR
   - Enable automatic model download (see Model Download section below)
4. **VFIO**: Spyre devices configured with VFIO

## Setup

1. **Install Avocado**:
```bash
pip install avocado-framework
```

2. **Configure Models** (Choose one option):

   **Option A: Automatic Model Download (Recommended)**
   
   Enable automatic model download in YAML files:
   ```yaml
   DOWNLOAD_MODEL: "true"
   HF_MODEL_ID: "ibm-granite/granite-3.3-8b-instruct"
   MODEL_NAME: "granite-3.3-8b-instruct"
   HOST_MODELS_DIR: "/opt/ibm/spyre/models"
   ```
   
   The test will automatically:
   - Install Hugging Face CLI (`pip install -U "huggingface_hub[cli]"`)
   - Create the models directory (`/opt/ibm/spyre/models/`)
   - Download the model from Hugging Face Hub
   - Verify the download
   ```
   
   Then set `DOWNLOAD_MODEL: "false"` in YAML files.

3. **Set API Key** (if required):
```bash
export API_KEY="your-api-key-here"
```

4. **Update YAML Files**:
   - Edit YAML files to match your environment
   - Update `AIU_PCIE_IDS` with your actual PCIe IDs
   - Update `CONTAINER_URL` and `CONTAINER_TAG` if using different images
   - Update `HOST_MODELS_DIR` if models are in different locations
   - Set `DOWNLOAD_MODEL` to "true" or "false" based on your preference

## Running Tests

### Test Methods Available

The test suite provides both specific and generic test methods:

1. **Specific Test Methods** (recommended for standard use cases):
   - `test_rag_granite_8b` - RAG with Granite 3.3-8B
   - `test_entity_extraction_granite_8b` - Entity Extraction with Granite 3.3-8B
   - `test_rag_embedding_granite_125m` - RAG Embedding with Granite 125M
   - `test_reranker_bge_m3` - Reranker with BGE v2-m3

2. **Generic Test Method** (for custom configurations):
   - `test_spyre_container` - Flexible test for any YAML configuration

### Single Test

Run a specific use case using the dedicated test method:
```bash
# RAG test
avocado run spyre_stack_test.py:SpyreStackTest.test_rag_granite_8b \
    --mux-yaml spyre_stack_test.py.data/rag_granite_8b.yaml

# Entity Extraction test
avocado run spyre_stack_test.py:SpyreStackTest.test_entity_extraction_granite_8b \
    --mux-yaml spyre_stack_test.py.data/entity_extraction_granite_8b.yaml

# Embedding test
avocado run spyre_stack_test.py:SpyreStackTest.test_rag_embedding_granite_125m \
    --mux-yaml spyre_stack_test.py.data/rag_embedding_granite_125m.yaml

# Reranker test
avocado run spyre_stack_test.py:SpyreStackTest.test_reranker_bge_m3 \
    --mux-yaml spyre_stack_test.py.data/reranker_bge_m3.yaml
```

Or use the generic test method:
```bash
avocado run spyre_stack_test.py:SpyreStackTest.test_spyre_container \
    --mux-yaml spyre_stack_test.py.data/rag_granite_8b.yaml
```

### Run All Standard Tests

Run all four standard use cases:
```bash
# Run all tests with their respective configurations
avocado run spyre_stack_test.py:SpyreStackTest.test_rag_granite_8b \
            spyre_stack_test.py:SpyreStackTest.test_entity_extraction_granite_8b \
            spyre_stack_test.py:SpyreStackTest.test_rag_embedding_granite_125m \
            spyre_stack_test.py:SpyreStackTest.test_reranker_bge_m3 \
    --mux-yaml spyre_stack_test.py.data/rag_granite_8b.yaml \
               spyre_stack_test.py.data/entity_extraction_granite_8b.yaml \
               spyre_stack_test.py.data/rag_embedding_granite_125m.yaml \
               spyre_stack_test.py.data/reranker_bge_m3.yaml
```

### Multiple Embedding Tests

Run multiple embedding configurations sequentially:
```bash
# Run all embedding tests with different batch sizes and prompt lengths
for config in spyre_stack_test.py.data/embedding_*.yaml; do
    avocado run spyre_stack_test.py:SpyreStackTest.test_spyre_container \
        --mux-yaml "$config"
done
```

### With Custom Parameters

Override YAML parameters from command line:
```bash
avocado run spyre_stack_test.py:SpyreStackTest.test_rag_granite_8b \
    --mux-yaml spyre_stack_test.py.data/rag_granite_8b.yaml \
    -p MAX_BATCH_SIZE=64 \
    -p STARTUP_TIMEOUT=900
```

## Model Download Feature

The test suite includes automatic model downloading from Hugging Face Hub. This feature:

1. **Automatically installs** Hugging Face CLI if not present
2. **Creates** the models directory if it doesn't exist
3. **Downloads** models from Hugging Face Hub
4. **Verifies** the download was successful
5. **Skips** download if model already exists locally

### Supported Models

| Use Case | Hugging Face Model ID | Local Directory Name |
|----------|----------------------|---------------------|
| RAG | `ibm-granite/granite-3.3-8b-instruct` | `granite-3.3-8b-instruct` |
| Entity Extraction | `ibm-granite/granite-3.3-8b-instruct` | `granite-3.3-8b-instruct` |
| Embedding | `ibm-granite/granite-embedding-125m-english` | `granite-embedding-125m-english` |
| Reranker | `BAAI/bge-reranker-v2-m3` | `bge-reranker-v2-m3` |

### Configuration

Enable model download in your YAML file:

```yaml
# Enable automatic model download
DOWNLOAD_MODEL: "true"

# Specify Hugging Face model ID
HF_MODEL_ID: "ibm-granite/granite-3.3-8b-instruct"

# Specify local directory name (will be created under HOST_MODELS_DIR)
MODEL_NAME: "granite-3.3-8b-instruct"

# Base directory for all models
HOST_MODELS_DIR: "/opt/ibm/spyre/models"
```

### How It Works

When `DOWNLOAD_MODEL: "true"` is set:

1. Test checks if `huggingface-cli` is installed
2. If not, installs it: `pip install -U "huggingface_hub[cli]"`
3. Creates models directory: `mkdir -p /opt/ibm/spyre/models/`
4. Downloads model: `huggingface-cli download --local-dir /opt/ibm/spyre/models/MODEL_NAME HF_MODEL_ID`
5. Verifies download by checking directory contents
6. If model already exists, skips download

### Multiple Models

The test suite intelligently handles multiple models:
- Each model is downloaded to its own subdirectory
- Models are reused across tests if they share the same model
- Example structure:
  ```
  /opt/ibm/spyre/models/
  ├── granite-3.3-8b-instruct/
  ├── granite-embedding-125m-english/
  └── bge-reranker-v2-m3/
  ```

### Disabling Model Download

To use pre-downloaded models, set:
```yaml
DOWNLOAD_MODEL: "false"
```

The test will then expect models to already exist in `HOST_MODELS_DIR`.

## Creating Custom Configurations

To create a new test configuration:

1. Copy an existing YAML file:
```bash
cp spyre_stack_test.py.data/rag_granite_8b.yaml \
   spyre_stack_test.py.data/my_custom_test.yaml
```

2. Edit the parameters:
```yaml
TEST_NAME: "My_Custom_Test"
CONTAINER_URL: "your-registry/your-image"
CONTAINER_TAG: "your-tag"
AIU_PCIE_IDS: "your:pcie:ids"
# ... other parameters
```

3. Run the test:
```bash
avocado run spyre_stack_test.py:SpyreStackTest.test_spyre_container \
    --mux-yaml spyre_stack_test.py.data/my_custom_test.yaml
```

## Embedding Test Matrix

For comprehensive embedding testing, create YAML files for all combinations:

| Prompt Length | Batch Sizes |
|---------------|-------------|
| 64 | 1, 2, 16, 32, 64, 128, 256 |
| 128 | 1, 2, 16, 32, 64, 128, 256 |
| 256 | 1, 2, 16, 32, 64, 128, 256 |
| 512 | 1, 2, 16, 32, 64, 128, 256 |

Example script to generate all configurations:
```bash
#!/bin/bash
for pl in 64 128 256 512; do
    for bs in 1 2 16 32 64 128 256; do
        cat > spyre_stack_test.py.data/embedding_pl${pl}_bs${bs}.yaml <<EOF
TEST_NAME: "Embedding_PL${pl}_BS${bs}"
CONTAINER_URL: ""
CONTAINER_TAG: ""
CONTAINER_REGISTRY: "icr.io"
AIU_PCIE_IDS: "0333:70:00.0"
AIU_WORLD_SIZE: 1
HOST_MODELS_DIR: "/opt/ibm/spyre/models"
VLLM_MODEL_PATH: "/models/granite-embedding-125m-english"
MAX_MODEL_LEN: ${pl}
MAX_BATCH_SIZE: ${bs}
MEMORY: "1500G"
SHM_SIZE: "2G"
DEVICE: "/dev/vfio"
PRIVILEGED: "true"
PIDS_LIMIT: "0"
USERNS: "keep-id"
GROUP_ADD: "keep-groups"
PORT_MAPPING: "127.0.0.1::8000"
VLLM_SPYRE_USE_CB: "1"
VLLM_DT_CHUNK_LEN: 0
VLLM_SPYRE_USE_CHUNKED_PREFILL: 0
ENABLE_PREFIX_CACHING: "false"
STARTUP_TIMEOUT: 600
EOF
    done
done
```

## Troubleshooting

### Container Fails to Start

1. **Check VFIO devices**:
```bash
ls -l /dev/vfio/
```

2. **Verify AIU PCIe IDs**:
```bash
lspci -nn | grep -i aiu
```

3. **Check SELinux**:
```bash
getenforce  # Should be Permissive or Disabled
```

4. **Review container logs**:
```bash
podman logs <container-id>
```

### VFIO Permission Errors

Ensure user is in the correct group:
```bash
groups  # Should include spyre or vfio group
```

### Model Not Found

Verify model path:
```bash
ls -l /opt/ibm/spyre/models/
```

### Memory Issues

Increase memory limits in YAML:
```yaml
MEMORY: "400G"  # Increase as needed
SHM_SIZE: "4G"  # Increase for larger batches
```

## Test Results

Test results are saved in Avocado's results directory:
```bash
# View latest test results
avocado list --loaders file -- ~/avocado/job-results/latest/

# View test logs
cat ~/avocado/job-results/latest/test-results/*/debug.log
```

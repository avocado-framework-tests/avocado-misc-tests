# Spyre VFIO Serviceability Test

## Overview

This test suite validates VFIO (Virtual Function I/O) device access for IBM Spyre AI accelerators on Power systems. It tests various user permission scenarios and includes AI inference workload testing with performance metrics collection.

## Test Description

The serviceability test verifies that:
1. VFIO Spyre devices are properly configured
2. User group membership controls device access correctly
3. Containers can access VFIO devices based on permissions
4. VLLM (Very Large Language Model) inference works correctly
5. AIU (AI Unit) performance metrics can be collected

## Test Scenarios

### 1. test_root_in_spyre_group
Tests VFIO device access when root user IS in the spyre group.

**Expected Result:** Container should successfully access VFIO devices, VLLM should start, and inference requests should complete successfully.

**Test Flow:**
- Configure Spyre devices using ServiceReport
- Add root user to spyre group
- Start container in fresh root session
- Wait for VLLM startup
- Run inference tests with AIU metrics collection
- Verify successful VFIO access and inference completion

### 2. test_root_not_in_spyre_group
Tests VFIO device access when root user is NOT in the spyre group.

**Expected Result:** Container should fail to access VFIO devices.

**Test Flow:**
- Remove root user from spyre group
- Start container in fresh root session
- Monitor for VFIO access failures
- Verify expected failure

### 3. test_user_in_spyre_group
Tests VFIO device access when non-root user IS in the spyre group.

**Expected Result:** Container should successfully access VFIO devices, VLLM should start, and inference requests should complete successfully.

**Test Flow:**
- Create test user
- Add user to spyre group
- Start container as user in fresh session
- Wait for VLLM startup
- Run inference tests with AIU metrics collection
- Verify successful VFIO access and inference completion

### 4. test_user_not_in_spyre_group
Tests VFIO device access when non-root user is NOT in the spyre group.

**Expected Result:** Container should fail to access VFIO devices.

**Test Flow:**
- Ensure user is not in spyre group
- Start container as user in fresh session
- Monitor for VFIO access failures
- Verify expected failure

## New Features

### AIU Metrics Collection

The test now includes automated collection of AIU performance metrics during inference workloads:

- **Method:** `run_inference_with_metrics()`
- **Metrics Collected:** AIU utilization, memory usage, throughput
- **Output Format:** CSV file with timestamped metrics
- **Location:** `{workdir}/metrics/{container_id}_aiu_metrics.csv`

### VLLM Inference Testing

Automated inference request testing validates the AI workload:

- **Test Prompts:** 5 diverse AI questions
- **Request Parameters:** 
  - Max tokens: 256
  - Temperature: 0.7
  - Model: Configured via VLLM_MODEL_PATH
- **Validation:** Response success and error checking

## Required Parameters

### Core Parameters
- `SPYRE_GROUP`: Group name for Spyre device access (e.g., "spyre")
- `AIU_PCIE_IDS`: PCIe IDs of AIU devices (e.g., "0233:70:00.0 0234:80:00.0")
- `AIU_WORLD_SIZE`: Number of AIU cards (e.g., "4")
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
- `ADDITIONAL_VLLM_ARGS`: Additional VLLM arguments (comma-separated)

### Test User Parameters (for user tests)
- `TEST_USERNAME`: Username for non-root tests (e.g., "testuser")
- `TEST_PASSWORD`: Password for test user

## Example YAML Configuration¸

```yaml
serviceability:
    vms:
        - serviceability:
            SPYRE_GROUP: "spyre"
            AIU_PCIE_IDS: "0233:70:00.0 0234:80:00.0 0333:70:00.0 0334:80:00.0"
            AIU_WORLD_SIZE: "4"
            HOST_MODELS_DIR: "/opt/ibm/spyre/models"
            VLLM_MODEL_PATH: "/models/granite-3.3-8b-instruct"
            MAX_MODEL_LEN: "32768"
            MAX_BATCH_SIZE: "32"
            MEMORY: "200G"
            SHM_SIZE: "2G"
            CONTAINER_URL: ""
            CONTAINER_TAG: ""
            API_KEY: "your-api-key-here"
            VLLM_SPYRE_USE_CB: "1"
            ENABLE_PREFIX_CACHING: "true"
            TEST_USERNAME: ""
            TEST_PASSWORD: ""
            DEVICE: "/dev/vfio"
            PRIVILEGED: "true"
            PIDS_LIMIT: "0"
            USERNS: "keep-id"
            GROUP_ADD: "keep-groups"
            PORT_MAPPING: "127.0.0.1::8000"
```

## Running the Tests

### Run all tests:
```bash
avocado run spyre_serviceability_test.py
```

### Run specific test:
```bash
avocado run spyre_serviceability_test.py:spyre_serviceability_test.test_root_in_spyre_group
```

### Run with custom parameters:
```bash
avocado run spyre_serviceability_test.py -p SPYRE_GROUP=spyre -p AIU_WORLD_SIZE=4
```

## Output and Logs

### Test Logs
- Standard Avocado test logs in `results/` directory
- Container logs captured and displayed in test output

### Metrics Files
- AIU metrics: `{workdir}/metrics/{container_id}_aiu_metrics.csv`
- Contains timestamped performance data during inference

### Log Analysis
The test automatically checks for:
- VFIO device access errors
- VLLM startup completion messages
- Inference request success/failure
- AIU metrics collection status

## Prerequisites

1. **Hardware:** IBM Power system with Spyre AI accelerators
2. **Software:**
   - Podman container runtime
   - ServiceReport tool
   - Access to container registry (with API key if private)
3. **Permissions:**
   - Root access or sudo privileges
   - Ability to modify user groups
4. **Models:**
   - AI models downloaded to HOST_MODELS_DIR
   - Models compatible with VLLM

## Troubleshooting

### Container fails to start
- Check VFIO device permissions: `ls -l /dev/vfio`
- Verify user is in correct group: `groups` or `id`
- Check SELinux status: `getenforce` (should be Permissive or Disabled)
- Verify container image is pulled: `podman images`

### VLLM startup timeout
- Increase timeout in test parameters
- Check container logs: `podman logs <container_id>`
- Verify model path is correct
- Check AIU device availability: `lspci | grep -i aiu`

### Inference requests fail
- Verify VLLM is listening on correct port
- Check network connectivity to container
- Review VLLM logs for errors
- Ensure model is loaded correctly

### Metrics collection fails
- Verify aiu-smi tool is available in container
- Check output directory permissions
- Review metrics process logs

## Dependencies

- **Avocado Framework:** Test execution framework
- **Podman:** Container runtime
- **ServiceReport:** Spyre device configuration tool
- **VLLM:** Large language model serving framework
- **AIU Performance Toolkit:** Metrics collection tools

## Notes

- Tests use fresh login sessions to ensure group membership changes take effect
- Container cleanup is automatic in tearDown()
- SELinux is temporarily set to Permissive mode if Enforcing
- Metrics collection runs in background during inference tests
- All tests validate both device access and functional AI workloads

## Support

For issues or questions:
- Check Avocado documentation: https://avocado-framework.github.io/
- Review Podman documentation: https://docs.podman.io/
- Contact: Abdul Haleem (abdhalee@linux.vnet.ibm.com)

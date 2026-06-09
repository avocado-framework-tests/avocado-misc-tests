# Spyre Senlib Tests

This test suite validates the IBM Senlib functionality on Spyre AIU devices by running unit tests inside a containerized VLLM environment with continuous inference running in the background.

## Overview

The test suite:
1. Creates a Podman container as root user
2. Copies the `ibm-senlib-tests-dd2` RPM into the container
3. Waits for the VLLM server to start up
4. Installs the RPM inside the container
5. Starts continuous inference in the background during tests
6. Executes senlib unit tests from `/opt/ibm/spyre/senlib/bin`
7. Validates that all tests either PASS or are SKIPPED

## Test Suites

The following test suites are available:

1. **test_doom_fixture** - Tests DoomFixture.* suite
2. **test_alloc_fixture** - Tests AllocFixture.* suite
3. **test_job_queue_fixture** - Tests JobQueueFixture.* suite
4. **test_lrg_pf1_vf1** - Tests LrgPF1VF1.* suite
5. **test_med_pf1_vf0** - Tests MedPF1VF0.* suite

## Prerequisites

- Power platform (ppc64le)
- Podman installed
- Root access
- Spyre AIU devices configured
- VLLM container image available
- IBM Senlib tests RPM file (ibm-senlib-tests-dd2)

## Required Parameters

### Core Parameters
- `SENLIB_RPM_PATH`: Path to the ibm-senlib-tests-dd2 RPM file (e.g., "/root/ibm-senlib-tests-dd2-1.2.1-1_0.el9.ppc64le.rpm")
- `SPYRE_GROUP`: Group name for Spyre device access (e.g., "spyre")
- `AIU_PCIE_IDS`: PCIe IDs of AIU devices (e.g., "0301:50:00.0")
- `AIU_WORD_SIZE`: Number of AIU cards (e.g., "1")
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
- `ADDITIONAL_VLLM_ARGS`: Additional VLLM arguments (space-separated, e.g., "--max-num-seqs 64 --gpu-memory-utilization 0.9")

### senlib RPM
- `SENLIB_RPM_PATH`: Path to senlib RPM

## Example YAML Configuration

```yaml
senlib:
    vms:
        - senlib:
            SPYRE_GROUP: "spyre"
            AIU_PCIE_IDS: "0301:50:00.0"
            AIU_WORD_SIZE: "1"
            HOST_MODELS_DIR: "/opt/ibm/spyre/models"
            VLLM_MODEL_PATH: "/models/granite-3.3-8b-instruct"
            MAX_MODEL_LEN: "32768"
            MAX_BATCH_SIZE: "32"
            MEMORY: "200G"
            SHM_SIZE: "2G"
            CONTAINER_URL: "container-url"
            CONTAINER_TAG: "container-tag"
            API_KEY: "your-api-key-here"
            VLLM_SPYRE_USE_CB: "1"
            ENABLE_PREFIX_CACHING: "true"
            DEVICE: "/dev/vfio"
            PRIVILEGED: "true"
            PIDS_LIMIT: "0"
            USERNS: "keep-id"
            GROUP_ADD: "keep-groups"
            PORT_MAPPING: "127.0.0.1::8000"
            ADDITIONAL_VLLM_ARGS: "--max-num-seqs 64"
            SENLIB_RPM_PATH: "/root/ibm-senlib-tests-dd2-1.2.1-1_0.el9.ppc64le.rpm"
```

## Usage

Run all tests:
```bash
avocado run --max-parallel-tasks=1 spyre_senlib_tests.py -m spyre_senlib_tests.py.data/spyre_senlib_tests.yaml
```

Run a specific test:
```bash
avocado run --max-parallel-tasks=1 spyre_senlib_tests.py:SenlibTests.test_doom_fixture -m spyre_senlib_tests.py.data/spyre_senlib_tests.yaml
```

## Test Flow

Each test follows this flow:

1. **Container Setup**
   - Create container with VLLM and Spyre configuration
   - Mount AIU devices and models directory
   - Start VLLM server with specified model

2. **VLLM Startup Wait**
   - Monitor container logs for "Application startup complete"
   - Timeout after 300 seconds if VLLM doesn't start

3. **RPM Installation**
   - Copy RPM from host to container `/tmp` directory using `podman cp`
   - Install RPM as root using `podman exec -u 0 {container_id} rpm -ivh`
   - Verify installation with `rpm -ql` to list installed files

4. **Continuous Inference**
   - Start background Python process sending inference requests
   - Uses rotating prompts to keep AIU devices active
   - Runs continuously during all senlib tests

5. **Senlib Tests**
   - Execute tests from `/opt/ibm/spyre/senlib/bin` directory
   - Run `./senlib_unit_test --gtest_filter="<TestSuite>.*"`
   - Parse output for PASSED/SKIPPED/FAILED status

6. **Validation**
   - Test passes if all tests are PASSED or SKIPPED
   - Test fails if any test shows FAILED status

7. **Cleanup**
   - Stop continuous inference process
   - Stop and remove container
   - Collect final logs for debugging

## Expected Output

Successful test output:
```
[  PASSED  ] 10 tests.
[  SKIPPED ] 2 tests.
```

Failed test output (causes test failure):
```
[  PASSED  ] 8 tests.
[  FAILED  ] 2 tests.
```

## Troubleshooting

### Container fails to start
- Check VFIO device permissions: `ls -l /dev/vfio`
- Verify spyre group membership: `groups`
- Check container logs: `podman logs <container_id>`
- Verify AIU_PCIE_IDS are correct: `lspci | grep AIU`

### VLLM startup timeout
- Check if model path is correct
- Verify sufficient memory allocated
- Check AIU devices are accessible
- Review container logs for errors

### RPM installation fails
- Verify SENLIB_RPM_PATH is correct and file exists
- Check RPM is compatible with container OS (el9)
- Ensure container has root access
- Check for "Permission denied" errors in logs

### Senlib tests not found
- Verify RPM installed successfully
- Check RPM contents: `podman exec -u 0 {container_id} rpm -ql ibm-senlib-tests-dd2`
- Binary should be at `/opt/ibm/spyre/senlib/bin/senlib_unit_test`

### Inference fails
- Check VLLM server is running: `podman logs {container_id}`
- Verify port mapping is correct
- Check model is loaded properly
- Ensure python3-requests is installed on host

### Tests fail unexpectedly
- Review test output for specific failure messages
- Check if AIU devices are functioning properly
- Verify continuous inference is running
- Check container resource limits (memory, CPU)

## Notes

- Tests run as root user (UID 0) inside the container for RPM installation and test execution
- Each test suite creates a fresh container to ensure isolation
- Continuous inference uses simple prompts with 5-second intervals
- Test timeout is 300 seconds for VLLM startup
- All tests are independent and can run in any order
- The container is automatically cleaned up after each test
- SELinux is temporarily set to Permissive mode if it's Enforcing
- Required packages (make, gcc, podman, python3-requests) are automatically installed
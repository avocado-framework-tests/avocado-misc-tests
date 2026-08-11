# Spyre Senlib Tests

This test suite validates the IBM Senlib functionality on Spyre AIU devices by running unit tests inside a containerized VLLM environment with inference running in the background.

## Overview

The test suite:
1. Creates a Podman container as root user with Spyre AIU device access
2. Waits for the VLLM server to start up
3. Copies the `ibm-senlib-tests-dd2` RPM into the container
4. Installs the RPM inside the container as root
5. Starts inference in the background during tests
6. Executes senlib unit tests from `/opt/ibm/spyre/senlib/bin`
7. Validates that all tests either PASS or are SKIPPED (no FAILED tests allowed)

**Note:** The container is created once in setUp() and reused for all 5 test suites to improve efficiency.

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
- ServiceReport configured (spyre-host-config test should be run first)

## Required Parameters

### Core Parameters
- `SENLIB_RPM_PATH`: Path to the ibm-senlib-tests-dd2 RPM file
- `SPYRE_GROUP`: Group name for Spyre device access
- `AIU_PCIE_IDS`: PCIe IDs of AIU devices (e.g., "0301:50:00.0")
- `AIU_WORLD_SIZE`: Number of AIU cards (default: "1")
- `HOST_MODELS_DIR`: Host directory containing models (default: "/opt/ibm/spyre/models/src")
- `VLLM_MODEL_PATH`: Path to model inside container (default: "/models/granite-3.3-8b-instruct")

### Model Configuration
- `MAX_MODEL_LEN`: Maximum model context length (default: "3072")
- `MAX_BATCH_SIZE`: Maximum batch size (default: "16")
- `MEMORY`: Container memory limit (default: "200G")

### Container Configuration
- `CONTAINER_URL`: Container registry URL
- `CONTAINER_TAG`: Container image tag
- `API_KEY`: Container registry API key (optional)
- `DEVICE`: Device to mount (default: "/dev/vfio")
- `USERNS`: User namespace (default: "keep-id")
- `GROUP_ADD`: Additional groups (default: "keep-groups")
- `PIDS_LIMIT`: Process limit (default: "0")
- `PORT_MAPPING`: Port mapping (default: "127.0.0.1::8000")

## Usage

Run all tests:
```bash
avocado run --max-parallel-tasks=1 spyre_Senlib_test.py -m spyre_Senlib_test.py.data/spyre_Senlib_test.yaml
```

Run a specific test:
```bash
avocado run --max-parallel-tasks=1 spyre_Senlib_test.py:SenlibTests.test_doom_fixture -m spyre_Senlib_test.py.data/spyre_Senlib_test.yaml
```
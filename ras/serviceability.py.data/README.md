# Serviceability Test Suite for VFIO Spyre Device Access

## Overview

The `serviceability.py` test suite validates VFIO (Virtual Function I/O) Spyre device access control through group membership management. It ensures that only users with proper group membership can access VFIO devices within containerized environments running VLLM (vLLM - Large Language Model inference engine).

## ⚠️ Important Requirements

**This test MUST be run as the root user.**

The test performs system-level operations including:
- User and group management (`usermod`, `gpasswd`)
- VFIO device configuration
- SELinux policy modifications
- Container operations with privileged access
- System service configuration

## Test Scenarios

The test suite includes four test cases:

### 1. `test_root_in_spyre_group`
**Purpose:** Verify VFIO device access when root user IS in the spyre group  
**Expected Result:** Container successfully accesses VFIO devices and VLLM starts  
**Validates:** Proper group membership grants device access

### 2. `test_root_not_in_spyre_group`
**Purpose:** Verify VFIO device access when root user is NOT in the spyre group  
**Expected Result:** Container fails to access VFIO devices  
**Validates:** Lack of group membership denies device access

### 3. `test_user_in_spyre_group`
**Purpose:** Verify VFIO device access when non-root user IS in the spyre group  
**Expected Result:** Container successfully accesses VFIO devices and VLLM starts  
**Validates:** Non-root users with proper group membership can access devices

### 4. `test_user_not_in_spyre_group`
**Purpose:** Verify VFIO device access when non-root user is NOT in the spyre group  
**Expected Result:** Container fails to access VFIO devices  
**Validates:** Non-root users without group membership cannot access devices

## Configuration Parameters

All test parameters are configured in `serviceability.yaml`. Below is a detailed explanation of each parameter:

### Core Device and Group Parameters

| Parameter | Description | Example Value |
|-----------|-------------|---------------|
| `SPYRE_GROUP` | Group name for VFIO device access control | `spyre_group` |
| `AIU_PCIE_IDS` | Space-separated list of AIU PCIe device IDs | `0233:70:00.0 0234:80:00.0` |
| `AIU_WORLD_SIZE` | Number of AIU devices to use | `4` |

### Model and Path Configuration

| Parameter | Description | Example Value |
|-----------|-------------|---------------|
| `HOST_MODELS_DIR` | Host directory containing AI models (mounted into container) | `/path/to/model` |
| `VLLM_MODEL_PATH` | Path to VLLM model inside container | `/models` |
| `CACHE_DIR` | Cache directory for model artifacts | `/path/to/cache/` |

### VLLM Configuration

| Parameter | Description | Example Value |
|-----------|-------------|---------------|
| `MAX_MODEL_LEN` | Maximum sequence length for the model | `32768` |
| `MAX_BATCH_SIZE` | Maximum batch size for inference | `32` |
| `VLLM_SPYRE_USE_CB` | Enable control blocks (1=enabled, 0=disabled) | `1` |
| `VLLM_DT_CHUNK_LEN` | Chunk length for data transfer (optional) | `512` |
| `VLLM_SPYRE_USE_CHUNKED_PREFILL` | Enable chunked prefill (optional) | `1` |
| `ENABLE_PREFIX_CACHING` | Enable VLLM prefix caching | `true` |
| `ADDITIONAL_VLLM_ARGS` | Comma-separated additional VLLM arguments | `--arg1,--arg2` |
| `PRECOMPILED_DECODERS` | Use precompiled decoders | `1` |
| `SENLIB_CONFIG_FILE` | Senlib configuration file name | `senlib.json` |

### Container Configuration

| Parameter | Description | Example Value |
|-----------|-------------|---------------|
| `CONTAINER_URL` | Container registry URL | `container-url-here` |
| `CONTAINER_TAG` | Container image tag/version | `v1.0.0` |
| `API_KEY` | API key for container registry authentication | `your-api-key-here` |
| `MEMORY` | Container memory limit | `100G` |
| `SHM_SIZE` | Shared memory size for container | `2G` |

### Container Runtime Parameters

| Parameter | Description | Example Value |
|-----------|-------------|---------------|
| `DEVICE` | Device to mount in container | `/dev/vfio` |
| `PRIVILEGED` | Run container in privileged mode (required for VFIO) | `true` |
| `PIDS_LIMIT` | Process ID limit (0 = unlimited) | `0` |
| `USERNS` | User namespace mode | `keep-id` |
| `GROUP_ADD` | Add user groups to container | `keep-groups` |
| `PORT_MAPPING` | Port mapping format: `[host_ip]:[host_port]:container_port` | `127.0.0.1::8000` |

### Test User Configuration

| Parameter | Description | Example Value |
|-----------|-------------|---------------|
| `TEST_USERNAME` | Username for non-root test cases | `user` |
| `TEST_PASSWORD` | Password for test user | `secure-password` |

### Timeout Configuration

| Parameter | Description | Example Value |
|-----------|-------------|---------------|
| `VLLM_STARTUP_TIMEOUT` | Maximum time to wait for VLLM startup (seconds) | `300` |
| `LOG_CHECK_INTERVAL` | Interval between log checks (seconds) | `10` |

## Example Configuration

Here's a complete example configuration in `serviceability.yaml`:

```yaml
SPYRE_GROUP: "spyre_group"
AIU_PCIE_IDS: "0233:70:00.0 0234:80:00.0"
HOST_MODELS_DIR: "/path/to/models/"
VLLM_MODEL_PATH: "/models"
AIU_WORLD_SIZE: "4"
MAX_MODEL_LEN: "32768"
MAX_BATCH_SIZE: "32"
MEMORY: "100G"
SHM_SIZE: "2G"

CONTAINER_URL: "container_url"
CONTAINER_TAG: "v1.0.0"
API_KEY: "your-api-key-here"

VLLM_SPYRE_USE_CB: "1"
PRECOMPILED_DECODERS: "1"
CACHE_DIR: "/path/to/cache"
SENLIB_CONFIG_FILE: "senlib.json"

DEVICE: "/dev/vfio"
PRIVILEGED: "true"
PIDS_LIMIT: "0"
USERNS: "keep-id"
GROUP_ADD: "keep-groups"
PORT_MAPPING: "127.0.0.1::8000"

ENABLE_PREFIX_CACHING: "true"
ADDITIONAL_VLLM_ARGS: ""

TEST_USERNAME: "user"
TEST_PASSWORD: "test-password"
```

## Prerequisites

### System Requirements
- **Operating System:** Power (ppc64le) architecture running Linux
- **Platform:** PowerVM (not PowerNV/bare-metal)
- **User:** Root access required, root login for LPAR
- **Packages:** `make`, `gcc`, `podman`

### Hardware Requirements
- VFIO Spyre devices configured and available at `/dev/vfio`
- Sufficient memory for model loading (typically 100GB+)

### Software Requirements
- ServiceReport tool (automatically downloaded from GitHub)
- Podman container runtime
- Access to container registry (if using private images)

## Running the Tests

### Run All Tests
```bash
sudo avocado run serviceability.py -m serviceability.py.data/serviceability.yaml --max-parallel-tasks=1
```

### Run Specific Test 
```bash
sudo avocado run serviceability.py:serviceability.test_root_in_spyre_group -m serviceability.py.data/serviceability.yaml --max-parallel-tasks=1
```

### Run with Custom Parameters
```bash
sudo avocado run serviceability.py \
  --mux-yaml serviceability.py.data/serviceability.yaml \
  -p SPYRE_GROUP=spyre_group \
  -p CONTAINER_URL=icr.io/spyre/vllm-spyre \
  -p CONTAINER_TAG=v1.0.0
```

### Run with Verbose Logging
```bash
sudo avocado run serviceability.py --show-job-log
```

## Test Flow

Each test follows this general flow:

1. **Setup Phase**
   - Check platform compatibility (Power, PowerVM)
   - Disable SELinux if enforcing
   - Install required packages
   - Download ServiceReport tool
   - Initialize Podman
   - Login to container registry (if API key provided)
   - Pull container images

2. **Test Execution**
   - Configure Spyre devices using ServiceReport
   - Manage user/group membership
   - Verify group membership in fresh login sessions
   - Start container with VFIO device access
   - Monitor container logs for VLLM startup
   - Validate VFIO device access success/failure

3. **Teardown Phase**
   - Retrieve final container logs
   - Stop and remove containers
   - Clean up test artifacts

## Key Technical Details

### Fresh Login Sessions
The tests use `su - {user} -c 'command'` to create fresh login sessions. This is critical because:
- Group membership changes via `usermod`/`gpasswd` only affect new login sessions
- The kernel caches group information for existing sessions
- Fresh sessions read updated `/etc/group` file

### Container User Namespaces
- Each user has a separate podman container namespace
- Root cannot access containers created by non-root users via Podman API
- Tests track `container_user` to clean up containers in the correct user context

### VFIO Device Access
- VFIO devices require specific group membership
- Device files at `/dev/vfio/*` must have correct group ownership
- Containers need `--privileged` mode and `--device /dev/vfio` mount

## Troubleshooting

### Test Cancellation: "supported only on Power platform"
**Cause:** Running on non-Power architecture  
**Solution:** Run on ppc64le system

### Test Cancellation: "servicelog: is not supported on the PowerNV platform"
**Cause:** Running on bare-metal Power (PowerNV)  
**Solution:** Run on PowerVM (LPAR)

### Container Fails to Start
**Possible Causes:**
- Missing VFIO devices: Check `/dev/vfio` exists
- Incorrect group membership: Verify user is in spyre group
- SELinux blocking: Check SELinux status
- Container image not available: Verify registry access

### VFIO Device Access Denied
**Possible Causes:**
- User not in correct group
- VFIO device permissions incorrect
- Group membership not refreshed (need fresh login session)

### Container Registry Authentication Failure
**Solution:** Verify `API_KEY` parameter is correct and has registry access

## Log Files

Test logs are written to:
- **Avocado job log:** `~/avocado/job-results/job-<timestamp>/job.log`
- **Per-rank logs:** `LOG.R0.txt`, `LOG.R1.txt`, etc. (for multi-rank tests)
- **Container logs:** Retrieved via `podman logs` and included in test output

## Support

For issues or questions:
1. Check Avocado test logs for detailed error messages
2. Verify all prerequisites are met
3. Ensure running as root user
4. Check VFIO device availability and permissions
5. Verify container registry access

## License

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later version.

## Authors

- Abdul Haleem (abdhalee@linux.ibm.com)

## Copyright

Copyright: 2026 IBM
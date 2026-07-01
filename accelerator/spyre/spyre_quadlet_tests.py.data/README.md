# Spyre Quadlet Tests

This test suite validates Spyre AI accelerator deployments using Podman Quadlet for systemd-managed containers. It tests four different use cases to ensure proper VFIO device access, container deployment, and VLLM (Very Large Language Model) startup using systemd user services.

## Quadlet Overview

**Podman Quadlet** is a feature that allows you to define containers using systemd unit files. Instead of running `podman run` commands directly, you create `.container` files that systemd can manage. This provides:
- Automatic container startup on boot
- Service management via systemctl
- Better integration with systemd logging (journalctl)
- Declarative configuration
- Service dependencies and ordering

## Overview

The test suite includes four test cases, each validating a different AI workload use case:

### Test 1: Entity Extraction (`test_entity_extraction`)
Tests entity extraction use case with a single AIU device.

### Test 2: RAG - Retrieval-Augmented Generation (`test_rag`)
Tests RAG use case with multiple AIU devices for larger context windows.

### Test 3: Embedding (`test_embedding`)
Tests embedding generation use case with a specialized embedding model.

### Test 4: Reranker (`test_reranker`)
Tests reranking use case with a reranker model.

## Test Purpose

This test suite validates:
- **Quadlet Integration**: Ensures Podman Quadlet files are correctly generated and loaded by systemd
- **Systemd User Services**: Verifies non-root users can manage containers via systemd
- **VFIO Device Access**: Confirms proper VFIO device permissions and group membership
- **VLLM Startup**: Validates VLLM inference framework starts successfully in containers
- **Container Lifecycle**: Tests container creation, monitoring, and cleanup via systemd

## Prerequisites

- Power platform (ppc64le)
- Podman installed with Quadlet support
- Systemd (for user services)
- Root access or sudo privileges
- Spyre AIU devices configured
- VLLM container image available
- AI models downloaded to HOST_MODELS_DIR

## Required Parameters

### Core Parameters
- `SPYRE_GROUP`: Group name for VFIO device access (e.g., "sentient")
- `TEST_USERNAME`: Username for non-root container execution
- `TEST_PASSWORD`: Password for test user
- `ROOT_PASSWORD`: Root password
- `HOST_MODELS_DIR`: Host directory containing AI models (e.g., "/opt/ibm/spyre/models")

### Timeout Parameters
- `VLLM_STARTUP_TIMEOUT`: Maximum time to wait for VLLM startup in seconds (default: "300")
- `LOG_CHECK_INTERVAL`: Log check interval in seconds (e.g., "5")

### Use Case Specific Parameters

Each use case has its own set of parameters with the format `<USECASE>_<PARAMETER>`:

#### Entity Extraction Parameters
- `ENTITY_EXTRACT_AIU_IDS`: AIU PCIe device IDs (e.g., "0301:50:00.0")
- `ENTITY_EXTRACT_MODEL`: Model path (e.g., "/models/granite-3.3-8b-instruct")
- `ENTITY_EXTRACT_WORLD_SIZE`: Tensor parallel size (e.g., "1")
- `ENTITY_EXTRACT_MAX_MODEL_LEN`: Maximum model length (e.g., "3072")
- `ENTITY_EXTRACT_MAX_BATCH_SIZE`: Maximum batch size (e.g., "16")
- `ENTITY_EXTRACT_MEMORY`: Container memory limit (e.g., "200G")

#### RAG Parameters
- `RAG_AIU_IDS`: AIU PCIe device IDs (e.g., "0301:50:00.0 0302:60:00.0 0303:70:00.0 0304:80:00.0")
- `RAG_MODEL`: Model path (e.g., "/models/granite-3.3-8b-instruct")
- `RAG_WORLD_SIZE`: Tensor parallel size (e.g., "4")
- `RAG_MAX_MODEL_LEN`: Maximum model length (e.g., "32768")
- `RAG_MAX_BATCH_SIZE`: Maximum batch size (e.g., "32")
- `RAG_MEMORY`: Container memory limit (e.g., "200G")
- `RAG_SHM_SIZE`: Shared memory size (e.g., "2G")

#### Embedding Parameters
- `EMBEDDING_AIU_IDS`: AIU PCIe device IDs (e.g., "0301:50:00.0")
- `EMBEDDING_MODEL`: Model path (e.g., "/models/granite-embedding-125m-english")
- `EMBEDDING_WORLD_SIZE`: Tensor parallel size (e.g., "1")
- `EMBEDDING_MAX_MODEL_LEN`: Maximum model length (e.g., "512")
- `EMBEDDING_MAX_BATCH_SIZE`: Maximum batch size (e.g., "4")
- `EMBEDDING_MEMORY`: Container memory limit (e.g., "1500G")

#### Reranker Parameters
- `RERANKER_AIU_IDS`: AIU PCIe device IDs (e.g., "0301:50:00.0")
- `RERANKER_MODEL`: Model path (e.g., "/models/bge-reranker-v2-m3")
- `RERANKER_WORLD_SIZE`: Tensor parallel size (e.g., "1")
- `RERANKER_MAX_MODEL_LEN`: Maximum model length (e.g., "1024")
- `RERANKER_MAX_BATCH_SIZE`: Maximum batch size (e.g., "4")
- `RERANKER_MEMORY`: Container memory limit (e.g., "400G")

### Container Configuration
- `CONTAINER_IMAGE`: Container image URL with tag
- `CONTAINER_URL`: Container registry URL
- `CONTAINER_TAG`: Container image tag
- `API_KEY`: API key for container registry (optional)
- `DEVICE`: Device to mount in container (default: "/dev/vfio")
- `PRIVILEGED`: Run in privileged mode for VFIO access (default: "true")
- `PIDS_LIMIT`: PIDs limit (0 = unlimited, default: "0")
- `USERNS`: User namespace mode (default: "keep-id")
- `GROUP_ADD`: Add user groups to container (default: "keep-groups")
- `PORT_MAPPING`: Port mapping format (default: "127.0.0.1::8000")

### VLLM-Specific Options
- `VLLM_SPYRE_USE_CB`: Use control blocks
- `VLLM_DT_CHUNK_LEN`: Chunk length for data transfer
- `VLLM_SPYRE_USE_CHUNKED_PREFILL`: Use chunked prefill
- `ENABLE_PREFIX_CACHING`: Enable VLLM prefix caching (true/false)
- `ADDITIONAL_VLLM_ARGS`: Additional VLLM arguments (e.g., "--max-num-batched-tokens 512")

## Example YAML Configuration

See `spyre_quadlet_tests_sample.yaml` for a complete example with values:

```yaml
HOST_MODELS_DIR: "/opt/ibm/spyre/models"
VLLM_STARTUP_TIMEOUT: "300"
ENTITY_EXTRACT_AIU_IDS: "0301:50:00.0"
ENTITY_EXTRACT_MODEL: "/models/granite-3.3-8b-instruct"
ENTITY_EXTRACT_WORLD_SIZE: "1"
ENTITY_EXTRACT_MAX_MODEL_LEN: "3072"
ENTITY_EXTRACT_MAX_BATCH_SIZE: "16"
ENTITY_EXTRACT_MEMORY: "200G"
DEVICE: "/dev/vfio"
PRIVILEGED: "true"
PIDS_LIMIT: "0"
USERNS: "keep-id"
GROUP_ADD: "keep-groups"
```

## Usage

Run all quadlet tests:
```bash
avocado run --max-parallel-tasks=1 spyre_quadlet_tests.py -m spyre_quadlet_tests.py.data/spyre_quadlet_tests.yaml
```

Run specific test:
```bash
avocado run spyre_quadlet_tests.py:SpyreQuadletTests.test_entity_extraction -m spyre_quadlet_tests.py.data/spyre_quadlet_tests.yaml
avocado run spyre_quadlet_tests.py:SpyreQuadletTests.test_rag -m spyre_quadlet_tests.py.data/spyre_quadlet_tests.yaml
avocado run spyre_quadlet_tests.py:SpyreQuadletTests.test_embedding -m spyre_quadlet_tests.py.data/spyre_quadlet_tests.yaml
avocado run spyre_quadlet_tests.py:SpyreQuadletTests.test_reranker -m spyre_quadlet_tests.py.data/spyre_quadlet_tests.yaml
```

## Test Flow

Each test follows this detailed flow:

### 1. Setup Phase (Root User)
- Install required packages (podman, systemd)
- Download and extract ServiceReport
- Load all parameters from YAML configuration
- Create test user if doesn't exist
- Add test user to spyre group
- Enable lingering for test user (allows user services to run without login)
- Setup runtime directory (`/run/user/<uid>`)
- Ensure models directory exists

### 2. Check ServiceReport and VFIO Devices
- Run `servicereport -r -p spyre` to configure Spyre devices
- Run `servicereport -v -p spyre` to validate configuration
- Verify VFIO devices exist in `/dev/vfio`
- Check device group ownership matches spyre_group
- Fail test if VFIO devices not properly configured

### 3. Create Quadlet File (Non-Root User)
- Create directory: `~/.config/containers/systemd/`
- Generate quadlet `.container` file with use case configuration
- Set proper file ownership for test user

### 4. Reload Systemd Daemon
- Run `systemctl --user daemon-reload` as test user
- This loads the new quadlet file into systemd

### 5. Start the Service
- Run `systemctl --user start spyre-<usecase>.service` as test user
- Verify service starts without errors
- If service fails to start, capture journalctl logs and fail test

### 6. Check Container Creation
- Wait 5 seconds for container to initialize
- Run `podman ps` to verify container is created and running
- If container not running, capture service logs and fail test
- Log container name and status

### 7. Monitor for VLLM Startup
- Check container status every 20 seconds
- First verify container is still running with `podman ps`
- Then check `podman logs <container-name>` for "Application startup complete"
- Monitor for VFIO-related errors in logs
- Continue until timeout (default: 300 seconds) or success
- Display recent log lines (20 lines) during each check
- If container exits, logs won't be available (that's why we check podman ps first)

### 8. Collect Logs for Debugging
- Capture container logs: `podman logs <container-name>`
- Capture service logs: `journalctl --user -xeu spyre-<usecase>.service`
- Display all logs in test output for user debugging
- Logs include systemd service status, container output, and any errors

### 9. Stop the Service
- Run `systemctl --user stop spyre-<usecase>.service`
- Remove container: `podman rm -f <container-name>`
- Clean up resources

### 10. Cleanup (tearDown)
- Get final service logs for debugging
- Stop systemd service
- Remove container if it exists
- Log cleanup completion

## Quadlet File Format

Each test creates a Podman Quadlet `.container` file with this structure:

```ini
[Unit]
Description=Spyre Entity Extraction
After=network-online.target

[Container]
ContainerName=spyre-entity-extract
PublishPort=127.0.0.1::8000
Image=container-image

Environment=AIU_PCIE_IDS="0301:50:00.0"

PodmanArgs=--device=/dev/vfio
PodmanArgs=--userns=keep-id
PodmanArgs=--group-add=keep-groups
PodmanArgs=--pids-limit=0
PodmanArgs=--memory=200G
PodmanArgs=--privileged=true

Volume=/opt/ibm/spyre/models:/models

Exec=--model /models/granite-3.3-8b-instruct -tp 1 --max-model-len 3072 --max-num-seqs 16

[Service]
Slice=spyre-entity-extract.slice
Restart=no

[Install]
WantedBy=default.target
```

## Pass/Fail Criteria

### Test PASSES if:
- ServiceReport configures Spyre devices successfully
- VFIO devices exist with correct group ownership
- Test user is added to spyre group successfully
- Quadlet file is created in correct location
- Systemd daemon reloads successfully
- Service starts without errors
- Container is created and running (verified with `podman ps`)
- VLLM server starts within timeout period
- "Application startup complete" message appears in logs
- No VFIO access errors in logs

### Test FAILS if:
- VFIO devices not found or not properly configured
- Failed to add user to spyre group
- Failed to create quadlet file
- Systemd daemon-reload fails
- Service fails to start
- Container is not created (not in `podman ps` output)
- Container exits before VLLM starts
- VLLM fails to start within timeout (300 seconds)
- VFIO device access errors detected in logs
- "Application startup complete" message not found

## Troubleshooting

### Container fails to start
- **Check VFIO device permissions**: `ls -l /dev/vfio`
  - Devices should be owned by root:spyre_group
  - Permissions should allow group access
- **Verify user is in correct group**: `groups <username>`
  - User should be member of spyre_group
  - May need to logout/login for group changes to take effect
- **Check quadlet file syntax**: `cat ~/.config/containers/systemd/spyre-*.container`
  - Verify all required fields are present
  - Check for syntax errors
- **Review service status**: `systemctl --user status spyre-<usecase>.service`
  - Shows service state and recent log entries
- **Check service logs**: `journalctl --user -xeu spyre-<usecase>.service`
  - Shows detailed service logs with explanations

### VLLM startup timeout
- **Increase timeout**: Set `VLLM_STARTUP_TIMEOUT` to higher value (e.g., "600")
- **Check container logs**: `podman logs spyre-<usecase>`
  - Look for error messages
  - Check if model is loading
- **Verify model path**: Ensure model exists at specified path
  - Check HOST_MODELS_DIR exists and contains models
  - Verify model path in container matches VLLM_MODEL_PATH
- **Check AIU device availability**: `lspci | grep -i aiu`
  - Verify AIU devices are detected
  - Check device IDs match AIU_PCIE_IDS
- **Ensure sufficient memory**: Check memory limits are adequate
  - Entity Extraction: 200G minimum
  - RAG: 200G minimum
  - Embedding: 1500G minimum
  - Reranker: 400G minimum

### Quadlet file not loaded
- **Verify file location**: `ls -la ~/.config/containers/systemd/`
  - File should be in user's home directory
  - File should have .container extension
- **Check file permissions**: File should be readable by user
- **Run daemon-reload**: `systemctl --user daemon-reload`
  - Must be run after creating/modifying quadlet files
- **Check for syntax errors**: Review quadlet file for typos
  - Each PodmanArgs must be on separate line
  - Environment variables must be quoted
  - Paths must be absolute

### Service fails to start
- **Check systemd service logs**: `journalctl --user -xeu spyre-<usecase>.service`
  - Shows why service failed to start
  - Look for permission errors, missing files, etc.
- **Verify container image**: `podman images`
  - Check if image is pulled
  - Verify image name matches CONTAINER_IMAGE
- **Check for port conflicts**: Ensure port 8000 is not already in use
- **Ensure runtime directory exists**: `/run/user/<uid>` should exist
  - Created automatically during setup
  - Check with: `ls -la /run/user/`

### Container exits immediately
- **Review container logs**: `podman logs spyre-<usecase>`
  - Check for startup errors
  - Look for missing dependencies
- **Check VFIO device access**: Look for permission denied errors
  - Verify user is in spyre group
  - Check device permissions
- **Verify model files exist**: Check HOST_MODELS_DIR
  - Models should be present and readable
  - Check file permissions
- **Check memory limits**: Ensure sufficient memory allocated
  - Container may exit if memory limit too low

### Logs don't show up
- **Container must be running**: `podman ps` to check
  - If container exited, logs may not be available
  - Check service logs instead: `journalctl --user -xeu <service>`
- **Use correct user context**: Run podman commands as test user
  - Use: `su - <username> -c 'podman logs <container>'`
  - Or set XDG_RUNTIME_DIR: `XDG_RUNTIME_DIR=/run/user/$(id -u) podman logs <container>`

### Lingering issues
- **Enable lingering**: `loginctl enable-linger <username>`
  - Allows user services to run without active login session
  - Required for systemd user services
- **Check lingering status**: `loginctl show-user <username> | grep Linger`
  - Should show: `Linger=yes`
- **Restart user services**: After enabling lingering
  - Logout and login, or restart systemd user instance

## Notes

### General
- Tests run as non-root user with systemd user services
- Quadlet files are automatically generated for each test
- Container cleanup is automatic in tearDown()
- Each test is independent and can be run separately
- Lingering must be enabled for test user
- All tests validate both container startup and VLLM initialization

### Quadlet vs Direct Podman

This test suite uses Podman Quadlet instead of direct `podman run` commands:

**Advantages:**
- **Systemd Integration**: Full integration with systemd service management
- **Automatic Restart**: Can configure automatic restart policies
- **Better Logging**: Logs available through both podman and journalctl
- **Declarative Configuration**: Configuration in files, not command lines
- **Service Dependencies**: Can specify startup order and dependencies
- **Resource Management**: Better control via systemd slices and cgroups

**Differences from direct podman:**
- Requires systemd user services
- Uses `.container` files instead of command-line arguments
- Managed via `systemctl --user` commands
- Logs available through both `podman logs` and `journalctl`
- Requires daemon-reload after file changes
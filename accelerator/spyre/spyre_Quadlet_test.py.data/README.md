# Spyre Quadlet Tests

This test suite validates Spyre AI accelerator deployments using Podman Quadlet for systemd-managed containers. It tests four different use cases to ensure proper VFIO device access, container deployment, and VLLM(Very Large Language Model) startup using systemd user services.

# Quadlet Overview

**Podman Quadlet ** is a feature that allows you to define containers using systemd unit files. Instead of running `podman run` commands directly, you create `.container` files that systemd can manage. This provides:
- Automatic container startup on boot
- Service management via systemctl
- Better integration with systemd logging(journalctl)
- Declarative configuration
- Service dependencies and ordering

# Overview

The test suite includes four test cases, each validating a different AI workload use case:

1. ** Entity Extraction ** - Tests entity extraction with a single AIU device
2. ** RAG(Retrieval-Augmented Generation) ** - Tests RAG with multiple AIU devices for larger context windows
3. ** Embedding ** - Tests embedding generation with a specialized embedding model
4. ** Reranker ** - Tests reranking with a reranker model

# Test Purpose

This test suite validates:
- **Quadlet Integration**: Ensures Podman Quadlet files are correctly generated and loaded by systemd
- **Systemd User Services**: Verifies non-root users can manage containers via systemd
- **VFIO Device Access**: Confirms proper VFIO device permissions and group membership
- **VLLM Startup**: Validates VLLM inference framework starts successfully in containers
- **Container Lifecycle**: Tests container creation, monitoring, and cleanup via systemd

# Prerequisites

- Power platform(ppc64le)
- Podman installed with Quadlet support
- Systemd(for user services)
- Root access or sudo privileges
- Spyre AIU devices configured
- VLLM container image available
- AI models downloaded to HOST_MODELS_DIR

# Required Parameters

# Core Parameters
- `USE_CASE`: Use case name("entity-extract", "rag", "embedding", or "reranker")
- `RHAIIS_VERSION`: RHAIIS version(e.g., "3.4" or "3.5")
- `SPYRE_GROUP`: Group name for VFIO device access
- `USER`: Username for non-root container execution
- `HOST_MODELS_DIR`: Host directory containing AI models(default: "/opt/ibm/spyre/models/src")

# Environment Variables
- `AIU_PCIE_IDS`: AIU PCIe device IDs(e.g., "0301:50:00.0" or "0301:50:00.0 0302:60:00.0 0303:70:00.0 0304:80:00.0")
- `VLLM_MODEL_PATH`: Model path inside container
- `AIU_WORLD_SIZE`: Tensor parallel size
- `MAX_MODEL_LEN`: Maximum model length
- `MAX_BATCH_SIZE`: Maximum batch size

# Container Configuration
- `CONTAINER_URL`: Container registry URL
- `CONTAINER_TAG`: Container image tag
- `API_KEY`: API key for container registry authentication
- `DEVICE`: Device to mount in container(default: "/dev/vfio")
- `USERNS`: User namespace mode(default: "keep-id")
- `GROUP_ADD`: Add user groups to container(default: "keep-groups")
- `PIDS_LIMIT`: PIDs limit(0=unlimited, default: "0")
- `MEMORY`: Container memory limit(e.g., "100G", "50G", "400G")
- `SHM_SIZE`: Shared memory size(optional, e.g., "2G" for RAG)
- `PORT_MAPPING`: Port mapping format(default: "127.0.0.1:8000:8000")

# Usage

Run a specific use case test:
```bash
avocado run spyre_Quadlet_test.py - m spyre_Quadlet_test.py.data/spyre_Quadlet_EE_test.yaml
avocado run spyre_Quadlet_test.py - m spyre_Quadlet_test.py.data/spyre_Quadlet_RAG_test.yaml
avocado run spyre_Quadlet_test.py - m spyre_Quadlet_test.py.data/spyre_Quadlet_Embedding_test.yaml
avocado run spyre_Quadlet_test.py - m spyre_Quadlet_test.py.data/spyre_Quadlet_Reranker_test.yaml
```

# Test Flow

Each test follows this detailed flow:

# 1. Setup Phase
- Verify platform is Power(ppc64le)
- Load all parameters from YAML configuration
- Run servicereport commands to verify Spyre configuration
- Verify test user exists
- Verify user is in spyre group
- Authenticate with container registry(if API_KEY is provided)
- Verify models directory exists
- Construct container image from CONTAINER_URL and CONTAINER_TAG

# 2. Check VFIO Devices
- Verify VFIO devices exist in `/dev/vfio`
- Check device group ownership matches spyre_group
- Fail test if VFIO devices not properly configured

# 3. Create Quadlet File (Non-Root User)
- Create directory: `~/.config/containers/systemd/`
- Generate quadlet `.container` file with use case configuration
- Set proper file ownership for test user

# 4. Reload Systemd Daemon
- Run `systemctl - -user daemon-reload` as test user
- This loads the new quadlet file into systemd

# 5. Start the Service
- Run `systemctl - -user start spyre-<usecase > .service` as test user
- Verify service starts without errors
- If service fails to start, capture journalctl logs and fail test

# 6. Check Container Creation
- Wait 5 seconds for container to initialize
- Run `podman ps` to verify container is created and running
- If container not running, capture service logs and fail test

# 7. Monitor for VLLM Startup
- Check container status every 20 seconds
- First verify container is still running with `podman ps`
- Then check `podman logs < container-name >` for "Application startup complete"
- Continue until timeout or success
- If container exits, logs won't be available (that's why we check podman ps first)

# 8. Collect Logs for Debugging
- Capture container logs: `podman logs < container-name >`
- Capture service logs: `journalctl - -user - xeu spyre-<usecase > .service`
- Display all logs in test output for user debugging

# 9. Cleanup (tearDown)
- Get final service logs for debugging
- Stop systemd service
- Force remove container if it exists
- Verify container is completely removed
- Remove quadlet file
- Reload systemd daemon to unload the service
- Log cleanup completion

# Quadlet File Format

Each test creates a Podman Quadlet `.container` file with this structure:

```ini
[Unit]
Description = Spyre Entity Extraction
After = network-online.target

[Container]
ContainerName = spyre-entity-extract
PublishPort = 127.0.0.1: : 8000
Image = container-image

Environment = AIU_PCIE_IDS = "0301:50:00.0"

PodmanArgs = --device = /dev/vfio
PodmanArgs = --userns = keep-id
PodmanArgs = --group-add = keep-groups
PodmanArgs = --pids-limit = 0
PodmanArgs = --memory = 200G

Volume = /opt/ibm/spyre/models/src: / models

Exec = --model / models/granite-3.3-8b-instruct - tp 1 - -max-model-len 3072 - -max-num-seqs 16

[Service]
Slice = spyre-entity-extract.slice
Restart = no

[Install]
WantedBy = default.target
```

# Pass/Fail Criteria

# Test PASSES if:
- VFIO devices exist with correct group ownership
- Test user is in spyre group
- Quadlet file is created in correct location
- Systemd daemon reloads successfully
- Service starts without errors
- Container is created and running(verified with `podman ps`)
- VLLM server starts within timeout period
- "Application startup complete" message appears in logs
- No VFIO access errors in logs

# Test FAILS if:
- VFIO devices not found or not properly configured
- User not in spyre group
- Failed to create quadlet file
- Systemd daemon-reload fails
- Service fails to start
- Container is not created(not in `podman ps` output)
- Container exits before VLLM starts
- VLLM fails to start within timeout
- VFIO device access errors detected in logs
- "Application startup complete" message not found

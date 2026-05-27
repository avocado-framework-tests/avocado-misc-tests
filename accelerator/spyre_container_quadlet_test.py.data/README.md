# Spyre Container Quadlet Test Suite

## Overview

This test suite validates Spyre AI accelerator use cases using **Podman Quadlet** (systemd container management). It provides automated testing for:

- **Entity Extraction** - Text entity extraction using Granite models
- **Embedding** - Text embedding generation
- **Reranker** - Document reranking/scoring
- **RAG** (Retrieval-Augmented Generation) - Full RAG pipeline

## Key Features

1. **Systemd Integration**: Uses Podman Quadlet for container lifecycle management via systemd
2. **Journalctl Monitoring**: Real-time log monitoring and collection using journalctl
3. **Parallel Execution**: Supports parallel startup of multiple containers
4. **Sequential Testing**: Automated sequential testing with PCIe ID management
5. **User-mode Execution**: Runs as `senuser` using systemd --user services

## Architecture

### Quadlet Files

The test generates `.container` files in `/home/senuser/.config/containers/systemd/` which are processed by Podman Quadlet to create systemd services.

Example quadlet file structure:
```ini
[Unit]
Description=Spyre Entity Extraction
After=network-online.target

[Container]
ContainerName=spyre-entity-extract
PublishPort=127.0.0.1::8000
Image=""
Environment=AIU_PCIE_IDS="0301:50:00.0"
PodmanArgs=--device=/dev/vfio
PodmanArgs=--userns=keep-id
PodmanArgs=--group-add=keep-groups
PodmanArgs=--pids-limit=0
PodmanArgs=--memory=200G
PodmanArgs=--privileged=true
Volume=/opt/ibm/spyre/models:/models
Exec=--model /models/granite-3.3-8b-instruct -tp 1 --max-model-len 3072 --max-num-seqs 16 --max-num-batched-tokens 512

[Service]
Slice=spyre-ee.slice
Restart=always

[Install]
WantedBy=default.target
```

### Service Management

Services are managed using systemd --user commands:
```bash
# Reload systemd to pick up new quadlet files
systemctl --user daemon-reload

# Start a service
systemctl --user start spyre-entity-extract.service

# Stop a service
systemctl --user stop spyre-entity-extract.service

# View logs
journalctl --user -u spyre-entity-extract.service -f
```

## Prerequisites

### System Requirements

- **Platform**: IBM Power (ppc64le)
- **OS**: Linux with systemd
- **Podman**: Version 4.0 or higher with Quadlet support
- **VFIO Spyre devices**: Available at `/dev/vfio`

### User Setup

The test runs as `senuser`. Ensure this user exists and has proper permissions:

```bash
# User should be in sentient group for model access
usermod -aG sentient senuser

# Enable linger for senuser (allows services to run without login)
loginctl enable-linger senuser
```

### Directory Structure

```
/opt/ibm/spyre/models/          # Model storage (0775, root:sentient)
/home/senuser/.config/containers/systemd/  # Quadlet files
/var/log/journal/               # Persistent journal logs (2755, root:systemd-journal)
/etc/systemd/system/user@.service.d/  # Systemd user service config
```

### Models

Download required models to `/opt/ibm/spyre/models/`:

- `granite-3.3-8b-instruct` - For Entity Extraction and RAG
- `granite-embedding-125m-english` - For Embedding
- `bge-reranker-v2-m3` - For Reranker

## Configuration

### YAML Configuration File

Create `spyre_quadlet_test.yaml` with your configuration:

```yaml
# Container Image (user configurable)
IMAGE: ""

# PCIe IDs (space-separated list)
PCIE_IDS: "0233:70:00.0 0234:80:00.0 0333:70:00.0 0334:80:00.0"

# Entity Extraction Configuration
EE_MEMORY: "200G"
EE_MODEL_PATH: "/models/granite-3.3-8b-instruct"
EE_TENSOR_PARALLEL: 1
EE_MAX_MODEL_LEN: 3072
EE_MAX_NUM_SEQS: 16
EE_MAX_NUM_BATCHED_TOKENS: 512

# Embedding Configuration
EMB_MEMORY: "1500G"
EMB_MODEL_PATH: "/models/granite-embedding-125m-english"
EMB_TENSOR_PARALLEL: 1
EMB_MAX_MODEL_LEN: 512
EMB_MAX_NUM_SEQS: 4
EMB_MAX_NUM_BATCHED_TOKENS: 512

# Reranker Configuration
RR_MEMORY: "1500G"
RR_MODEL_PATH: "/models/bge-reranker-v2-m3"
RR_TENSOR_PARALLEL: 1
RR_MAX_MODEL_LEN: 1024
RR_MAX_NUM_SEQS: 4
RR_MAX_NUM_BATCHED_TOKENS: 512

# RAG Configuration
RAG_MEMORY: "200G"
RAG_SHM_SIZE: "2G"
RAG_MODEL_PATH: "/models/granite-3.3-8b-instruct"
RAG_TENSOR_PARALLEL: 4
RAG_MAX_MODEL_LEN: 32768
RAG_MAX_NUM_SEQS: 32
RAG_MAX_NUM_BATCHED_TOKENS: 512

# Host models directory
HOST_MODELS_DIR: "/opt/ibm/spyre/models"
```

### Key Parameters

- **IMAGE**: Container image for EE, Embedding, and Reranker
- **RAG_IMAGE**: Separate image for RAG (may use different version)
- **PCIE_IDS**: Space-separated list of PCIe device IDs for AIU accelerators
- **Memory settings**: Adjust based on your system capacity
- **Model paths**: Must match downloaded model locations

## Running Tests

### Individual Use Case Tests

Test each use case separately:

```bash
# Test Entity Extraction
avocado run spyre_container_quadlet_test.py:SpyreQuadletTest.test_entity_extraction_quadlet \
    --mux-yaml spyre_quadlet_test.yaml

# Test Embedding
avocado run spyre_container_quadlet_test.py:SpyreQuadletTest.test_embedding_quadlet \
    --mux-yaml spyre_quadlet_test.yaml

# Test Reranker
avocado run spyre_container_quadlet_test.py:SpyreQuadletTest.test_reranker_quadlet \
    --mux-yaml spyre_quadlet_test.yaml

# Test RAG
avocado run spyre_container_quadlet_test.py:SpyreQuadletTest.test_rag_quadlet \
    --mux-yaml spyre_quadlet_test.yaml
```

### Sequential All Use Cases Test

This test demonstrates the full workflow:
1. Starts EE, Reranker, and Embedding in parallel (each with 1 PCIe ID)
2. Waits for all three to start successfully
3. Shuts down all three containers
4. Starts RAG with all 4 PCIe IDs

```bash
avocado run spyre_container_quadlet_test.py:SpyreQuadletTest.test_all_usecases_quadlet_sequential \
    --mux-yaml spyre_quadlet_test.yaml
```

**Note**: This test requires 4 PCIe IDs in the YAML configuration.

## Test Workflow

### Setup Phase

1. **Platform Validation**: Verifies Power platform
2. **Package Installation**: Installs Podman if needed
3. **Spyre Device Check**: Validates VFIO devices exist
4. **Directory Setup**: Creates required directories with proper permissions
5. **Linger Enable**: Enables loginctl linger for senuser
6. **Journal Configuration**: Sets up persistent journald logging
7. **Model Verification**: Checks that required models are downloaded

### Test Execution Phase

For each use case:

1. **Generate Quadlet File**: Creates `.container` file with configuration
2. **Reload Systemd**: Runs `systemctl --user daemon-reload`
3. **Start Service**: Starts the systemd service
4. **Monitor Logs**: Watches journalctl for VLLM startup message
5. **Collect Logs**: Saves journalctl logs to `/tmp/<service-name>.log`
6. **Stop Service**: Stops the systemd service

### Teardown Phase

1. **Stop Active Services**: Stops any remaining active services
2. **Cleanup**: Removes temporary files

## Log Collection

Logs are collected in two ways:

1. **Real-time Monitoring**: During test execution, logs are displayed to stdout
2. **Log Files**: Complete logs saved to `/tmp/<service-name>.log`

Example log file locations:
- `/tmp/spyre-entity-extract.log`
- `/tmp/spyre-embedding.log`
- `/tmp/spyre-reranker.log`
- `/tmp/spyre-rag.log`

View logs manually:
```bash
# View all logs for a service
journalctl --user -u spyre-entity-extract.service

# Follow logs in real-time
journalctl --user -u spyre-entity-extract.service -f

# View logs since last boot
journalctl --user -u spyre-entity-extract.service -b
```

## VLLM Startup Detection

The test monitors journalctl logs for the VLLM startup message:
```
Application startup complete.
```

It also checks for error conditions:
- **BACKTRACE**: Indicates a crash
- **VFIO fail**: Indicates device access failure

## Troubleshooting

### Service Won't Start

```bash
# Check service status
systemctl --user status spyre-entity-extract.service

# View detailed logs
journalctl --user -u spyre-entity-extract.service -n 100

# Check if quadlet file exists
ls -la /home/senuser/.config/containers/systemd/

# Verify systemd picked up the quadlet file
systemctl --user list-unit-files | grep spyre
```

### VFIO Device Access Issues

```bash
# Check VFIO devices
ls -la /dev/vfio/

# Verify user is in correct groups
id senuser

# Check device permissions
ls -la /dev/vfio/*
```

### Model Not Found

```bash
# Verify models directory
ls -la /opt/ibm/spyre/models/

# Check model permissions
ls -la /opt/ibm/spyre/models/granite-3.3-8b-instruct/
```

### Journald Logs Not Persisting

```bash
# Check journald configuration
grep Storage /etc/systemd/journald.conf

# Verify journal directory
ls -la /var/log/journal/

# Restart journald
systemctl restart systemd-journald
```

### Linger Not Enabled

```bash
# Check linger status
loginctl show-user senuser | grep Linger

# Enable linger
loginctl enable-linger senuser
```

## Advanced Usage

### Custom PCIe ID Assignment

For the sequential test, PCIe IDs are assigned as follows:
- **EE**: First PCIe ID (index 0)
- **Reranker**: Second PCIe ID (index 1)
- **Embedding**: Third PCIe ID (index 2)
- **RAG**: All PCIe IDs

Modify `PCIE_IDS` in YAML to change assignment.

### Parallel Execution

The `test_all_usecases_quadlet_sequential` test uses Python threading to start multiple services in parallel. This demonstrates efficient resource utilization when multiple AIU devices are available.

### Custom Timeout

Modify startup timeout in the test code:
```python
# Default timeout is 600 seconds (10 minutes)
# For RAG, timeout is 900 seconds (15 minutes)
startup_success = self.wait_for_vllm_startup_journalctl(
    service_name, 
    timeout=1200  # Custom 20-minute timeout
)
```

## Comparison with Direct Podman Test

| Feature | Quadlet Test | Direct Podman Test |
|---------|-------------|-------------------|
| Container Management | systemd services | Direct podman commands |
| Log Collection | journalctl | podman logs |
| Service Persistence | Survives reboots | Manual restart needed |
| Startup Control | systemd dependencies | Manual sequencing |
| Resource Management | systemd slices | Manual cgroups |
| User Mode | systemd --user | podman --userns |

## References

- [Podman Quadlet Documentation](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
- [systemd User Services](https://www.freedesktop.org/software/systemd/man/user@.service.html)
- [journalctl Manual](https://www.freedesktop.org/software/systemd/man/journalctl.html)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review journalctl logs for detailed error messages
3. Verify all prerequisites are met
4. Contact the Spyre team for AIU-specific issues

---

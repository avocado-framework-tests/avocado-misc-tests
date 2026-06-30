# Spyre Host Configuration — Test Parameters

This directory contains the YAML parameter file for `spyre_Host_config.py`,
the host setup test suite for the IBM Spyre AI accelerator.

## Run

```bash
avocado run spyre_Host_config.py --mux-yaml spyre_Host_config.py.data/spyre_Host_config.yaml  --max-parallel-tasks=1
```

## Parameters

### User Configuration
| Parameter | Description | Default |
|---|---|---|
| `USER` | Local user to create and configure for Spyre workloads | — |
| `PASSWORD` | Password for the above user | — |
| `SPYRE_GROUP` | Group to add the user to for Spyre device access | — |

### Directory Configuration
| Parameter | Description | Default |
|---|---|---|
| `HOST_MODELS_DIR` | Path where AI model directories will be created | `/opt/ibm/spyre/models/src` |

### Registry Configuration
| Parameter | Description | Default |
|---|---|---|
| `REGISTRY` | Container registry hostname | - |
| `API_KEY` | API key for podman login to the registry | — |

### IBM Repository / ServiceReport
| Parameter | Description |
|---|---|
| `SERVICEREPORT_URL` | Direct URL to ServiceReport RPM. Use a public URL (no auth) or a GSA URL with `gsa_user`/`gsa_password` |
| `GSA_USER` | IBM GSA username — required only when `servicereport_rpm_url` points to gsa |
| `GSA_PASSWORD` | IBM GSA password — required only when `servicereport_rpm_url` points to gsa |


### Red Hat Registration
| Parameter | Description |
|---|---|
| `REDHAT_USER` | Red Hat subscription username |
| `REDHAT_PASSWORD` | Red Hat subscription password |

### HuggingFace
| Parameter | Description |
|---|---|
| `HF_TOKEN` | HuggingFace access token for `hf auth login`. Get one at https://huggingface.co/settings/tokens |

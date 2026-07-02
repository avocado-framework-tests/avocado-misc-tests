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
| `username` | Local user to create and configure for Spyre workloads | — |
| `password` | Password for the above user | — |
| `spyre_group` | Group to add the user to for Spyre device access | — |

### Directory Configuration
| Parameter | Description | Default |
|---|---|---|
| `models_dir` | Path where AI model directories will be created | `/opt/ibm/spyre/models/src` |

### Registry Configuration
| Parameter | Description | Default |
|---|---|---|
| `registry` | Container registry hostname | - |
| `api_key` | API key for podman login to the registry | — |

### IBM Repository / ServiceReport
| Parameter | Description |
|---|---|
| `servicereport_rpm_url` | Direct URL to ServiceReport RPM. Use a public URL (no auth) or a GSA URL with `gsa_user`/`gsa_password` |
| `gsa_user` | IBM GSA username — required only when `servicereport_rpm_url` points to gsa |
| `gsa_password` | IBM GSA password — required only when `servicereport_rpm_url` points to gsa |

**Public URL example:**
```
servicereport_rpm_url: ""
```
**GSA URL example (requires gsa_user + gsa_password):**
```
gsa_user: "your_ibm_id"
gsa_password: "your_gsa_password"
```

### Red Hat Registration
| Parameter | Description |
|---|---|
| `redhat_user` | Red Hat subscription username |
| `redhat_pass` | Red Hat subscription password |

### HuggingFace
| Parameter | Description |
|---|---|
| `hf_token` | HuggingFace access token for `hf auth login`. Get one at https://huggingface.co/settings/tokens |

# Spyre HTX Container Test

## Overview

HTX (Hardware Test eXecutive) stress test suite for Spyre AIU (AI Unit) devices using container-based exercisers on IBM Power systems.

## Test Types

| Type | MDT File | Description |
|------|----------|-------------|
| `test` | mdt.container_spyre_test | Basic Spyre exerciser test |
| `stress` | mdt.container_spyre_stress_test | High stress & power consumption with EEH |
| `eeh` | mdt.container_spyre_eeh_test | Dedicated EEH testing |
| `bu` | mdt.container_spyre_bu_test | Spyre with Memory/CPU exercisers |
| `granite` | mdt.container_spyre_test | Granite AI model testing |

## Prerequisites

- IBM Power system (ppc64/ppc64le)
- Root/sudo access
- HTX RPM or Git source
- Podman for containers
- Spyre AIU devices installed

## Configuration

Edit [`spyre_htx.yaml`](spyre_htx_test.py.data/spyre_htx.yaml:1):

```yaml
test_type: test              # test, stress, eeh, bu, granite
time_limit: 2                # Duration
time_unit: h                 # 'm' (minutes) or 'h' (hours)
run_type: rpm                # rpm or git
htx_rpm_link: "https://..."  # HTX RPM repository
enable_eeh: '0'              # '1' to enable EEH testing
eeh_retries: '5'             # Number of EEH injections
gsa_user: ""                 # For granite test
gsa_password: ""             # For granite test
model_url: "https://..."     # Granite model URL
```

## Usage

### Basic Test (2 hours)
```bash
avocado run spyre_htx_test.py --mux-yaml spyre_htx_test.py.data/spyre_htx.yaml
```

### Stress Test (4 hours)
```yaml
test_type: stress
time_limit: 4
time_unit: h
```

### EEH Test (1 hour, 10 retries)
```yaml
test_type: eeh
time_limit: 1
time_unit: h
enable_eeh: '1'
eeh_retries: '10'
```

### Granite Model Test
```yaml
test_type: granite
time_limit: 4
time_unit: h
gsa_user: "your_username"
gsa_password: "your_password"
model_url: ""
```

## How It Works

1. **PCI Detection**: Automatically detects Spyre buses using `lsslot -c pci | grep WZS01YY`
2. **Configuration**: Writes PCI addresses to `/usr/lpp/htx/setup/spyre_power_config.txt`
3. **Setup**: Runs `/usr/lpp/htx/setup/hxespyre.config` configuration script
4. **Container Creation**: Executes `hcl -setup_container spyre` to create container image and MDTs
5. **Test Execution**: Runs selected MDT file with HTX
6. **Monitoring**: Uses `hcl -query` and `hcl -get_run_time` for status
7. **Log Collection**: Copies logs from containers to `/tmp/spyre_ctr<N>_hxespyre.log`

## EEH Testing

When `enable_eeh: '1'`:
- Sets `HTXEEH=1` environment variable
- Sets `HTXEEHRETRIES` to configured value
- Injects errors with 5s gap for card recovery
- Validates device recovery after each injection

## Granite Model Testing

For `test_type: granite`:
- Downloads model from GSA server (requires credentials)
- Large download (~several GB), may take hours
- Downloads to `/tmp` directory
- Ensure sufficient disk space available

## Logs

- **HTX Logs**: `/tmp/htx/`
- **Container Logs**: `/tmp/spyre_ctr<N>_hxespyre.log`
- **Avocado Logs**: `~/avocado/job-results/`

## Author

Abdul Haleem <abdhalee@linux.vnet.ibm.com>

## License

GNU General Public License v2.0 or later

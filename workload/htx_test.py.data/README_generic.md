# Generic HTX Test

This configuration runs HTX with generic MDT files for overall system stress testing.

## Overview

The generic HTX test allows you to run HTX with any MDT file to stress test various system components including memory, CPU, and other hardware.

## Configuration File

### htx_generic.yaml

Configuration for generic HTX testing.

**Key Parameters:**
- `mdt_file`: MDT file to use (default: mdt.mem)
- `time_limit`: Duration to run the test
- `time_unit`: 'm' for minutes, 'h' for hours
- `run_type`: 'rpm' or 'git' installation
- `htx_rpm_link`: URL to HTX RPM repository

## Common MDT Files

- `mdt.mem` - Memory stress testing
- `mdt.cpu` - CPU stress testing
- `mdt.all` - Overall system stress (all devices)
- Custom MDT files as needed

## Usage Examples

### Basic Memory Test
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_generic.yaml
```

### CPU Test for 4 Hours
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_generic.yaml \
    -p mdt_file=mdt.cpu \
    -p time_limit=4 \
    -p time_unit=h
```

### Custom MDT File
```bash
avocado run workload/htx_test.py --mux-yaml workload/htx_test.py.data/htx_generic.yaml \
    -p mdt_file=mdt.custom
```

## Test Phases

1. **test_start**: Setup HTX, select and activate MDT file, start the test
2. **test_check**: Monitor test execution and check for errors every 60 seconds
3. **test_stop**: Stop HTX and cleanup

## Requirements

- **Platform**: Power Architecture (ppc64/ppc64le)
- **Operating Systems**: RHEL, CentOS, Fedora, Ubuntu, SLES
- **HTX Installation**: RPM or Git source

## Installation Methods

### RPM Installation (Recommended)
- Faster installation
- Pre-built packages
- Requires `htx_rpm_link` parameter
- Automatically selects correct RPM for distro

### Git Installation
- Latest development version
- Builds from source
- Requires build tools
- Set `run_type: git`

## Error Handling

The test monitors HTX error logs (`/tmp/htxerr`) and fails if:
- HTX reports any errors during execution
- HTX daemon fails to start
- MDT file is not found or cannot be created

## Troubleshooting

### HTX Installation Fails
- Verify `htx_rpm_link` is accessible
- Check network connectivity
- Ensure required packages are installed

### MDT File Not Found
- Verify MDT file name is correct
- Check `/usr/lpp/htx/mdt/` directory
- Enable on-demand MDT creation (automatic)

### Test Fails to Start
- Check HTX daemon status
- Verify MDT file can be selected
- Check system logs for errors


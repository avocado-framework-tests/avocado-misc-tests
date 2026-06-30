Goodpath Scenarios Test Suite
==============================

This test suite validates storage stack reliability under stress conditions
by combining RAID, LVM, and workload testing.

Test Cases
----------

1. test_rawread_on_raid_lvm
   - Creates RAID1 array across all provided disks
   - Provisions 4 LVM logical volumes on the RAID array
   - Runs rawread stress test on each LV (24 test types per LV)
   - Monitors system health every 5 minutes for 1 hour
   - Validates RAID, LVM, and storage stack integrity

2. test_swraid_fs_fio
   - Creates RAID1 array on first two disks
   - Triggers RAID rebuild by removing and re-adding a disk
   - Creates ext4 filesystem on third disk
   - Runs concurrent LTP fsstress and FIO tests
   - Monitors RAID rebuild progress and system health
   - Validates concurrent I/O operations during RAID rebuild

3. test_htx_stress_with_diagnostic_report
   - Verifies ppc64 architecture (HTX is Power-only)
   - Installs HTX via RPM link or git build from open-power GitHub
   - Creates MDT, activates all YAML-provided disks in HTX
   - Runs HTX block-device stress for 30 minutes (configurable)
   - Polls every 60 seconds for HTX errors (htxcmdline -geterrlog) and
     new storage-related dmesg errors throughout the stress window
   - Stops HTX gracefully on completion
   - RHEL/CentOS/Fedora: generates sos report (--batch --label htx-stress-goodpath)
   - SuSE: generates supportconfig (-R <output_dir>)
   - Logs archive path; fails if HTX errors or report generation fails

Configuration
-------------

Required YAML parameter:
  disks: Space-separated list of disk devices (minimum 4 required)
         Example: "/dev/sdb /dev/sdc /dev/sdd /dev/sde"
         or NVMe: "/dev/nvme0n1 /dev/nvme0n2 /dev/nvme0n3 /dev/nvme0n4"

Optional HTX parameters (test_htx_stress_with_diagnostic_report):
  htx_run_type:          'git' to build from GitHub source (default: RPM install)
  htx_rpm_link:          Base URL for HTX RPM packages (required for RPM install)
  htx_mdt_file:          MDT file to use (default: mdt.hd)
  htx_stress_duration_min: Stress duration in minutes (default: 30)

Example YAML (goodpath_scenarios.yaml):
  disks: "/dev/sdb /dev/sdc /dev/sdd /dev/sde"
  htx_mdt_file: 'mdt.hd'
  htx_stress_duration_min: 30

Test Duration
-------------
- Default test duration (RAID/FIO tests): 3600 seconds (1 hour)
- Monitoring interval: 300 seconds (5 minutes)
- HTX stress default: 30 minutes (configurable via htx_stress_duration_min)

Dependencies
------------
- mdadm (Software RAID)
- lvm2 (Logical Volume Manager)
- fio (Flexible I/O Tester)
- gcc, make, g++/gcc-c++ (for rawread compilation)
- libaio-dev/libaio-devel (for rawread)
- HTX (Hardware Test eXecutive) - ppc64 only; from RPM or GitHub
- sos (RHEL/CentOS/Fedora) or supportutils (SuSE) for diagnostic reports

Rawread Tool
------------
The rawread tool is compiled from source during test setup. It performs
24 different types of read tests on block devices to validate storage
reliability under various access patterns.

Expected Behavior
-----------------
- Test 1: Rawread processes run on all 4 LVs simultaneously
- Test 2: RAID rebuild is intentionally triggered and monitored
- Both tests filter out expected errors from intentional actions
- Only unexpected storage errors cause test failure
- Non-storage kernel errors (plpks, SED, pstore) are logged but ignored

Error Handling
--------------
The test suite implements intelligent error filtering:
- Expected errors from intentional actions (RAID rebuild) are ignored
- Storage-related errors (RAID, LVM, I/O, filesystem) are detected
- Non-storage errors are logged but don't cause failure
- Test completes full duration before reporting failures

Monitoring
----------
During test execution, the following are monitored:
- Rawread/FIO/fsstress process status
- Kernel dmesg for storage-related errors
- LVM logical volume health
- RAID array status and rebuild progress
- System stability under concurrent I/O load

Usage
-----
Run specific test:
  avocado run goodpath_scenarios.py:GoodpathScenarios.test_rawread_on_raid_lvm \
    --mux-yaml goodpath_scenarios.yaml

  avocado run goodpath_scenarios.py:GoodpathScenarios.test_htx_stress_with_diagnostic_report \
    --mux-yaml goodpath_scenarios.yaml

Run all tests:
  avocado run goodpath_scenarios.py --mux-yaml goodpath_scenarios.yaml

Notes
-----
- Minimum 4 disks required for test_rawread_on_raid_lvm and test_swraid_fs_fio
- test_htx_stress_with_diagnostic_report requires only the YAML 'disks' list
  (no minimum disk count enforced beyond what HTX needs for the MDT)
- All disks will be wiped by RAID/LVM tests - ensure no important data exists
- Tests require root/sudo privileges
- RAID sync may take time depending on disk size
- Rawread is architecture-independent (works on x86_64, ppc64, etc.)
- HTX is ppc64-only; test_htx_stress_with_diagnostic_report will cancel on
  non-ppc64 platforms
- sos report is generated on RHEL/CentOS/Fedora; supportconfig on SuSE
  Other distributions log a warning and skip report generation
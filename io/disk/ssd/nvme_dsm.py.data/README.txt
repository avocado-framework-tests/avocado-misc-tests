NVMe Dataset Management (DSM) Test
===================================

Source file : io/disk/ssd/nvme_dsm.py
Config file : io/disk/ssd/nvme_dsm.py.data/nvme_dsm.yaml
Author      : Naresh Bannoth <nbannoth@in.ibm.com>
Copyright   : 2026 IBM


Overview
--------
Issues the NVMe Dataset Management (DSM) command on the target namespace
and verifies that the namespace remains accessible and fully functional
after the command completes.

The DSM command (also known as Deallocate or TRIM) is used to notify the
device that certain LBA ranges are no longer in use.  This test suite
exercises DSM in three distinct ways:

  test_dsm       — individual attribute flags (-d -w -r)
  test_dsm_cdw11 — raw DWORD 11 value (-c 0x7, equivalent to -d -w -r)

Both tests apply a configurable command timeout via the -t flag
(hardcoded to 5000 ms in setUp).

The namespace to operate on is discovered automatically at runtime.
setUp calls nvme.get_current_ns_list() on the controller and picks the
first namespace returned.  No namespace parameter is required in the YAML.

The test requires the device to advertise "Data Set Management Supported"
in the human-readable output of nvme id-ctrl -H.  Devices that do not
support DSM are automatically skipped (CANCEL).


Prerequisites
-------------
- An NVMe controller visible to the OS (e.g. /dev/nvme0).
- At least one namespace present on that controller.
- nvme-cli installed (distro package) or internet access to build upstream.
- Root / sudo privileges.
- meson (only required when package=upstream).


Configuration (nvme_dsm.yaml)
------------------------------
Key               Default    Description
---------         -------    ---------------------------------------------------
device            (none)     NVMe controller to target.  Accepted formats:
                             - Controller short name : nvme0
                             - Subsystem name        : nvme-subsys0
                             - NQN string            : nqn.1994-11.com...
                             Must be provided; test cancels if absent.

shared_namespaces False      Set True when the namespace is a shared
                             (multipath) namespace.

package           distro     'distro'   — use the OS-packaged nvme-cli.
                             'upstream' — build nvme-cli from the GitHub
                                          master branch (requires meson).

namespace                    NOT a config parameter.  The first namespace
                             on the controller is discovered automatically
                             via nvme.get_current_ns_list() at setUp time.


Running the Test
----------------
Run all variants (both distro and upstream via the !mux):

    avocado run nvme_dsm.py -m nvme_dsm.py.data/nvme_dsm.yaml

Run only the distro variant:

    avocado run nvme_dsm.py -p device=nvme0 -p package=distro

Run only the upstream variant:

    avocado run nvme_dsm.py -p device=nvme0 -p package=upstream

Run with a multipath (shared) namespace:

    avocado run nvme_dsm.py -p device=nvme0 -p shared_namespaces=True

Run a single test method:

    avocado run nvme_dsm.py:NVMeDataSetManagement.test_dsm_cdw11 -p device=nvme0


Test Details
------------
test_dsm
    Issues the NVMe Dataset Management command using individual attribute
    flags and verifies the namespace is healthy afterwards.

    Command issued:
        nvme dsm <ns> -a 1 -b 1 -s 1 -d -w -r -t <dsm_timeout>

    Steps:
      1. Resolve the device and namespace paths; cancel if either is absent.
      2. Install / build nvme-cli according to the 'package' parameter.
      3. Verify DSM support via nvme id-ctrl -H; cancel if not advertised.
      4. Confirm the namespace block device is accessible.
      5. Issue the DSM command with Deallocate, Write, and Read attributes
         on range: 1 entry, 1 block, starting LBA 1.
      6. Fail if the DSM command returns a non-zero exit code.
      7. Verify the namespace block device is still accessible after DSM.
      8. Verify the namespace ID is still listed by the controller
         (nvme.is_ns_exists).
      9. Issue a read of one block to confirm I/O is functional after DSM:
             nvme read <ns> -z <block_size>
     10. Fail if the read returns a non-zero exit code.

test_dsm_cdw11
    Issues the NVMe Dataset Management command using raw DWORD 11 (-c 0x7)
    instead of individual attribute flags, and verifies the namespace is
    healthy afterwards.

    DWORD 11 bit layout (NVMe spec):
      Bit 0 : Attribute Deallocate (AD)
      Bit 1 : Attribute Integral Dataset for Write (IDW)
      Bit 2 : Attribute Integral Dataset for Read (IDR)
    Value 0x7 (binary 111) sets all three attributes — equivalent to -d -w -r.

    Command issued:
        nvme dsm <ns> -a 1 -b 1 -s 1 -c 0x7 -t <dsm_timeout>

    Steps:
      1–4. Same setup/validation as test_dsm.
      5. Issue the DSM command with -c 0x7 (raw DWORD 11).
      6. Fail if the command returns a non-zero exit code.
      7–10. Same post-DSM namespace and I/O validations as test_dsm.

Expected Results
----------------
PASS   : DSM command and post-DSM read both succeed; namespace remains
         visible and accessible throughout.
CANCEL : Device does not support Data Set Management, the namespace does
         not exist, or a required build step failed.
FAIL   : DSM command or post-DSM read returned a non-zero exit code,
         indicating a command error or I/O failure after deallocate.

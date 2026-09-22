NVMe Compare Test
=================

Description
-----------
Writes a known data pattern to an NVMe namespace and then issues the
NVMe Compare command to verify that the data resident on the media
matches the host buffer. A mismatch causes the test to fail, indicating
a data-integrity problem.

The test requires the device to advertise Compare support via bit 0 of
the ONCS (Optional NVM Command Support) field in id-ctrl. Devices that
do not support Compare are automatically skipped (CANCEL).

Source file : io/disk/ssd/nvme_compare.py
Config file : io/disk/ssd/nvme_compare.py.data/nvme_compare.yaml


Prerequisites
-------------
- Root privileges (nvme write requires direct device access).
- The target NVMe namespace must exist before the test is run.
- For the 'distro' package variant: nvme-cli must be installable via
  the OS package manager.
- For the 'upstream' package variant: meson and an internet connection
  are required to fetch and build nvme-cli from GitHub master.


Parameters (nvme_compare.yaml)
------------------------------
device
    NVMe controller to target. Accepted formats:
      controller  : nvme0
      subsystem   : nvme-subsys0
      NQN         : nqn.1994-11.com.vendor:nvme:model:serial

namespace
    Namespace number to use for I/O (default: 1).
    The test operates on /dev/<device>n<namespace>.

shared_namespaces
    Set to True when the namespace is a shared (multipath) namespace
    (default: False).

package
    Selects the nvme-cli binary to use:
      distro   - use the OS-packaged nvme-cli (default).
      upstream - fetch and build nvme-cli from the GitHub master branch.
    The yaml mux runs both variants in a single job invocation.


Test Steps
----------
1. Resolve the device path and verify it exists.
2. Install / build nvme-cli according to the 'package' parameter.
3. Determine the namespace block size via nvme id-ns.
4. Read the ONCS field from nvme id-ctrl; cancel if bit 0 is not set.
5. Verify the namespace block device exists.
6. Confirm the namespace block device is accessible.
7. Write one block (block_size bytes) of data to LBA 0:
       echo 1 | nvme write <ns> -z <block_size> -t
8. Compare the same block against the host buffer:
       echo 1 | nvme compare <ns> -z <block_size>
9. Fail if either command returns a non-zero exit code.


Running the Test
----------------
    avocado run nvme_compare.py -m nvme_compare.py.data/nvme_compare.yaml

To run only the distro variant:
    avocado run nvme_compare.py -p package=distro -p device=nvme0

To run only the upstream variant:
    avocado run nvme_compare.py -p package=upstream -p device=nvme0


Expected Results
----------------
PASS   : Write and Compare both succeed; data on media matches host buffer.
CANCEL : Device does not support the Compare command (ONCS bit 0 = 0),
         or a required build step failed.
FAIL   : Write or Compare returned a non-zero exit code, indicating
         an I/O error or data-integrity mismatch.

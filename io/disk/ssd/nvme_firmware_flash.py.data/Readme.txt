NVMe Firmware Flash Test
========================

Prerequisites
-------------
- nvme-cli package must be installed before running this test.
  Install : dnf install nvme-cli      (RHEL/Fedora)
            apt install nvme-cli      (Ubuntu/Debian)
            zypper install nvme-cli   (SUSE/openSUSE)

Parameters
----------
device       : NVMe controller to target.
               Run "nvme list" to get available controllers, e.g.:
                 /dev/nvme0  ...  -> use "nvme0" as the device value
               Formats accepted:
                 nvme0                                  (controller name)
                 nvme-subsys0                           (subsystem name)
                 nqn.1994-11.com.vendor:nvme:model:SN  (NQN)

firmware_url : URL to the firmware image to download and flash.
               Example: https://example.com/firmware/A180010F.43395339

fw_version   : (Optional) The exact firmware version string the device
               should report after a successful flash, as seen in the
               output of "nvme id-ctrl /dev/nvme0 | grep -w '^fr'".
               Example: fr  : 43395339  -> set fw_version: 43395339

               Why use it:
               - NVMe firmware filenames (e.g. A180010F.43395339) do not
                 have a fixed format across vendors, so the test cannot
                 reliably derive the expected version from the filename.
               - Setting fw_version lets the test do an exact match:
                 version reported after flash == fw_version -> PASS
               - If not set, the test only checks that the version changed
                 (new != old) and logs a warning if it did not change.

Pass/Fail
---------
fw_version set   : PASS if all steps succeed AND reported version == fw_version
                   FAIL if any step fails OR reported version != fw_version
fw_version not set: PASS if all steps succeed AND version changed after flash
                    WARN if version did not change (flash may not have taken effect)

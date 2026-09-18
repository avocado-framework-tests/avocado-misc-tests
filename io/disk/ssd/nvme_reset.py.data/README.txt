NVMe Reset Tests
================

Source file : io/disk/ssd/nvme_reset.py
Config file : io/disk/ssd/nvme_reset.py.data/nvme_reset.yaml
Author      : Naresh Bannoth <nbannoth@in.ibm.com>
Copyright   : 2026 IBM


Overview
--------
Exercises the NVMe controller reset paths and verifies full device
recovery after each reset.  The target namespace is discovered
automatically at runtime by querying the controller — no manual namespace
ID is required in the configuration.

Tests cover:
  - Controller reset via nvme-cli (nvme reset)
  - Controller reset via sysfs (echo 1 > reset_controller)
  - NVM Subsystem Reset via nvme-cli (nvme subsystem-reset) — skipped if
    the device does not advertise support or if kernel lockdown is active

After every reset the tests:
  - Wait for the controller device node to reappear (up to 30 seconds).
  - Verify the controller device node is accessible.
  - Verify all pre-reset namespace IDs are still enumerated on the
    controller.


Prerequisites
-------------
- An NVMe controller visible to the OS (e.g. /dev/nvme0).
- At least one namespace present on that controller.
- nvme-cli installed (distro package) or internet access to build upstream.
- Root / sudo privileges.
- meson (only required when package=upstream).
- For test_subsystem_reset only:
    - 'NVM Subsystem Reset Supported' advertised in id-ctrl output.
    - Kernel lockdown disabled (/sys/kernel/security/lockdown = [none]).


Configuration (nvme_reset.yaml)
--------------------------------
Key               Default    Description
---------         -------    ---------------------------------------------------
device            (none)     NVMe controller name.  Accepted formats:
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


Running the Tests
-----------------
Run all tests (both distro and upstream variants via the !mux):

    avocado run nvme_reset.py \
        -p device=nvme0

Run only the distro-nvme-cli variant:

    avocado run nvme_reset.py \
        -p device=nvme0 \
        -p package=distro

Run a single test:

    avocado run nvme_reset.py:NVMeReset.test_reset \
        -p device=nvme0

Run with a multipath (shared) namespace:

    avocado run nvme_reset.py \
        -p device=nvme0 \
        -p shared_namespaces=True


Test Details
------------
test_reset
    Performs a controller reset using nvme-cli.
    Issues: nvme reset <device>
    Steps:
      1. Snapshot current namespace IDs.
      2. Issue the reset command; fail on non-zero exit code.
      3. Wait up to 30 s for /dev/<device> to reappear.
      4. Verify the controller device node is accessible.
      5. Verify all pre-reset namespace IDs are still listed (with
         nvme ns-rescan issued first).

test_reset_sysfs
    Performs a controller reset by writing to the sysfs attribute.
    Issues: echo 1 > /sys/class/nvme/<ctrl>/reset_controller
    Steps:
      1. Snapshot current namespace IDs.
      2. Write 1 to the sysfs reset_controller attribute; fail on error.
      3. Wait up to 30 s for /dev/<device> to reappear.
      4. Verify the controller device node is accessible.
      5. Verify all pre-reset namespace IDs are still listed.

test_subsystem_reset
    Performs an NVM Subsystem Reset using nvme-cli.
    Issues: nvme subsystem-reset <device>
    Automatically skipped when:
      - Kernel lockdown is active (/sys/kernel/security/lockdown != [none]).
      - show-regs reports 'NSSRS: No'.
      - id-ctrl does not advertise 'NVM Subsystem Reset Supported'.
    Steps:
      1. Check kernel lockdown and device capability; cancel if not met.
      2. Snapshot current namespace IDs.
      3. Issue subsystem-reset; fail on non-zero exit code.
      4. Wait up to 30 s for /dev/<device> to reappear.
      5. Verify the controller device node is accessible.
      6. Verify all pre-reset namespace IDs are still listed.

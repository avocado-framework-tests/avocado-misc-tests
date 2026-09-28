NVMe Namespace Management Tests
================================

Overview
--------
Exercises the full NVMe namespace management lifecycle — create, verify,
and delete — against a single NVMe controller.  The following scenarios
are covered:

  - Create a single namespace using ~60 % of free capacity and verify it
    is visible and accessible as a block device.
  - Create a namespace consuming the full device capacity and verify.
  - Create the maximum number of namespaces supported by the controller
    (nn field in id-ctrl), each with equal capacity, and verify all are
    visible and accessible.
  - Create a shared (multi-path) namespace with the nmic bit set and
    verify it is listed.
  - Create N equal-sized namespaces (count driven by the namespace_count
    parameter) and verify each one.
  - Delete all namespaces and verify none remain.

Each test saves a snapshot of the pre-existing namespace count in setUp
and restores the controller to that state in tearDown, regardless of
whether the test passed, failed, or was cancelled.


Prerequisites
-------------
- An NVMe controller visible to the OS (e.g. /dev/nvme0) that supports
  namespace management (NVM Subsystem supports Create / Delete NS).
- Root / sudo privileges.
- nvme-cli installed (distro package) or internet access to build upstream.
- meson (only required when package=upstream).


Configuration (nvme_namespace_management.yaml)
-----------------------------------------------
Key                Default    Description
---------          -------    ---------------------------------------------------
device             (none)     NVMe controller to target.  Accepted formats:
                              - Controller short name : nvme0
                              - Subsystem name        : nvme-subsys0
                              - NQN string            : nqn.1994-11.com...
                              Must be provided; test cancels if absent.

namespace_count    4          Number of equal-sized namespaces to create in
                              test_create_equal_ns.

shared_namespaces  False      Set True when working with shared (multi-path)
                              namespaces on an NVMe fabric.

package            distro     'distro'   — use the OS-packaged nvme-cli.
                              'upstream' — build nvme-cli from the GitHub
                                           master branch (requires meson).
                              The yaml mux runs both variants in one job.


Running the Tests
-----------------
Run all variants (both distro and upstream via the !mux):

    avocado run nvme_namespace_management.py \
        -m nvme_namespace_management.py.data/nvme_namespace_management.yaml

Run only the distro variant:

    avocado run nvme_namespace_management.py \
        -p device=nvme0 -p package=distro

Run only the upstream variant:

    avocado run nvme_namespace_management.py \
        -p device=nvme0 -p package=upstream

Run with a multipath (shared) namespace:

    avocado run nvme_namespace_management.py \
        -p device=nvme0 -p shared_namespaces=True

Run a specific test case only:

    avocado run nvme_namespace_management.py:NVMeNamespaceManagement.test_create_max_ns \
        -p device=nvme0


Test Details
------------
test_create_single_ns
    Creates one namespace using ~60 % of available free blocks and
    verifies it is visible and accessible.

    Steps:
      1. Delete all existing namespaces; verify none remain.
      2. Query free space and block size from id-ctrl / id-ns.
      3. Compute ns_size = 60 % of (free_space / block_size).
      4. Create namespace with ns_id = 1.
      5. Verify namespace is listed (nvme.is_ns_exists).
      6. Verify /dev/<ctrl>n1 is accessible as a block device.
      7. Delete the namespace; verify it is gone.

test_create_full_capacity_ns
    Creates a single namespace consuming the entire available capacity
    of the controller and verifies it is visible and accessible.

    Steps:
      1. Delete all existing namespaces; verify none remain.
      2. Create namespace using nvme.create_full_capacity_ns.
      3. Verify namespace exists and /dev/<ctrl>n1 is accessible.
      4. Delete the namespace; verify it is gone.

test_create_max_ns
    Creates the maximum number of namespaces (nn field in id-ctrl),
    each with equal capacity, then verifies all are visible and accessible.

    Steps:
      1. Delete all existing namespaces; verify none remain.
      2. Read max_ns from nvme.get_max_ns_supported.
      3. Create max_ns equal-sized namespaces via nvme.create_max_ns.
      4. For each created namespace verify it is listed and its block
         device is accessible.  Warn (not fail) if fewer than max_ns
         were created due to capacity limits.
      5. Delete all namespaces; verify none remain.

test_create_shared_ns
    Creates a shared namespace (nmic bit set) for multi-path access and
    verifies it appears in the namespace list.

    Steps:
      1. Delete all existing namespaces; verify none remain.
      2. Create one namespace with shared_ns=True (~60 % free space).
      3. Verify namespace exists and block device is accessible.
      4. Delete the namespace; verify it is gone.

test_create_equal_ns
    Creates *namespace_count* equal-sized namespaces and verifies each
    one is visible and accessible.

    Steps:
      1. Delete all existing namespaces; verify none remain.
      2. Create ns_count namespaces via nvme.create_namespaces.
      3. Verify every namespace ID 1..ns_count is listed and accessible.
      4. Delete all namespaces; verify none remain.

test_delete_all_ns
    Creates one namespace, verifies it exists, deletes all namespaces,
    and verifies none remain.

    Steps:
      1. Delete any pre-existing namespaces.
      2. Create a single namespace (~60 % free space).
      3. Verify it exists.
      4. Call nvme.delete_all_ns.
      5. Verify no namespaces remain.


Expected Results
----------------
PASS   : Namespace create / delete operations succeed; all namespaces
         are visible and accessible as block devices after creation, and
         absent after deletion.
CANCEL : Device does not exist, does not support namespace management,
         has insufficient free space, or a required build step failed.
FAIL   : A namespace is absent after creation, still present after
         deletion, or its block device path is not accessible.

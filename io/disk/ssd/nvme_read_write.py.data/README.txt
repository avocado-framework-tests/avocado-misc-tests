NVMe Read / Write Tests
=======================

Source file : io/disk/ssd/nvme_read_write.py
Config file : io/disk/ssd/nvme_read_write.py.data/nvme_read_write.yaml
Author      : Naresh Bannoth <nbannoth@in.ibm.com>
Copyright   : 2026 IBM


Overview
--------
Exercises the core NVMe I/O command set against a single namespace on a
target controller using nvme-cli.  The namespace is discovered
automatically at runtime by querying the controller — no manual namespace
ID is required in the configuration.

Tests cover:
  - Basic read (nvme read)
  - Read at a non-zero LBA offset (--start-block)
  - Multi-block read (--block-count)
  - Read with Force-Unit-Access / FUA (--force-unit-access)
  - Read to a file (--data)
  - Basic write (nvme write)
  - Write at a non-zero LBA offset (--start-block)
  - Multi-block write (--block-count)
  - Write with Force-Unit-Access / FUA (--force-unit-access)
  - Write from a file (--data)
  - Flush (nvme flush)
  - Write-Zeroes (nvme write-zeroes) — skipped if device does not support it
  - Write-Uncorrectable (nvme write-uncor) — skipped if device does not
    support it

Each test validates namespace accessibility before issuing I/O and checks
the nvme-cli return code after every command.


Prerequisites
-------------
- An NVMe controller visible to the OS (e.g. /dev/nvme0).
- At least one namespace present on that controller.
- nvme-cli installed (distro package) or internet access to build upstream.
- Root / sudo privileges.
- meson (only required when package=upstream).


Configuration (nvme_read_write.yaml)
-------------------------------------
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

    avocado run nvme_read_write.py \
        -p device=nvme0

Run only the distro-nvme-cli variant:

    avocado run nvme_read_write.py \
        -p device=nvme0 \
        -p package=distro

Run a single test:

    avocado run nvme_read_write.py:NVMeReadWrite.test_read \
        -p device=nvme0

Run with a multipath (shared) namespace:

    avocado run nvme_read_write.py \
        -p device=nvme0 \
        -p shared_namespaces=True


Test Details
------------
test_read
    Issues: nvme read <ns> -z <block_size> -t
    Reads one block from LBA 0 and verifies exit code 0.

test_read_start_block
    Issues: nvme read <ns> -s 1 -z <block_size> -t
    Reads one block starting at LBA 1.

test_read_block_count
    Issues: nvme read <ns> -c 3 -z <block_size*4> -t
    Reads 4 blocks (0-based count=3) in a single command.

test_read_force_unit_access
    Issues: nvme read <ns> -z <block_size> -f -t
    Reads bypassing the volatile cache (FUA bit set).

test_read_to_file
    Issues: nvme read <ns> -z <block_size> -d <tmpfile> -t
    Reads one block into a temporary file; verifies the file is non-empty.

test_write
    Issues: echo 1 | nvme write <ns> -z <block_size> -t
    Writes one block of data from stdin.

test_write_start_block
    Issues: echo 1 | nvme write <ns> -s 1 -z <block_size> -t
    Writes one block starting at LBA 1.

test_write_block_count
    Issues: echo 1 | nvme write <ns> -c 3 -z <block_size*4> -t
    Writes 4 blocks in a single command.

test_write_force_unit_access
    Issues: echo 1 | nvme write <ns> -z <block_size> -f -t
    Writes with FUA, committing data to non-volatile storage before
    signalling completion.

test_write_from_file
    Creates a temporary file filled with 0xAB bytes (one block).
    Issues: nvme write <ns> -z <block_size> -d <tmpfile> -t

test_flush
    Issues: nvme flush <ns>
    Flushes the namespace / controller cache.

test_write_zeroes
    Skipped if 'Write Zeroes Supported' is absent from id-ctrl.
    Issues: nvme write-zeroes <ns>
    Reads back one block after completion to confirm the command succeeded.

test_write_uncorrectable
    Skipped if 'Write Uncorrectable Supported' is absent from id-ctrl.
    Issues: nvme write-uncor <ns>

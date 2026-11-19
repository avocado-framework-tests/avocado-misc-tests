#!/usr/bin/env python
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
# Copyright: 2026 IBM
# Author: Krishan Gopal Saraswat <krishang@linux.ibm.com>

"""
PReP Boot Partition & grub2-install tests.

Requires ppc64le, a PReP partition, and root privileges.
"""

import os
import re
from avocado import Test
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


def _find_prep_partition():
    """Return the first PReP partition path on any LPAR disk, or None.

    Uses ``parted -lm`` which reports the ``prep`` flag regardless of
    the underlying disk type (NVMe, SAS, virtio-blk, …) or partition
    table scheme.  Output format per partition line:
        <num>:<start>:<end>:<size>:<fs>:<name>:<flags>;
    """
    result = process.run(
        'parted -lm 2>/dev/null', shell=True, ignore_status=True, sudo=True,
    )
    disk = None
    for line in result.stdout_text.splitlines():
        line = line.strip().rstrip(';')
        if line.startswith('/dev/'):
            disk = line.split(':')[0]
        elif disk and 'prep' in line.split(':')[-1]:
            part_num = line.split(':')[0]
            if part_num.isdigit():
                # Reconstruct the device node: /dev/sda1, /dev/nvme0n1p1, etc.
                if re.search(r'\d$', disk):
                    return f'{disk}p{part_num}'
                return f'{disk}{part_num}'
    return None


class GrubPrepInstallTest(Test):
    """
    grub2-install smoke tests for the PReP boot partition on ppc64le.

    :avocado: tags=grub,powerpc,prep,install
    """

    def setUp(self):
        sm = SoftwareManager()
        for pkg in ('grub2', 'grub2-tools', 'util-linux', 'parted'):
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.cancel(f'Required package {pkg!r} could not be installed.')

        self.prep_dev = _find_prep_partition()
        if self.prep_dev is None:
            self.cancel('No PReP partition found on this system.')

    def _run(self, cmd, expect_pass=True):
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True)
        if expect_pass:
            self.assertEqual(
                result.exit_status, 0,
                f'Command failed (exit {result.exit_status}): {cmd}\n'
                f'{result.stderr_text.strip()}',
            )
        else:
            self.assertNotEqual(
                result.exit_status, 0,
                f'Command unexpectedly succeeded: {cmd}',
            )
        return result

    def test_t01_install_to_prep_partition(self):
        """
        T-01: grub2-install targeting the PReP partition must exit 0
        and report "Installation finished. No error reported."
        """
        result = self._run(f'grub2-install {self.prep_dev}')
        self.assertIn(
            'Installation finished. No error reported.',
            result.stdout_text + result.stderr_text,
            'Success message not found in grub2-install output.',
        )

    def test_t02_install_with_explicit_boot_directory(self):
        """
        T-02: --boot-directory=/boot must produce the same successful
        result as the default invocation.
        """
        result = self._run(
            f'grub2-install --boot-directory=/boot {self.prep_dev}'
        )
        self.assertIn(
            'Installation finished. No error reported.',
            result.stdout_text + result.stderr_text,
            'Success message not found when --boot-directory=/boot is used.',
        )

    def test_t03_install_with_restricted_modules(self):
        """
        T-03: --install-modules="linux btrfs part_gpt" must succeed and
        produce a non-empty core.elf.
        """
        self._run(
            f'grub2-install --install-modules="linux btrfs part_gpt" '
            f'{self.prep_dev}'
        )
        core_elf = '/boot/grub2/powerpc-ieee1275/core.elf'
        stat_result = self._run(f'stat -c "%s" {core_elf}')
        self.assertGreater(
            int(stat_result.stdout_text.strip()), 0,
            f'{core_elf} is empty after restricted-module install.',
        )

    def test_t04_bootinfo_txt_content(self):
        """
        T-04: bootinfo.txt must contain <chrp-boot> and powerpc.elf.
        """
        bootinfo = process.run(
            'find /usr -name bootinfo.txt -path "*/powerpc-ieee1275/*" '
            '-print -quit',
            shell=True, ignore_status=True, sudo=True,
        ).stdout_text.strip()
        if not bootinfo:
            self.cancel('bootinfo.txt not found under /usr for powerpc-ieee1275.')
        self._run(f'test -f {bootinfo}')
        content = self._run(f'cat {bootinfo}').stdout_text
        self.assertIn('<chrp-boot>', content,
                      f'<chrp-boot> tag not found in {bootinfo}')
        self.assertIn('powerpc.elf', content,
                      f'powerpc.elf reference not found in {bootinfo}')

    def test_t05_install_to_nonexistent_disk(self):
        """
        T-05: A non-existent device must cause grub2-install to exit
        non-zero with an error message.
        """
        result = self._run('grub2-install /dev/nonexistentdisk',
                           expect_pass=False)
        self.assertIn(
            'error',
            (result.stdout_text + result.stderr_text).lower(),
            'Expected an error message for a non-existent device.',
        )

    def test_t06_core_elf_is_elf32_msb_powerpc(self):
        """
        T-06: core.elf must be an ELF 32-bit MSB PowerPC binary.
        """
        core_elf = '/boot/grub2/powerpc-ieee1275/core.elf'
        if not os.path.exists(core_elf):
            self._run(f'grub2-install {self.prep_dev}')
        file_output = self._run(f'file {core_elf}').stdout_text.strip()
        for marker in ('ELF 32-bit', 'MSB', 'PowerPC'):
            self.assertIn(
                marker, file_output,
                f'Expected "{marker}" in `file` output; got: {file_output}',
            )

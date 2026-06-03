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
# Copyright: 2018 IBM
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#

import os
import re

from avocado import Test
from avocado.utils import process, build, archive, genio, distro
from avocado.utils.software_manager.manager import SoftwareManager


class Blktests(Test):
    '''
    Blktests blktests is a test framework for the Linux kernel block layer
    and storage stack. It is inspired by the xfstests filesystem testing framework.

    :avocado: tags=fs
    '''

    def setUp(self):
        '''
        Setup Blktests
        '''
        self.disk = self.params.get('disk', default='')
        self.dev_type = self.params.get('type', default='')
        self.disk = self.disk.split(' ')
        smm = SoftwareManager()
        dist = distro.detect()

        packages = ['gcc', 'make', 'util-linux', 'fio']
        if dist.name in ['Ubuntu', 'debian']:
            packages += ['libdevmapper-dev', 'g++']
        elif dist.name in ['rhel', 'CentOS', 'fedora']:
            packages += ['device-mapper', 'gcc-c++', 'blktrace',
                         'ktls-utils', 'device-mapper-multipath']
        elif dist.name in ['SuSE']:
            packages += ['device-mapper', 'gcc-c++', 'blktrace',
                         'ktls-utils', 'multipath-tools']

        # Enable io_uring if disabled
        knob = "/proc/sys/kernel/io_uring_disabled"
        if os.path.exists(knob):
            try:
                current = int(process.system_output(f"cat {knob}").strip())
                # 0 = enabled, 1/2 = disabled
                if current != 0:
                    process.run(f"echo 0 > {knob}", sudo=True, shell=True)
            except Exception as ex:
                self.log.warn(f"Could not update io_uring_disabled: {ex}")
        else:
            self.log.info("io_uring_disabled knob not present older kernel")

        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(package + ' is needed for the test to be run')

        # Download/build blktests
        locations = ["https://github.com/osandov/blktests/archive/"
                     "master.zip"]
        tarball = self.fetch_asset("blktests.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'blktests-master')
        build.make(self.sourcedir)

    def test(self):
        self.clear_dmesg()
        os.chdir(self.sourcedir)

        genio.write_one_line("/proc/sys/kernel/hung_task_timeout_secs", "0")
        for disk in self.disk:
            os.environ['TEST_DEVS'] = ' '.join(self.disk)
        cmd = './check %s' % self.dev_type
        result = process.run(cmd, ignore_status=True, verbose=True)

        stdout = result.stdout.decode(errors="ignore")
        fail_pattern = re.compile(r'^(\S+/\S+).*?\[failed\]', re.MULTILINE)
        failed_tests = [m.group(1).strip() for m in fail_pattern.finditer(stdout)]

        if result.exit_status != 0 or failed_tests:
            if failed_tests:
                failed_list = ", ".join(failed_tests)
                summary = f"{len(failed_tests)} test(s) failed: {failed_list}"
            else:
                summary = f"blktests exited with code {result.exit_status}"
            self.fail(summary)

        dmesg = process.system_output('dmesg')
        match = re.search(br'Call Trace:', dmesg, re.M | re.I)
        if match:
            self.fail("some call traces seen please check")

    def clear_dmesg(self):
        process.run("dmesg -C", sudo=True)

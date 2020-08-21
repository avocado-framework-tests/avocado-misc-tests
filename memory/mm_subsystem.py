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
#
# Copyright: 2020 IBM
# Author: Harish <harish@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import build
from avocado.utils import memory
from avocado.utils import process
from avocado.utils import git
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class MmSubsystemTest(Test):
    '''
    Memory subsystem functional test

    :avocado: tags=memory
    '''
    @staticmethod
    def clear_dmesg():
        process.run("dmesg -C", sudo=True)

    @staticmethod
    def check_dmesg():
        errorlog = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                    'ard LOCKUP', 'Unable to handle paging request',
                    'rcu_sched detected stalls', 'NMI backtrace for cpu']
        err = []
        logs = process.system_output("dmesg -Txl 1,2,3,4"
                                     "").decode("utf-8").splitlines()
        for error in errorlog:
            for log in logs:
                if error in log:
                    err.append(log)
        return "\n".join(err)

    def setUp(self):
        """
        Build binary and filter tests based on the environment
        """
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'patch']
        detected_distro = distro.detect()
        if detected_distro.name in ["Ubuntu", 'debian']:
            deps.extend(['libpthread-stubs0-dev', 'git'])
        elif detected_distro.name == "SuSE":
            deps.extend(['glibc-devel-static', 'git-core'])
        else:
            deps.extend(['glibc-static', 'git', 'runc'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        git.get_repo("https://gitlab.com/cailca/linux-mm",
                     destination_dir=self.logdir)
        os.chdir(self.logdir)
        build.make(self.logdir)
        tst_list = process.system_output('./random -l').decode().splitlines()
        self.test_dic = {}
        for line in tst_list:
            keyval = line.split(":")
            self.test_dic[keyval[0]] = keyval[1]
        skip_numa = False
        if len(memory.numa_nodes_with_memory()) < 2:
            skip_numa = True
        rm_dic = []
        for key, val in self.test_dic.items():
            if skip_numa:
                if 'NUMA' in val or 'migrate' in val:
                    rm_dic.append(key)
            if detected_distro.name == "SuSE":
                if 'runc' in val:
                    rm_dic.append(key)

        for item in rm_dic:
            self.test_dic.pop(item)

    def test(self):
        """
        Run filtered tests sequentially
        """
        failed = []
        fail_msg = []
        self.log.info("Tests to be run are %s", self.test_dic)
        for cnt in list(self.test_dic.keys()):
            self.clear_dmesg()
            if process.system("./random %s" % cnt, ignore_status=True):
                failed.append(cnt)

            msg = self.check_dmesg()
            if msg:
                fail_msg.append('Test: %s (%s) failed with %s '
                                'message' % (cnt, self.test_dic[cnt], msg))

        if failed or fail_msg:
            self.log.info('ERROR in dmesg:  %s', fail_msg)
            self.log.info('Tests failed:  %s', failed)
            self.fail('Test failed, please check above for failures')

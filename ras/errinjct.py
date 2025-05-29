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
# Copyright: 2021 IBM
# Author: Shirisha Ganta <shirisha.ganta1@ibm.com>

from avocado import Test
from avocado.utils import process, genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado import skipIf

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class Errinjct(Test):
    """
    :avocado: tags=privileged
    """
    """
    The errinjct tool enables RTAS to inject errors on a Power system.
    Currently, errinjct is only supported on PowerVM systems.
    """
    fail_cmd = list()

    def run_cmd(self, cmd):
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.fail_cmd.append(cmd)
        return

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True,
                                     sudo=True).decode("utf-8").strip()

    @skipIf(IS_POWER_NV, "This test is supported on PowerVM environment")
    def setUp(self):
        sm = SoftwareManager()
        if not sm.check_installed("powerpc-utils") and \
           not sm.install("powerpc-utils"):
            self.cancel("Fail to install required 'powerpc-utils' package")

    def test_errinjct(self):
        self.log.info("===Executing errinjct tool====")
        # Equivalent Python code for bash command
        # errinjct open| awk -F '=' '{print $2}'
        output = self.run_cmd_out("errinjct open")
        token_flag = False
        for line in output.splitlines():
            if 'token' in line:
                token = line.split("=")[1].strip()
                token_flag = True
        if not token_flag:
            self.cancel("Can't open RTAS error injection facility.")
        runcmd = self.params.get('runcmd', default='corrupted-dcache-start')
        run_option = self.params.get(
            'run_option', default='-a 0 -C 0 --dry-run')
        self.run_cmd("errinjct %s %s -k %s" % (runcmd, run_option, token))
        self.run_cmd("errinjct close -k %s" % token)
        if self.fail_cmd:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

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
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager

class Ras_tools(Test):
    """
    :avocado: tags=privileged
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

    def setUp(self):
        sm = SoftwareManager()
        deps = ["ppc64-diag", "powerpc-utils"]
        for pkg in deps:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.cancel("Fail to install %s required for this test." %
                            pkg)

    def test1_nvsetenv(self):
        self.log.info("===Executing nvsetenv tool====")
        self.run_cmd("nvsetenv")
        value = self.params.get('nvsetenv_list', default=['load-base', 'load-base 7000'])
        for list_item in value:
            self.run_cmd('nvsetenv  %s ' % list_item )
        if self.fail_cmd:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

    def test2_usysattn(self):
        self.log.info("=====Executing usysattn tool test======")
        value = self.params.get('usysattn_list', default=['-h', '-V', '-P'])
        for list_item in value:
            self.run_cmd('usysattn  %s ' % list_item )
        loc_code = self.run_cmd_out("usysattn -P| awk '{print $1}'")
        self.run_cmd("usysattn -l %s -s normal -t" % loc_code)
        if self.fail_cmd:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

    def test3_usysfault(self):
        self.log.info("======Executing usysfault tool test======")
        value = self.params.get('usysfault_list', default=['-h', '-V', '-P'])
        for list_item in value:
            self.run_cmd('usysfault  %s ' % list_item )
        loc_code = self.run_cmd_out("usysfault -P | awk '{print $1}'")
        self.run_cmd("usysfault -l %s -s normal -t" % loc_code)
        if self.fail_cmd:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

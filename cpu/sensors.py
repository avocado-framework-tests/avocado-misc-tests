#! /usr/bin/env python

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
# Copyright: 2016 IBM
# Author: Harish <harisrir@linux.vnet.ibm.com>
#

"""
Test for sensors command
"""
from avocado import Test
from avocado import main
from avocado.utils import process, linux_modules
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import cpu

# TODO: Add possible errors of sensors command
ERRORS = ['I/O error']


class Sensors(Test):

    """
    Test covers  various command input of sensors utility(Linux monitoring sensors)

    :avocado: tags=cpu,privileged
    """

    @staticmethod
    def check_errors(cmd):
        """
        Checks any errors in command result
        """
        errs = []
        s_output = process.run(cmd, ignore_status=True).stderr.decode("utf-8")
        for error in ERRORS:
            if error in s_output:
                errs.append(error)
        return errs

    def setUp(self):
        """
        Check pre-requisites before running sensors command
        Testcase should be executed only on bare-metal environment.
        """
        s_mg = SoftwareManager()
        d_distro = distro.detect()
        if d_distro.arch in ["ppc64", "ppc64le"]:
            if not cpu._list_matches(open('/proc/cpuinfo').readlines(),
                                     'platform\t: PowerNV\n'):
                self.cancel(
                    'sensors test is applicable to bare-metal environment.')
        if d_distro.name == "Ubuntu":
            if not s_mg.check_installed("lm-sensors") and not s_mg.install(
                    "lm-sensors"):
                self.cancel('Need sensors to run the test')
        elif d_distro.name == "SuSE":
            if not s_mg.check_installed("sensors") and not s_mg.install(
                    "sensors"):
                self.cancel('Need sensors to run the test')
        else:
            if not s_mg.check_installed("lm_sensors") and not s_mg.install(
                    "lm_sensors"):
                self.cancel('Need sensors to run the test')
            config_check = linux_modules.check_kernel_config(
                'CONFIG_SENSORS_IBMPOWERNV')
            if config_check == linux_modules.ModuleConfig.NOT_SET:
                self.cancel('Config is not set')
            elif config_check == linux_modules.ModuleConfig.MODULE:
                if linux_modules.load_module('ibmpowernv'):
                    if linux_modules.module_is_loaded('ibmpowernv'):
                        self.log.info('Module Loaded Successfully')
                    else:
                        self.cancel('Module Loading Failed')
            else:
                self.log.info('Module is Built In')

        if not d_distro.name == "Ubuntu":
            try:
                process.run('service lm_sensors stop', sudo=True)
                process.run('service lm_sensors start', sudo=True)
                process.run('service lm_sensors status', sudo=True)
            except process.CmdError:
                self.error(
                    'Starting Service Failed. Make sure module is loaded')
        cmd = "yes | sudo sensors-detect"
        det_op = process.run(cmd, shell=True, ignore_status=True).stdout
        if b'no sensors were detected' in det_op:
            self.cancel('No sensors found to test !')

    def test(self):
        """
        Test for sensors command
        """

        error_list = self.check_errors('sensors')
        if len(error_list) > 0:
            self.fail('sensors command failed with %s' % error_list)
        error_list = self.check_errors('sensors -f')
        if len(error_list) > 0:
            self.fail('sensors -f command failed with %s' % error_list)
        error_list = self.check_errors('sensors -A')
        if len(error_list) > 0:
            self.fail('sensors -A command failed with %s' % error_list)
        error_list = self.check_errors('sensors -u')
        if len(error_list) > 0:
            self.fail('sensors -u command failed with %s' % error_list)


if __name__ == "__main__":
    main()

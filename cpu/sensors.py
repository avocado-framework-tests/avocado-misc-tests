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
import platform

from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager

# TODO: Add possible errors of sensors command
ERRORS = ['I/O error']


class Sensors(Test):

    """
    Run sensors command on ppc architectures.
    """

    @staticmethod
    def check_errors(cmd):
        """
        Checks any errors in command result
        """
        errs = []
        s_output = process.run(cmd, ignore_status=True).stderr
        for error in ERRORS:
            if error in s_output:
                errs.append(error)
        return errs

    def setUp(self):
        """
        Check pre-requisites before running sensors command
        """
        s_mg = SoftwareManager()
        d_distro = distro.detect()
        if d_distro.name == "Ubuntu":
            if not s_mg.check_installed("lm-sensors") and not s_mg.install(
                    "lm-sensors"):
                self.error('Need sensors to run the test')
        else:
            if not s_mg.check_installed("lm_sensors") and not s_mg.install(
                    "lm_sensors"):
                self.error('Need sensors to run the test')
        if d_distro.arch in ["ppc64", "ppc64le"]:
            kernel_ver = platform.uname()[2]
            l_config = "CONFIG_SENSORS_IBMPOWERNV"
            config_op = process.system_output(
                'cat /boot/config-' + kernel_ver +
                '| grep -i --color=never ' + l_config, shell=True)
            if "=" not in config_op:
                self.error('Config is not set')
            c_val = (config_op.split("=")[1]).replace('\n', '')
            if "powerkvm" in d_distro.name:
                if not c_val == "y":
                    self.error('Config is not set properly')
                else:
                    self.log.info("Driver will be part of distro")
            else:
                if not c_val == "m":
                    self.error('Config is not set correctly')
                else:
                    self.log.info("Driver will be built as module")
                    mod_op = process.run(
                        'modprobe ibmpowernv')
                    if mod_op.exit_status == 0:
                        lsmod_op = process.system_output(
                            "lsmod | grep -i ibmpowernv", shell=True)
                        if "ibmpowernv" not in lsmod_op:
                            self.error('Module Loading Failed')
                        else:
                            self.log.info('Module Loaded Successfully')
        if not d_distro.name == "Ubuntu":
            try:
                process.run('service lm_sensors stop', sudo=True)
                process.run('service lm_sensors start', sudo=True)
                process.run('service lm_sensors status', sudo=True)
            except process.CmdError:
                self.error(
                    'Starting Service Failed. Make sure module is loaded')
        det_op = process.run('yes | sudo sensors-detect', shell=True, ignore_status=True).stdout
        if 'no sensors were detected' in det_op:
            self.skip('No sensors found to test !')

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

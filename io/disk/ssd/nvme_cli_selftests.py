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
# Copyright: 2017 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
NVM-Express user space tooling for Linux, which handles NVMe devices.
"""

import os
import pkgutil
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import archive
from avocado.utils.software_manager import SoftwareManager


class NVMeCliSelfTest(Test):

    """
    nvme-cli seltests.

    :param device: Name of the nvme device
    :param disk: Name of the nvme namespace
    :param test: Name of the test
    """

    def setUp(self):
        """
        Download 'nvme-cli'.
        """
        self.device = self.params.get('device', default='nvme0')
        self.device = "/dev/%s" % self.device
        self.disk = self.params.get('disk', default='/dev/nvme0n1')
        self.test = self.params.get('test', default='')
        if not self.test:
            self.cancel('no test specified in yaml')
        cmd = 'ls %s' % self.device
        if process.system(cmd, ignore_status=True):
            self.cancel("%s does not exist" % self.device)
        smm = SoftwareManager()
        if not smm.check_installed("nvme-cli") and not \
                smm.install("nvme-cli"):
            self.cancel('nvme-cli is needed for the test to be run')
        py_pkgs = ['nose', 'nose2', 'pep8', 'flake8', 'pylint', 'epydoc']
        installed_py_pkgs = [pkg[1] for pkg in list(pkgutil.iter_modules())]
        py_pkgs_not_installed = list(set(py_pkgs) - set(installed_py_pkgs))
        if py_pkgs_not_installed:
            self.cancel("python packages %s not installed" %
                        ", ".join(py_pkgs_not_installed))
        url = 'https://codeload.github.com/linux-nvme/nvme-cli/zip/master'
        tarball = self.fetch_asset("nvme-cli-master.zip", locations=[url],
                                   expire='7d')
        archive.extract(tarball, self.teststmpdir)
        self.nvme_dir = os.path.join(self.teststmpdir, "nvme-cli-master")
        os.chdir(os.path.join(self.nvme_dir, 'tests'))
        msg = ['{']
        msg.append('    \"controller\": \"%s\",' % self.device)
        msg.append('    \"ns1\": \"%s\",' % self.disk)
        msg.append('    \"log_dir\": \"%s\"' % self.outputdir)
        msg.append('}')
        with open('config.json', 'w') as config_file:
            config_file.write("\n".join(msg))

    def test_selftests(self):
        """
        Runs the selftests on the device.
        """
        res = process.run("nose2 --verbose %s" %
                          self.test, shell=True, ignore_status=True)
        res = [res.stdout.decode("utf-8"), res.stderr.decode("utf-8")]
        if any('FAILED' in line for line in res):
            self.fail("Test Failed")


if __name__ == "__main__":
    main()

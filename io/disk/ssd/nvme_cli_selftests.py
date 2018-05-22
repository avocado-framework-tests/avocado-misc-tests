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
import pip
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager


class NVMeCliSelfTest(Test):

    """
    nvme-cli seltests.

    :param device: Name of the nvme device
    :param disk: Name of the nvme namespace
    """

    def setUp(self):
        """
        Download 'nvme-cli'.
        """
        self.device = self.params.get('device', default='/dev/nvme0')
        self.disk = self.params.get('disk', default='/dev/nvme0n1')
        cmd = 'ls %s' % self.device
        if process.system(cmd, ignore_status=True) is not 0:
            self.cancel("%s does not exist" % self.device)
        smm = SoftwareManager()
        if not smm.check_installed("nvme-cli") and not \
                smm.install("nvme-cli"):
            self.cancel('nvme-cli is needed for the test to be run')
        python_packages = pip.get_installed_distributions()
        python_packages_list = [i.key for i in python_packages]
        python_pkgs = ['nose', 'nose2', 'pep8', 'flake8', 'pylint', 'epydoc']
        for py_pkg in python_pkgs:
            if py_pkg not in python_packages_list:
                self.cancel("python package %s not installed" % py_pkg)
        url = 'https://codeload.github.com/linux-nvme/nvme-cli/zip/master'
        tarball = self.fetch_asset("nvme-cli-master.zip", locations=[url],
                                   expire='7d')
        archive.extract(tarball, self.teststmpdir)
        self.nvme_dir = os.path.join(self.teststmpdir, "nvme-cli-master")
        print os.listdir(self.nvme_dir)
        os.chdir(os.path.join(self.nvme_dir, 'tests'))
        msg = ['{']
        msg.append('    \"controller\": \"%s\",' % self.device)
        msg.append('    \"ns1\": \"%s\",' % self.disk)
        msg.append('    \"log_dir\": \"%s\"' % self.outputdir)
        msg.append('}')
        with open('config.json', 'w') as config_file:
            config_file.write("\n".join(msg))
        process.system("cat config.json")

    def test_selftests(self):
        """
        Runs the selftests on the device.
        """
        err = []
        for line in build.run_make(os.path.join(self.nvme_dir, 'tests'),
                                   extra_args='run',
                                   process_kwargs={'ignore_status': True}
                                   ).stderr.splitlines():
            if 'FAIL:' in line:
                err.append(line.split('.')[1])
        self.fail("Some tests failed. Details below:\n%s" % "\n".join(err))


if __name__ == "__main__":
    main()

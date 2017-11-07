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
# Author: sudeesh john <sudeesh@linux.vnet.ibm.com>

import os
from avocado import Test, main
from avocado.utils import build, git, process
from avocado.utils.software_manager import SoftwareManager


class Cxl(Test):
    """
    This tests the CAPI functionality in IBM Power machines.
    This wrapper uses the testcases from
    https://github.com/ibm-capi/cxl-tests.git
    """

    def setUp(self):
        """
        Preparing the machie for the cxl test
        """
        self.script = self.params.get('script', default='memcpy_afu_ctx')
        self.args = self.params.get('args', default='')
        lspci_out = process.system_output("lspci")
        if "accelerators" not in lspci_out:
            self.cancel("No capi card preset. Unable to initialte the test")
        smngr = SoftwareManager()
        for pkgs in ['gcc', 'make', 'automake', 'autoconf']:
            if not smngr.check_installed(pkgs) and not smngr.install(pkgs):
                self.cancel('%s is needed for the test to be run' % pkgs)
        git.get_repo('https://github.com/ibm-capi/cxl-tests.git',
                     destination_dir=self.teststmpdir)
        os.chdir(self.teststmpdir)
        if not os.path.isfile('memcpy_afu_ctx'):
            build.make(".")

    def test(self):
        """
        Runs the cxl tests.
        """
        cmd = "./%s  %s" % (self.script, self.args)
        result = process.run(cmd, ignore_status=True)
        if "Unable to open cxl device" in result.stderr:
            self.fail("%s is failed" % cmd)
        elif "failed" in result.stdout:
            self.fail("%s is failed" % cmd)


if __name__ == "__main__":
    main()

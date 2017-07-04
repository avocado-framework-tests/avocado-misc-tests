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
# Copyright: 2016 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>


"""
This test script is intended to give a block-level based overview of
SSD performance.
"""

import os
from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process
from avocado.utils import genio
from avocado.utils.software_manager import SoftwareManager
import avocado.utils.git as git


class EzfioTest(Test):

    """
    This test script is intended to give a block-level based overview of
    SSD performance. Uses FIO to perform the actual IO tests.
    Places the output files in avocado test's outputdir.

    :param device: Name of the ssd block device
    """

    def setUp(self):
        """
        Build 'fio and ezfio'.
        """
        self.disk = self.params.get('disk', default='/dev/nvme0n1')
        cmd = 'ls %s' % self.disk
        if process.system(cmd, ignore_status=True) is not 0:
            self.cancel("%s does not exist" % self.disk)
        fio_path = os.path.join(self.teststmpdir, 'fio')
        fio_link = 'https://github.com/axboe/fio.git'
        git.get_repo(fio_link, destination_dir=fio_path)
        build.make(fio_path, make='./configure')
        build.make(fio_path)
        build.make(fio_path, extra_args='install')
        self.ezfio_path = os.path.join(self.teststmpdir, 'ezfio')
        ezfio_link = 'https://github.com/earlephilhower/ezfio.git'
        git.get_repo(ezfio_link, destination_dir=self.ezfio_path)
        self.utilization = self.params.get('utilization', default='100')
        # aio-max-nr is 65536 by default, and test fails if QD is 256 or above
        genio.write_file("/proc/sys/fs/aio-max-nr", "1048576")
        smm = SoftwareManager()
        # Not a package that must be installed, so not skipping.
        if not smm.check_installed("sdparm") and not smm.install("sdparm"):
            self.log.debug("Can not install sdparm")
        self.cwd = os.getcwd()

    def test(self):
        """
        Performs ezfio test on the block device'.
        """
        os.chdir(self.ezfio_path)
        cmd = './ezfio.py -d %s -o "%s" -u %s --yes' \
            % (self.disk, self.outputdir, self.utilization)
        process.run(cmd, shell=True)

    def tearDown(self):
        """
        Clean up
        """
        os.chdir(self.cwd)


if __name__ == "__main__":
    main()

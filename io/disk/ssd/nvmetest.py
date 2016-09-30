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
NVM-Express user space tooling for Linux, which handles NVMe devices.
This Suite creates and formats a namespace, reads and writes on it
using nvme cli.
"""

import os
from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process
import avocado.utils.git as git


class NVMeTest(Test):

    """
    NVM-Express user space tooling for Linux, which handles NVMe devices.

    :param device: Name of the nvme device
    """

    def setUp(self):
        """
        Build 'nvme-cli' and setup the device.
        """
        self.device = self.params.get('device', default='/dev/nvme0')
        cmd = 'ls %s' % self.device
        if process.system(cmd, ignore_status=True) is not 0:
            self.skip("%s does not exist" % self.device)
        nvme_path = os.path.join(self.srcdir, 'nvme')
        nvme_link = 'https://github.com/linux-nvme/nvme-cli.git'
        git.get_repo(nvme_link, destination_dir=nvme_path)
        build.make(nvme_path)
        build.make(nvme_path, extra_args='install')
        self.id_ns = self.create_namespace()
        self.log.info(self.id_ns)
        cmd = "nvme id-ns %s | grep 'in use' | awk '{print $5}' | \
            awk -F':' '{print $NF}'" % self.id_ns
        self.format_size = process.system_output(cmd, shell=True).strip('\n')
        self.format_size = pow(2, int(self.format_size))
        cmd = "nvme id-ns %s | grep 'in use' | awk '{print $2}'" % self.id_ns
        self.lba = process.system_output(cmd, shell=True).strip('\n')
        self.format_namespace()

    def create_namespace(self):
        """
        Creates namespace on the device.
        """
        cmd = "nvme show-regs %s | grep version | awk '{print $NF}'" \
            % self.device
        if int(process.system_output(cmd, shell=True).strip('\n')) < 10200:
            return self.device + 'n1'
        cmd = 'nvme create-ns %s' % self.device
        process.run(cmd, shell=True)
        # TODO: retrieve the created namespace for nvme spec 1.2 and above
        return self.device + 'n1'

    def delete_namespace(self):
        """
        Deletes namespace on the device.
        """
        cmd = "nvme show-regs %s | grep version | awk '{print $NF}'" \
            % self.device
        if int(process.system_output(cmd, shell=True).strip('\n')) < 10200:
            return
        cmd = 'nvme delete-ns %s' % self.device
        process.run(cmd, shell=True)

    def format_namespace(self):
        """
        Formats the namespace on the device.
        """
        cmd = 'nvme format %s -l %s' % (self.id_ns, self.lba)
        process.run(cmd, shell=True)

    def testread(self, data=None):
        """
        Reads from the namespace on the device.
        """
        cmd = 'nvme read %s -z %d -t' % (self.id_ns, self.format_size)
        if data != None:
            cmd += ' | grep -w %s' % data
        if process.system(cmd, timeout=300, ignore_status=True, shell=True):
            self.fail("Read failed")

    def testwrite(self):
        """
        Write to the namespace on the device.
        """
        cmd = 'echo 1|nvme write %s -z %d -t' % (self.id_ns, self.format_size)
        if process.system(cmd, timeout=300, ignore_status=True, shell=True):
            self.fail("Write failed")
        self.testread()
        self.testread(data="1")

    def tearDown(self):
        """
        Clean up
        """
        self.delete_namespace()

if __name__ == "__main__":
    main()

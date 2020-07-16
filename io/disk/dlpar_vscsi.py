#!/usr/bin/python

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
# Author: Bismruti Bidhibrata Pattjoshi<bbidhibr@in.ibm.com>

"""
DLPAR operations
"""

from avocado import Test
from avocado.utils import process
from avocado.utils.ssh import Session


class DlparTest(Test):
    '''
    DLPAR disk script does vscsi device add,remove.
    Update the details in yaml file.
    '''

    def setUp(self):
        '''
        Gather necessary test inputs.
        '''
        self.disk = self.params.get('disk', default=None)
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        self.vios_ip = self.params.get('vios_ip', '*', default=None)
        self.vios_user = self.params.get('vios_username', '*', default=None)
        self.vios_pwd = self.params.get('vios_pwd', '*', default=None)
        self.session = Session(self.vios_ip, user=self.vios_user,
                               password=self.vios_pwd)
        self.session.connect()
        cmd = "lscfg -l %s" % self.disk
        for line in process.system_output(cmd, shell=True).decode("utf-8") \
                                                          .splitlines():
            if self.disk in line:
                self.slot = line.split()[-1].split('-')[-2]
        cmd = "ioscli lsdev -slots"
        output = self.session.cmd(cmd)
        for line in output.stdout_text.splitlines():
            if self.slot in line:
                self.host = line.split()[-1]
        self.log.info(self.host)
        cmd = "lsscsi -vl"
        output = process.system_output(cmd, shell=True)
        for line in output.decode("utf-8").splitlines():
            if self.disk in line:
                value = line.split()[0].replace('[', '').replace(']', '')
        for line in output.decode("utf-8").splitlines():
            if value in line:
                if "dir" in line:
                    self.disk_dir = line.split()[-1].replace('[', '') \
                                                    .replace(']', '')
        cmd = r"cat %s/inquiry" % self.disk_dir
        output = process.system_output(cmd, shell=True)
        self.hdisk_name = output.split()[2].strip(b'0001').decode("utf-8")
        self.log.info(self.hdisk_name)
        cmd = "ioscli lsmap -all|grep -p %s" % self.hdisk_name
        output = self.session.cmd(cmd)
        for line in output.stdout_text.splitlines():
            if "VTD" in line:
                self.vscsi = line.split()[-1]
        if not self.vscsi:
            self.cancel("failed to get vscsi")
        self.log.info(self.vscsi)

    def dlpar_remove(self):
        '''
        dlpar remove operation
        '''
        cmd = "ioscli rmvdev -vdev %s" % self.hdisk_name
        output = self.session.cmd(cmd)
        self.log.info(output.stdout_text)
        if output.exit_status != 0:
            self.fail("failed dlpar remove operation")

    def dlpar_add(self):
        '''
        dlpar add operation
        '''
        cmd = "ioscli mkvdev -vdev %s -vadapter %s -dev %s" % (self.hdisk_name,
                                                               self.host,
                                                               self.vscsi)
        output = self.session.cmd(cmd)
        self.log.info(output.stdout_text)
        if output.exit_status != 0:
            self.fail("Failed dlpar add operation")

    def test_dlpar(self):
        '''
        vscsi dlpar remove and add operation
        '''
        for _ in range(self.num_of_dlpar):
            self.dlpar_remove()
            self.dlpar_add()

    def tearDown(self):
        self.session.quit()

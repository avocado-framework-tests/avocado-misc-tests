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
# Copyright: 2017 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>
# Author: Naresh Bannoth <nbannoth@in.ibm.com>
"""
This script will perform scsi add and remove test case
"""
import time
from avocado import main
from avocado import Test
from avocado.utils import process, genio
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import multipath


class ScsiAddRemove(Test):

    '''
    Class to execute scsi add/remove operation
    '''

    def setUp(self):
        '''
        Function for preliminary set-up to execute the test
        '''
        self.err_paths = []
        smm = SoftwareManager()
        if not smm.check_installed("lsscsi") and not smm.install("lsscsi"):
            self.cancel("lsscsi is not installed")
        self.wwids = self.params.get('wwids', default='').split(',')
        system_wwids = multipath.get_multipath_wwids()
        for wwid in self.wwids:
            if wwid not in system_wwids:
                self.log.info("%s not present in the system" % wwid)

    def GetscsiId(self, path):
        '''
        calculate and return the scsi_id of a disk
        '''
        cmd = "lsscsi"
        out = process.run(cmd)
        for lines in out.stdout.splitlines():
            if path in lines:
                scsi_num = lines.split()[0].strip("[").strip("]")
                self.log.info("scsi_num=%s", scsi_num)
                scsi_num = scsi_num.replace(":", " ")
                return scsi_num

    def test(self):
        '''
        Function where test is executed
        '''
        for wwid in self.wwids:
            paths = multipath.get_paths(wwid)
            for path in paths:
                scsi_id = self.GetscsiId(path)
                process.run("lsscsi")
                self.log.info("Deleting %s = %s" % (path, scsi_id))
                genio.write_file("/sys/block/%s/device/delete" % path, "1")
                time.sleep(5)
                new_paths = multipath.get_paths(wwid)
                if path in new_paths:
                    self.err_paths.append(path)
                else:
                    self.log.info("\n%s = %s deleted\n" % (path, scsi_id))
                self.log.info("\nadding back %s = %s\n" % (path, scsi_id))
                part = "scsi add-single-device %s" % scsi_id
                genio.write_file("/proc/scsi/scsi", part)
                time.sleep(5)
                new_paths = multipath.get_paths(wwid)
                if path not in new_paths:
                    self.err_paths.append(path)
                else:
                    process.run("lsscsi")
                    self.log.info("%s = %s Added back" % (path, scsi_id))

    def tearDown(self):
        '''
        checking if any failure and exit the test
        '''
        if self.err_paths:
            self.fail("Paths failed to add or remove %s" % self.err_paths)


if __name__ == "__main__":
    main()

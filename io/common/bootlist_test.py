# this program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# Author: Bimurti Bidhibrata Pattjoshi <bbidhibr@in.ibm.com>
#

"""
Bootlist Test
"""

import os
from avocado import Test
from avocado.utils import process
from avocado import skipUnless
from avocado.utils import disk
from avocado.utils import multipath
from avocado.utils.network.hosts import LocalHost

IS_POWER_VM = 'pSeries' in open('/proc/cpuinfo', 'r').read()


class BootlisTest(Test):
    '''
    Displays and alters the list of boot devices available
    to the system
    '''
    @skipUnless(IS_POWER_VM,
                "supported only on PowerVM platform")
    def setUp(self):
        '''
        To check and interfaces
        '''
        self.disk_names = []
        self.host_interfaces = []
        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        disks = self.params.get("disks", default=None)
        ifaces = self.params.get("interfaces", default=None)
        if ifaces:
            for device in ifaces.split(" "):
                if device in interfaces:
                    self.host_interfaces.append(device)
                elif local.validate_mac_addr(device) and device in local.get_all_hwaddr():
                    self.host_interfaces.append(local.get_interface_by_hwaddr(device).name)
                else:
                    self.cancel("Please check the network device")
            self.names = ' '.join(self.host_interfaces)
        elif disks:
            for dev in disks.split():
                dev_path = disk.get_absolute_disk_path(dev)
                dev_base = os.path.basename(os.path.realpath(dev_path))
                if 'dm' in dev_base:
                    dev_base = multipath.get_mpath_from_dm(dev_base)
                self.disk_names.append(dev_base)
            self.names = ' '.join(self.disk_names)
        else:
            self.cancel("user should specify a boot device name")

    def bootlist_mode(self, param):
        '''
        converting into different mode
        '''
        cmd = "bootlist -m %s %s" % (param, self.names)
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True):
            self.fail("%s bootlist fail" % param)

    def normal_bootlist_file(self):
        '''
        default bootlist write in to a file
        '''
        cmd = "bootlist -m normal -r > /tmp/normal"
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("unable to write normal bootlist in to the file")

    def set_original_normal_bootlist(self):
        '''
        set the original bootlist
        '''
        cmd = "bootlist -m normal -f /tmp/normal"
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("failed to set default normal bootlist")

    def service_bootlist_file(self):
        '''
        default sevice bootlist write in to a file
        '''
        cmd = "bootlist -m service -r > /tmp/service"
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("unable to write normal bootlist in to the file")

    def set_original_service_bootlist(self):
        '''
        set the original service bootlist
        '''
        cmd = "bootlist -m service -f /tmp/service"
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("failed to set default service bootlist")

    @staticmethod
    def display_normal_logical_device():
        '''
        Displaying normal bootlist entries as logical device name
        '''
        cmd = "bootlist -m normal -o"
        for line in process.system_output(cmd, shell=True,
                                          ignore_status=True).splitlines():
            return line.split()[-1]

    @staticmethod
    def display_normal_firmware_device():
        '''
        Display normal bootlist entries as open firmware devices
        '''
        cmd = "bootlist -m normal -r"
        for line in process.system_output(cmd, shell=True,
                                          ignore_status=True).splitlines():
            return line.split()[-1]

    @staticmethod
    def display_service_logical_device():
        '''
        Displaying service bootlist entries as logical device name
        '''
        cmd = "bootlist -m service -o"
        for line in process.system_output(cmd, shell=True,
                                          ignore_status=True).splitlines():
            return line.split()[-1]

    @staticmethod
    def display_service_firmware_device():
        '''
        Display service bootlist entries as open firmware devices
        '''
        cmd = "bootlist -m service -r"
        for line in process.system_output(cmd, shell=True,
                                          ignore_status=True).splitlines():
            return line.split()[-1]

    def test_normal_mode(self):
        '''
        To make a boot list for Normal mode
        '''
        self.normal_bootlist_file()
        self.bootlist_mode("normal")
        self.display_normal_logical_device()
        self.display_normal_firmware_device()
        self.set_original_normal_bootlist()

    def test_service_mode(self):
        '''
        To make a boot list for service mode
        '''
        self.service_bootlist_file()
        self.bootlist_mode("service")
        self.display_service_logical_device()
        self.display_service_firmware_device()
        self.set_original_service_bootlist()

    def test_both_mode(self):
        '''
        To make boot list for both mode
        '''
        self.bootlist_mode("both")
        self.display_normal_logical_device()
        self.display_normal_firmware_device()
        self.display_service_logical_device()
        self.display_service_firmware_device()
        self.set_original_normal_bootlist()
        self.set_original_service_bootlist()

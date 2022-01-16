#!/usr/bin/env python

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
        self.host_interfaces = self.params.get("host_interfaces",
                                               default=None)
        self.disk_names = self.params.get("disks", default=None)
        if self.host_interfaces is not None:
            if not self.host_interfaces:
                self.cancel("user should specify host interfaces")
            self.names = self.host_interfaces
            interfaces = os.listdir('/sys/class/net')
            for host_interface in self.host_interfaces.split(" "):
                if host_interface not in interfaces:
                    self.cancel("interface is not available")
        elif self.disk_names is not None:
            if not self.disk_names:
                self.cancel("user should specify disk name")
            self.names = self.disk_names

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

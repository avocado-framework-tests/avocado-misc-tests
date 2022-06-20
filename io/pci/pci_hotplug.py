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
# Author: Naresh Bannoth <nbannoth@in.ibm.com>
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
PCI Hotplug can remove and add pci devices when the system is active.
This test verifies that for supported slots.
"""

import os
import time
import platform
from avocado import Test
from avocado.utils import wait, multipath
from avocado.utils import linux_modules, genio, pci
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost


class PCIHotPlugTest(Test):

    """
    PCI Hotplug can remove and add pci devices when the system is active.
    This test verifies that for supported slots.
    :param device: Name of the pci device
    :param peer_ip: peer network adapter IP
    :param count: Number of times the hotplug needs to perform
    """

    def setUp(self):
        """
        Setup the device.
        """
        if 'ppc' not in platform.processor():
            self.cancel("Processor is not ppc64")
        if os.path.exists('/proc/device-tree/bmc'):
            self.cancel("Test Unsupported! on this platform")
        if 'pSeries' in open('/proc/cpuinfo', 'r').read():
            for mdl in ['rpaphp', 'rpadlpar_io']:
                if not linux_modules.module_is_loaded(mdl):
                    linux_modules.load_module(mdl)
        elif 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            if not linux_modules.module_is_loaded("pnv_php"):
                linux_modules.load_module("pnv_php")
        self.dic = {}
        self.device = self.params.get('pci_devices', default="")
        self.peer_ip = self.params.get('peer_ip', default="")
        self.count = int(self.params.get('count', default='1'))
        if not self.device:
            self.cancel("PCI_address not given")
        self.device = self.device.split(" ")
        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package is need to test")

        for pci_addr in self.device:
            if not os.path.isdir('/sys/bus/pci/devices/%s' % pci_addr):
                self.cancel("%s not present in device path" % pci_addr)
            slot = pci.get_slot_from_sysfs(pci_addr)
            if not slot:
                self.cancel("slot number not available for: %s" % pci_addr)
            self.dic[pci_addr] = slot

    def test(self):
        """
        Removes and adds back a PCI adapter based on pci_adress.
        """
        err_pci = []
        for pci_addr in self.device:
            for _ in range(self.count):
                if not self.hotplug_remove(self.dic[pci_addr], pci_addr):
                    err_pci.append(pci_addr)
                else:
                    self.log.info("%s removed successfully", pci_addr)
                time.sleep(10)
                if not self.hotplug_add(self.dic[pci_addr], pci_addr):
                    err_pci.append(pci_addr)
                else:
                    self.log.info("%s added back successfully", pci_addr)
                time.sleep(10)
        if err_pci:
            self.fail("following devices failed: %s" % ", ".join(err_pci))

    @staticmethod
    def hotplug_remove(slot, pci_addr):
        """
        Hot Plug remove operation
        """
        genio.write_file("/sys/bus/pci/slots/%s/power" % slot, "0")

        def is_removed():
            """
            Returns True if pci device is removed, False otherwise.
            """
            if pci_addr in pci.get_pci_addresses():
                return False
            return True

        return wait.wait_for(is_removed, timeout=10) or False

    def hotplug_add(self, slot, pci_addr):
        """
        Hot plug add operation and recovery check
        """
        genio.write_file("/sys/bus/pci/slots/%s/power" % slot, "1")

        def is_added():
            """
            Returns True if pci device is added, False otherwise.
            """
            if pci_addr not in pci.get_pci_addresses():
                return False
            return True

        def is_recovered():
            """
            Checks if the block device adapter is recovers all its disks/paths
            properly after hotplug of adapter.
            Returns True if all disks/paths back online after adapter added
            Back, else False.
            """
            def is_path_online():
                path_stat = list(multipath.get_path_status(curr_path))
                if path_stat[0] != 'active' or path_stat[2] != 'ready':
                    return False
                return True

            curr_path = ''
            err_disks = []
            if pci.get_pci_class_name(pci_addr) == 'fc_host':
                disks = pci.get_disks_in_pci_address(pci_addr)
                for disk in disks:
                    curr_path = disk.split("/")[-1]
                    self.log.info("curr_path=%s" % curr_path)
                    if not wait.wait_for(is_path_online, timeout=10):
                        self.log.info("%s failed to recover after add" % disk)
                        err_disks.append(disk)

            if err_disks:
                self.log.info("few paths failed to recover : %s" % err_disks)
                return False
            return True

        def net_recovery_check():
            """
            Checks if the network adapter fuctionality like ping/link_state,
            after adapter added back.
            Returns True on propper Recovery, False if not.
            """
            self.log.info("entering the net recovery check")
            local = LocalHost()
            iface = pci.get_interfaces_in_pci_address(pci_addr, 'net')
            networkinterface = NetworkInterface(iface[0], local)
            if wait.wait_for(networkinterface.is_link_up, timeout=120):
                if networkinterface.ping_check(self.peer_ip, count=5) is None:
                    self.log.info("inteface is up and pinging")
                    return True
            return False

        if wait.wait_for(is_added, timeout=30):
            time.sleep(45)
            if pci.get_pci_class_name(pci_addr) == 'net':
                if wait.wait_for(net_recovery_check, timeout=30):
                    return True
                return False
            else:
                if wait.wait_for(is_recovered, timeout=30):
                    return True
        return False

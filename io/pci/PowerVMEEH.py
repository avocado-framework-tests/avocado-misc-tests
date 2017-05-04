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
#
# Copyright: 2017 IBM
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>

"""
This scripts basic EEH tests on all PCI device
"""

import time
import sys
from avocado import main
from avocado import Test
from avocado.utils import process
from avocado.utils import pci
from avocado.utils import genio

EEH_HIT = 0
EEH_MISS = 1


class EEHRecoveryFailed(Exception):
    """
    Exception class, if EEH fails to recover
    """
    def __init__(self, thing, dev, log=None):
        self.thing = thing
        self.dev = dev
        self.log = log

    def __str__(self):
        return "%s %s recovery failed: %s" % (self.thing, self.dev, self.log)


class PowerVMEEH(Test):

    """
    This class contains functions for listing domains
    forming EEH command
    """
    def setUp(self):

        """
        Gets the console and set-up the machine for test
        """
        output = genio.read_file("/sys/kernel/debug/powerpc/eeh_enable")\
            .strip()
        if output != '0x1':
            self.skip("EEH is not enabled, please enable via FSP")
            sys.exit(1)
        self.max_freeze = int(self.params.get('max_freeze', default='1'))
        cmd = "echo %d > /sys/kernel/debug/powerpc/eeh_max_freezes"\
            % self.max_freeze
        process.system(cmd, ignore_status=True, shell=True)
        self.function = str(self.params.get('function')).split(" ")
        self.log.info("===============Testing EEH Frozen PE==================")

    def test_eeh_basic_pe(self):

        """
        Test to execute basic error injection on PE
        """
        for self.addr in pci.get_pci_addresses():
            enter_loop = True
            num_of_miss = 0
            num_of_hit = 0
            self.pci_mem_addr = pci.get_memory_address(self.addr)
            self.pci_mask = pci.get_mask(self.addr)
            self.pci_class_name = pci.get_pci_class_name(self.addr)
            self.pci_interface = pci.get_interfaces_in_pci_address(
                self.addr, self.pci_class_name)[-1]
            self.log.info("PCI addr = %s" % self.addr)
            self.log.info("PCI mem_addr = %s" % self.pci_mem_addr)
            self.log.info("PCI mask = %s" % self.pci_mask)
            self.log.info("PCI class name = %s" % self.pci_class_name)
            self.log.info("PCI interface = %s" % self.pci_interface)
            while num_of_hit <= self.max_freeze:
                for func in self.function:
                    self.log.info("Running error inject on pe %s function %s"
                                  % (self.addr, func))
                    if num_of_miss < 5:
                        return_code = self.basic_eeh(func,
                                                     self.pci_class_name,
                                                     self.pci_interface,
                                                     self.pci_mem_addr,
                                                     self.pci_mask)
                        if return_code == EEH_MISS:
                            num_of_miss += 1
                            self.log.info("number of miss is %d"
                                          % num_of_miss)
                            continue
                        else:
                            num_of_hit += 1
                            self.log.info("number of hit is %d"
                                          % num_of_hit)
                            if num_of_hit <= self.max_freeze:
                                if not self.check_eeh_pe_recovery(self.addr):
                                    self.fail("PE %s recovery failed after"
                                              "%d EEH" % (self.addr,
                                                          num_of_hit))
                                    break
                                else:
                                    self.log.info("PE recovered successfully")
                    else:
                        self.log.warning("EEH inject failed for 5 times with\
                                   function %s" % func)
                        enter_loop = False
                        break
                if not enter_loop:
                    break
            else:
                if self.check_eeh_removed():
                    self.log.info("PE %s removed successfully" % self.addr)
                else:
                    self.fail("PE %s not removed after max hit" % self.addr)

    def basic_eeh(self, func, pci_class_name, pci_interface,
                  pci_mem_addr, pci_mask):

        """
        Injects Error, and checks for PE recovery
        returns True, if recovery is success, else Flase
        """
        self.clear_dmesg_logs()
        return_code = self.error_inject(func, pci_class_name,
                                        pci_interface, pci_mem_addr,
                                        pci_mask)
        if return_code != EEH_HIT:
            self.log.info("Skipping verification, as command failed")
        if not self.check_eeh_hit():
            self.log.info("PE %s EEH hit failed" % self.addr)
            return EEH_MISS
        else:
            self.log.info("PE %s EEH hit success" % self.addr)
            return EEH_HIT

    @classmethod
    def error_inject(cls, func, pci_class_name, pci_interface, pci_mem_addr,
                     pci_mask):

        """
        Form a command to inject the error
        """
        cmd = "errinjct eeh -v -f %s -s %s/%s -a %s -m %s; echo $?"\
            % (func, pci_class_name, pci_interface, pci_mem_addr, pci_mask)
        res = process.system_output(cmd, ignore_status=True, shell=True)
        return int(res[-1])

    def check_eeh_pe_recovery(self, addr):

        """
        Check if the PE is recovered successfully after injecting EEH
        """
        cmd = "dmesg | grep -i 'EEH: Notify device driver to resume'; echo $?"
        tries = 60
        for _ in range(0, tries):
            res = process.system_output(cmd, ignore_status=True, shell=True)
            if int(res[-1]) != 0:
                self.log.info("waiting for PE to recover %s" % self.addr)
                time.sleep(1)
            else:
                break
        else:
            raise EEHRecoveryFailed("EEH recovery failed", addr)
        tries = 30
        for _ in range(0, tries):
            for device in pci.get_pci_addresses():
                if self.addr in device:
                    return True
                time.sleep(1)
            return False

    @classmethod
    def clear_dmesg_logs(cls):

        """
        Clears dmesg logs, so that functions which uses dmesg
        gets the latest logs
        """
        cmd = "dmesg -C"
        process.system(cmd, ignore_status=True, shell=True)

    @classmethod
    def check_eeh_hit(cls):

        """
        Function to check if EEH is successfully hit
        """
        tries = 10
        cmd = "dmesg | grep 'EEH: Frozen';echo $?"
        for _ in range(0, tries):
            res = process.system_output(cmd, ignore_status=True, shell=True)
            if int(res[-1]) == 0:
                return True
            time.sleep(1)
        return False

    @classmethod
    def check_eeh_removed(cls):

        """
        Function to check if PE is recovered successfully
        """
        tries = 30
        for _ in range(0, tries):
            cmd = "(dmesg | grep 'permanently disabled'; echo $?)"
            res = process.system_output(cmd, ignore_status=True, shell=True)
            if int(res[-1]) == 0:
                time.sleep(10)
                return True
            time.sleep(1)
        return False


if __name__ == '__main__':
    main()

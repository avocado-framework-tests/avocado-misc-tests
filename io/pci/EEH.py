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
from avocado import Test
from avocado.utils import process
from avocado.utils import pci
from avocado.utils import genio
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils.software_manager import SoftwareManager

EEH_HIT = 0
EEH_MISS = 1


class EEHRecoveryFailed(Exception):

    """
    Exception class, if EEH fails to recover
    """

    def __init__(self, msg, dev, log=None):
        self.msg = msg
        self.dev = dev
        self.log = log

    def __str__(self):
        return "%s %s recovery failed: %s" % (self.msg, self.dev, self.log)


class EEH(Test):

    """
    This class contains functions for listing domains
    forming EEH command
    """

    def setUp(self):
        """
        Gets the console and set-up the machine for test
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not ppc64")
        eeh_enable_file = "/sys/kernel/debug/powerpc/eeh_enable"
        if '0x1' not in genio.read_file(eeh_enable_file).strip():
            self.cancel("EEH is not enabled, please enable via FSP")
        self.max_freeze = self.params.get('max_freeze', default=1)
        self.pci_device = self.params.get('pci_device', default="")
        self.add_cmd = self.params.get('additional_command', default='')
        if not self.pci_device:
            self.cancel("No PCI Device specified")
        self.function = str(self.params.get('function')).split(" ")
        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package is need to test")
        self.mem_addr = pci.get_memory_address(self.pci_device)
        self.mask = pci.get_mask(self.pci_device)
        if self.is_baremetal():
            cmd = "echo %d > /sys/kernel/debug/powerpc/eeh_max_freezes"\
                % self.max_freeze
            process.system(cmd, ignore_status=True, shell=True)
            self.phb = self.pci_device.split(":", 1)[0]
            self.addr = genio.read_file("/sys/bus/pci/devices/%s/"
                                        "eeh_pe_config_addr" % self.pci_device)
            self.addr = str(self.addr).rstrip()
            self.err = 0
            for line in process.system_output('lspci -vs %s' % self.pci_device,
                                              ignore_status=True,
                                              shell=True).decode("utf-8\
                                              ").splitlines():
                if 'Memory' in line and '64-bit, prefetchable' in line:
                    self.err = 1
                    break
        else:
            self.pci_class_name = pci.get_pci_class_name(self.pci_device)
            if self.pci_class_name == 'fc_host':
                self.pci_class_name = 'scsi_host'
            self.pci_interface = pci.get_interfaces_in_pci_address(
                self.pci_device, self.pci_class_name)[-1]
        self.log.info("===============Testing EEH Frozen PE==================")

    def test_eeh_basic_pe(self):
        """
        Test to execute basic error injection on PE
        """
        enter_loop = True
        num_of_miss = 0
        num_of_hit = 0
        while num_of_hit <= self.max_freeze:
            for func in self.function:
                self.log.info("Running error inject on pe %s function %s",
                              self.pci_device, func)
                if num_of_miss < 5:
                    if self.is_baremetal():
                        return_code = self.basic_eeh(func, '', '', '', '', '')
                    else:
                        return_code = self.basic_eeh(func,
                                                     self.pci_class_name,
                                                     self.pci_interface,
                                                     self.mem_addr,
                                                     self.mask,
                                                     self.add_cmd)
                    if return_code == EEH_MISS:
                        num_of_miss += 1
                        self.log.info("number of miss is %d", num_of_miss)
                        continue
                    else:
                        num_of_hit += 1
                        self.log.info("number of hit is %d", num_of_hit)
                        if num_of_hit <= self.max_freeze:
                            if not self.check_eeh_pe_recovery():
                                self.fail("PE %s recovery failed after"
                                          "%d EEH" % (self.pci_device,
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
                self.log.info("PE %s removed successfully", self.pci_device)
            else:
                self.fail("PE %s not removed after max hit" % self.pci_device)

    def basic_eeh(self, func, pci_class_name, pci_interface,
                  pci_mem_addr, pci_mask, add_cmd):
        """
        Injects Error, and checks for PE recovery
        returns True, if recovery is success, else Flase
        """
        dmesg.clear_dmesg()
        if self.is_baremetal():
            return_code = self.error_inject(func, '', '', self.mem_addr,
                                            self.mask, '', self.addr,
                                            self.err, self.phb)
        else:
            return_code = self.error_inject(func, pci_class_name,
                                            pci_interface, pci_mem_addr,
                                            pci_mask, add_cmd, '', '', '')
        if return_code != EEH_HIT:
            self.log.info("Skipping verification, as command failed")
        if not self.check_eeh_hit():
            self.log.info("PE %s EEH hit failed" % self.pci_device)
            return EEH_MISS
        else:
            self.log.info("PE %s EEH hit success" % self.pci_device)
            return EEH_HIT

    def error_inject(self, func, pci_class_name, pci_interface, pci_mem_addr,
                     pci_mask, add_cmd, addr, err, phb):
        """
        Form a command to inject the error
        """
        if self.is_baremetal():
            cmd = "echo %s:%s:%s:%s:%s > /sys/kernel/debug/powerpc/PCI%s/err_injct \
                   && lspci; echo $?" % (addr, err, func, pci_mem_addr, pci_mask, phb)
            return int(process.system_output(cmd, ignore_status=True,
                                             shell=True).decode("utf-8")[-1])
        else:
            cmd = "errinjct eeh -v -f %s -s %s/%s -a %s -m %s; echo $?"\
                % (func, pci_class_name, pci_interface, pci_mem_addr, pci_mask)
            res = process.system_output(cmd, ignore_status=True,
                                        shell=True).decode("utf-8")
            if add_cmd:
                process.run(add_cmd, ignore_status=True, shell=True)
                return int(res[-1])

    def check_eeh_pe_recovery(self):
        """
        Check if the PE is recovered successfully after injecting EEH
        """
        cmd = "dmesg"
        tries = 60
        for _ in range(0, tries):
            res = process.run(cmd, ignore_status=True, shell=True)
            if 'EEH: Notify device driver to resume' in res.stdout.decode("utf-8") and \
               res.exit_status != 0:
                self.log.info("waiting for PE to recover %s", self.pci_device)
                time.sleep(1)
            else:
                # EEH Recovery is not similar for all adapters. For some
                # adapters, specifically multipath, we see that the adapter
                # needs some more time to recover after the message "Notify
                # device driver to resume" on the dmesg.
                # There is no reliable way to determine this extra time
                # required, nor a way to determine the recovery. So, a sleep
                # time of 10s is introduced.
                time.sleep(10)
                break
        else:
            raise EEHRecoveryFailed("EEH recovery failed", self.pci_device)
        tries = 30
        for _ in range(0, tries):
            for device in pci.get_pci_addresses():
                if self.pci_device in device:
                    return True
                time.sleep(1)
            return False

    @classmethod
    def check_eeh_hit(cls):
        """
        Function to check if EEH is successfully hit
        """
        tries = 30
        cmd = "dmesg"
        for _ in range(0, tries):
            res = process.run(cmd, ignore_status=True, shell=True)
            if 'EEH: Frozen' in res.stdout.decode("utf-8") and \
               res.exit_status == 0:
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
            cmd = "dmesg"
            res = process.run(cmd, ignore_status=True, shell=True)
            if 'permanently disabled' in res.stdout.decode("utf-8") and \
               res.exit_status == 0:
                time.sleep(10)
                return True
            time.sleep(1)
        return False

    @staticmethod
    def is_baremetal():
        """
        to check system is bare-metal or not
        """
        if 'PowerNV' in genio.read_file("/proc/cpuinfo").strip():
            return True
        return False

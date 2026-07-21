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
import psutil
from avocado import Test
from avocado.utils import process, wait
from avocado.utils import pci
from avocado.utils import genio
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils import multipath
from avocado.utils import data_structures
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost

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
        return f"{self.msg} {self.dev} recovery failed: {self.log}" % (
                self.msg, self.dev, self.log
            )


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
        self.ipaddr = self.params.get("host_ip", default=None)
        if self.ipaddr:
            self.peer_ip = self.params.get("peer_ip", default=None)
            self.interface = pci.get_nics_in_pci_address(self.pci_device)[0]
            self.localhost = LocalHost()
            device = self.interface
            # Check if device is a MAC address or interface name
            if self.localhost.validate_mac_addr(device):
                if device in self.localhost.get_all_hwaddr():
                    self.interface = self.localhost.get_interface_by_hwaddr(
                        device).name
                else:
                    self.cancel("Please check the network device")
            # If it's already an interface name, use it directly
            self.networkinterface = NetworkInterface(self.interface,
                                                     self.localhost)
            if not self.networkinterface.validate_ipv4_format(self.ipaddr):
                self.cancel("Please mention the correct host IP address")
            if not self.networkinterface.validate_ipv4_format(self.peer_ip):
                self.cancel("Please mention the correct peer IP address")
            self.netmask = self.params.get("netmask", default="")
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
            self.networkinterface.bring_up()
            if not wait.wait_for(self.networkinterface.is_link_up, timeout=60):
                self.cancel("Link up of host interface taking more than 60s")
        if self.is_baremetal():
            cmd = f"echo {self.max_freeze} > /sys/kernel/debug/powerpc/eeh_max_freezes"
            process.system(cmd, ignore_status=True, shell=True)
            self.phb = self.pci_device.split(":", 1)[0]
            self.addr = genio.read_file(
                    f"/sys/bus/pci/devices/{self.pci_device}/eeh_pe_config_addr"
            )
            self.addr = str(self.addr).rstrip()
            self.err = 0
            for line in process.system_output(f"lspci -vs {self.pci_device}",
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
        while num_of_hit < self.max_freeze:
            for func in self.function:
                self.log.info("Running error inject on pe %s function %s",
                              self.pci_device, func)
                if pci.get_pci_class_name(self.pci_device) == "fc_host":
                    before_eeh_path_status = multipath.get_multipath_details()
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
                        self.log.info(f"number of miss is {num_of_miss}")
                        continue
                    else:
                        num_of_hit += 1
                        self.log.info("number of hit is %d", num_of_hit)
                        if num_of_hit <= self.max_freeze:
                            if not self.check_eeh_pe_recovery():
                                self.fail(
                                        f"PE {self.pci_device} recovery failed after {num_of_hit}"
                                        f" EEH"
                                )
                                break
                            else:
                                self.log.info("PE recovered successfully")
                                # Verify network connectivity for net adapters
                                if (pci.get_pci_class_name(self.pci_device)
                                        == "net" and hasattr(self, 'peer_ip')
                                        and self.peer_ip):
                                    if not self.net_recovery_check(
                                            self.interface):
                                        self.fail(
                                            "Network adapter failed to ping "
                                            "after EEH recovery"
                                        )
                        time.sleep(10)
                        if pci.get_pci_class_name(self.pci_device) == "fc_host":
                            after_eeh_path_status = multipath.get_multipath_details()
                            get_diff_bef_aft = data_structures.recursive_compare_dict(
                                    before_eeh_path_status,
                                    after_eeh_path_status,
                                    diff_btw_dict=[]
                                )
                            if len(get_diff_bef_aft) != 0:
                                for value in get_diff_bef_aft[:]:
                                    if ("path_faults " in value) or ("switch_grp " in value):
                                        get_diff_bef_aft.remove(value)
                                if len(get_diff_bef_aft) != 0:
                                    self.fail("Some devices/disks are failed to recover after EEH")
                                    self.log.info(get_diff_bef_aft)
                else:
                    self.log.warning(f"EEH inject failed for 5 times with function {func}")
                    enter_loop = False
                    break
            if not enter_loop:
                break
        else:
            if self.check_eeh_removed():
                self.log.info(f"PE {self.pci_device} removed successfully")
            else:
                self.fail(f"PE {self.pci_device} not removed after max hit")

    def test_eeh_sriov(self):
        """
        Test to execute EEH error injection on SR-IOV devices
        """
        # Get the bus address from the PCI device
        bus_id = self.pci_device.split(':')[0]

        # Get interface name from PCI address
        interface_list = pci.get_nics_in_pci_address(self.pci_device)
        if not interface_list:
            self.fail(
                f"No network interface found for PCI device "
                f"{self.pci_device}"
            )
        interface_name = interface_list[0]
        self.log.info(
            f"Interface name for {self.pci_device}: {interface_name}"
        )

        # Get bus address from journalctl
        bus_address = self.get_bus_address_from_journalctl(bus_id)
        if not bus_address:
            self.fail(
                f"Failed to get bus address for {self.pci_device} "
                f"from journalctl"
            )
        self.log.info(f"Bus address from journalctl: {bus_address}")

        # Start network traffic on the SR-IOV interface
        self.log.info(
            f"Starting traffic on SR-IOV interface: {interface_name}"
        )

        # Start ping flood on the interface
        if self.peer_ip:
            networkinterface = NetworkInterface(interface_name,
                                                self.localhost)
            networkinterface.ping_flood(interface_name, self.peer_ip,
                                        1000000)

        # Clear dmesg before error injection
        dmesg.clear_dmesg()

        # Trigger EEH with the specified command
        mask = "0xffffffffffc00000"
        cmd = f"errinjct ioa-bus-error-64 -v -f 6 -s net/{interface_name} "
        cmd += f"-a {bus_address} -m {mask}"

        self.log.info(f"Triggering EEH with command: {cmd}")
        try:
            result = process.run(cmd, ignore_status=True, shell=True)
            output = result.stdout.decode('utf-8')
            self.log.info(f"EEH injection command output: {output}")
        except Exception as e:
            self.log.error(f"Error during EEH injection: {str(e)}")

        # Stop the network traffic after error inject
        for ps in psutil.process_iter(['name']):
            if ps.info['name'] == 'ping':
                ps.kill()

        # Check if EEH was hit
        if not self.check_eeh_hit():
            self.fail(
                f"EEH hit failed for SR-IOV device {self.pci_device}"
            )
        else:
            self.log.info(
                f"EEH hit successful for SR-IOV device {self.pci_device}"
            )

        # Check for PE recovery
        if not self.check_eeh_pe_recovery():
            self.fail(
                f"SR-IOV device {self.pci_device} recovery failed "
                f"after EEH"
            )
        else:
            self.log.info(
                f"SR-IOV device {self.pci_device} recovered successfully"
            )

        # Additional validation for network interface
        time.sleep(10)
        net_interface = NetworkInterface(interface_name, self.localhost)
        if not wait.wait_for(net_interface.is_link_up, timeout=60):
            self.fail(
                f"Interface {interface_name} failed to come up after EEH"
            )
        self.log.info(
            f"Interface {interface_name} is up after EEH recovery"
        )

        # Verify network connectivity with ping check
        if self.peer_ip and not self.net_recovery_check(interface_name):
            self.fail("Network adapter failed to ping after EEH recovery")

    def net_recovery_check(self, interface_name):
        """
        Checks if the network adapter functionality like ping/link_state,
        after EEH recovery.
        Returns True on proper Recovery, False if not.
        """
        self.log.info("Performing network recovery check")
        local = LocalHost()
        networkinterface = NetworkInterface(interface_name, local)
        if wait.wait_for(networkinterface.is_link_up, timeout=120):
            if networkinterface.ping_check(self.peer_ip, count=5) is None:
                self.log.info("Interface is up and pinging")
                return True
        return False

    def get_bus_address_from_journalctl(self, bus_id):
        """
        Extract bus address from journalctl for the given bus ID
        Example output:
        pci_bus 40xx:xx: root bus resource
        [mem 0x4xxxc000000-0x4xxxxffffff 64bit]
        (bus address [0x60xxxx000000-0x6xxxxxffffff])
        """
        cmd = "journalctl | grep 'bus address'"
        try:
            output = process.system_output(cmd, ignore_status=True,
                                           shell=True).decode("utf-8")

            # Parse the output to find the matching bus ID
            for line in output.splitlines():
                if f"pci_bus {bus_id}" in line:
                    # Extract bus address from the line
                    # Format: (bus address [0x60xxxx000000-0x6xxxxxffffff])
                    if 'bus address' in line:
                        start_idx = line.find('[', line.find('bus address'))
                        end_idx = line.find('-', start_idx)
                        if start_idx != -1 and end_idx != -1:
                            bus_address = line[start_idx + 1:end_idx].strip()
                            self.log.info(
                                f"Found bus address: {bus_address}"
                            )
                            return bus_address

            self.log.warning(
                f"Bus address not found for bus ID {bus_id} in journalctl"
            )
            return None
        except Exception as e:
            self.log.error(
                f"Error getting bus address from journalctl: {str(e)}"
            )
            return None

    def basic_eeh(self, func, pci_class_name, pci_interface,
                  pci_mem_addr, pci_mask, add_cmd):
        """
        Injects Error, and checks for PE recovery
        returns True, if recovery is success, else False
        """
        dmesg.clear_dmesg()
        # Start network traffic for net pci_class
        if self.pci_class_name == 'net':
            self.networkinterface.ping_flood(self.interface,
                                             self.peer_ip,
                                             1000000)
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
            self.log.info(f"PE {self.pci_device} EEH hit failed")
            return EEH_MISS
        else:
            self.log.info(f"PE {self.pci_device} EEH hit success")
            return EEH_HIT
        # Stop the network traffic after error inject
        for ps in psutil.process_iter(['name']):
            if ps.info['name'] == 'ping':
                ps.kill()

    def error_inject(self, func, pci_class_name, pci_interface, pci_mem_addr,
                     pci_mask, add_cmd, addr, err, phb):
        """
        Form a command to inject the error
        """
        if self.is_baremetal():
            cmd = f"echo {addr}:{err}:{func}:{pci_mem_addr}:{pci_mask} > "
            cmd += f"/sys/kernel/debug/powerpc/PCI{phb}/err_injct && lspci; echo $?"
            return int(process.system_output(cmd, ignore_status=True,
                                             shell=True).decode("utf-8")[-1])
        else:
            cmd = f"errinjct eeh -v -f {func} -s {pci_class_name}/{pci_interface}"
            cmd += f" -a {pci_mem_addr} -m {pci_mask}; echo $?"
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
            if 'EEH: Recovery successful.' in res.stdout.decode("utf-8"):
                self.log.info("waiting for PE to recover %s", self.pci_device)
                # EEH Recovery is not similar for all adapters. For some
                # adapters, specifically multipath, we see that the adapter
                # needs some more time to recover after the message "Notify
                # device driver to resume" on the dmesg.
                # There is no reliable way to determine this extra time
                # required, nor a way to determine the recovery. So, a sleep
                # time of 10s is introduced.
                time.sleep(10)
                break
            time.sleep(1)
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

# Assisted by AI tool

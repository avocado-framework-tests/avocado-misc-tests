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
# Copyright: 2023 IBM
# Author: Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>
"""
This script will perform usb related testcases
"""
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import disk, distro, dmesg, pci, process, service, wait


class USBTests(Test):

    '''
    Class to execute usb tests
    '''

    def setUp(self):
        """
        Function for preliminary set-up to execute the test
        """
        distro_name = distro.detect().name.lower()
        smm = SoftwareManager()
        pkgs = ["usbguard"]
        if distro_name in ['rhel', 'fedora']:
            pkgs.extend(["libqb", "protobuf"])
        elif distro_name == 'suse':
            pkgs.extend(["libqb-devel", "protobuf-devel"])
        else:
            self.cancel("Install required packages")
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(f"{pkg} is not installed")
        self.usb_pci_device = self.params.get("pci_device", default=None)
        if not self.usb_pci_device:
            self.cancel("please provide pci adrees or wwids of scsi disk")
        if self.usb_pci_device not in pci.get_pci_addresses():
            self.cancel(f"PCI Adress {self.usb_pci_device} not found among "
                        f"list of available PCI devices")
        self.usb_disk = self.params.get("disk", default=None)
        if not self.usb_disk:
            self.cancel("Disk information not provided in yaml")
        if self.usb_disk:
            self.usb_disk = disk.get_absolute_disk_path(self.usb_disk)
        self.num_of_partitions = self.params.get("num_of_partitions", default=None)
        self.partition_size = self.params.get("partition_size", default=None)
        self.rules_conf = "/etc/usbguard/rules.conf"
        # Create service object
        self.usbguard_svc = service.SpecificServiceManager("usbguard")

    def test_create_usb_partitions(self):
        """
        Create specified number of partitions on USB disk
        """
        if self.num_of_partitions and self.partition_size:
            partitions = disk.create_linux_raw_partition(
                self.usb_disk,
                size=self.partition_size,
                num_of_par=self.num_of_partitions
            )
        elif self.num_of_partitions and not self.partition_size:
            partitions = disk.create_linux_raw_partition(
                self.usb_disk,
                num_of_par=self.num_of_partitions
            )
        elif not self.num_of_partitions and self.partition_size:
            partitions = disk.create_linux_raw_partition(
                self.usb_disk,
                size=self.partition_size,
            )
        self.log.info(f"Partitions created: {partitions}")

    def test_delete_all_usb_partitions(self):
        """
        Deletes all partition on USB disk and wipes partition table on USB
        """
        disk.clean_disk(self.usb_disk)
        partitions = disk.get_disk_partitions(self.usb_disk)
        if partitions:
            self.log.fail("Partitions {partitions} not deleted")

    def test_usbguard(self):
        """
        Block and allow devices attached to USB device
        1. Change usb device state by editing conf file using sed
        2. Change usb device state by using usbguard
        """
        self.install_usbguard_rules_conf()
        for state in ["block", "allow"]:
            self.change_usb_device_state_with_sed(state)
            if self.disk_listed_under_lsscsi() and state == "block":
                self.fail(f"{self.usb_disk} is listed under lsscsi even after blocking device")
            elif not self.disk_listed_under_lsscsi() and state == "allow":
                self.fail(f"{self.usb_disk} is not listed under lsscsi even after allowing device")
        for state in ["block", "allow"]:
            cur_dev_state = self.get_usb_devices_state()
            if len(cur_dev_state) > 1:
                for _ in cur_dev_state:
                    self.change_usb_device_state_with_usbguard(state, _[0])
            else:
                self.change_usb_device_state_with_usbguard(
                    state,
                    cur_dev_state[0][0]
                )
            if self.disk_listed_under_lsscsi() and state == "block":
                self.fail(f"{self.usb_disk} is seen with lsscsi even after blocking device")
            elif not self.disk_listed_under_lsscsi() and state == "allow":
                self.fail(f"{self.usb_disk} is not seen with lsscsi even after allowing device")

    def install_usbguard_rules_conf(self):
        """
        Generate and install rules.conf for usbguard service
        """
        tmp_rules = "/tmp/rules.conf"
        process.system(
            f"usbguard generate-policy > {tmp_rules}",
            shell=True,
            ignore_status=True
        )
        user_name = process.system_output("whoami").decode('utf-8')
        process.system(
            f"install -m 0600 -o {user_name} -g {user_name} {tmp_rules} {self.rules_conf}",
            shell=True,
            ignore_status=True
        )
        self.restart_usbguard_service()

    def restart_usbguard_service(self):
        """
        Restart usbguard service
        """
        self.usbguard_svc.restart()
        wait.wait_for(self.usbguard_svc.status, timeout=10)

    def get_usb_devices_state(self):
        """
        Get devices connected to usb
        """
        list_of_usb_devices = process.system_output("usbguard list-devices").decode('utf-8')
        usb_devices = [
            dev for dev in list_of_usb_devices.split("\n") if self.usb_pci_device not in dev
        ]
        return [(dev.split()[0].replace(":", ""), dev.split()[1]) for dev in usb_devices]

    def disk_listed_under_lsscsi(self):
        """
        Retuens boolean True is disk is listed under lsscsi else false
        """
        lsscsi_output = process.system_output("lsscsi").decode('utf-8').split("\n")
        return self.usb_disk in [line.split()[-1] for line in lsscsi_output]

    def change_usb_device_state_with_sed(self, dev_state):
        """
        Changes state of usb device br editing conf file
        """
        dmesg_txt = dmesg.collect_dmesg()
        if dev_state == "block":
            process.system(
                f"sed -i 's/allow/{dev_state}/g' {self.rules_conf}",
                shell=True,
                ignore_status=True
            )
        else:
            process.system(
                f"sed -i 's/block/{dev_state}/g' {self.rules_conf}",
                shell=True,
                ignore_status=True
            )
        self.restart_usbguard_service()
        if dev_state == "allow":
            if not self.check_usb_dev_dmesg(dmesg_txt):
                self.fail(f"sed: Disk {self.usb_disk} is not detected after allowing")
        usb_dev_state = self.get_usb_devices_state()
        if False in [state == dev_state for dev, state in usb_dev_state]:
            self.fail(f"Failed to change state of usb device to {dev_state} using sed")

    def change_usb_device_state_with_usbguard(self, dev_state, usb_device):
        """
        Changes state of usb device
        """
        dev_state_act = "block-device" if "block" in dev_state else "allow-device"
        dmesg_txt = dmesg.collect_dmesg()
        process.system(
            f"usbguard {dev_state_act} {usb_device}",
            timeout=2,
            shell=True,
            ignore_status=True
        )
        if dev_state == "allow":
            if not self.check_usb_dev_dmesg(dmesg_txt):
                self.fail(f"usbguard: Disk {self.usb_disk} is not detected after allowing")
        usb_dev_state = self.get_usb_devices_state()
        if False in [
            state == dev_state for dev, state in usb_dev_state if dev == usb_device
                ]:
            self.fail(f"Failed to change state of usb device to {dev_state} using usbguard")

    def check_usb_dev_dmesg(self, dmesg_old):
        """
        Checking for device in dmesg logs
        """
        _ = 0
        while _ < 10:
            dmesg_new = dmesg.collect_dmesg()
            diff_dmesg = process.system_output(
                f"diff {dmesg_old} {dmesg_new}",
                ignore_status=True
            ).decode('utf-8')
            if diff_dmesg:
                for line in diff_dmesg.split("\n"):
                    if self.usb_disk.split("/")[-1] in line and \
                            "Attached SCSI removable disk" in line and \
                            line.startswith(">"):
                        return True
            _ += 1
        return False

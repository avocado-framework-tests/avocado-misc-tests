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
# Copyright: 2017 IBM
# Author: Pridhiviraj Paidipeddi <ppaidipe@linux.vnet.ibm.com>

"""
Disk Info tests various storage block device list tools, and also it creates
filesystems on test disk and mount it on OS boot disk where the test code
available. Then it verifies all the tools with certain parameters like disk
name, Size, UUID, mount points and IO Sector sizes
"""

import platform
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import genio
from avocado.utils import distro
from avocado.utils.partition import Partition
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError
from avocado.utils.partition import PartitionError


class DiskInfo(Test):

    """
    DiskInfo test for different storage block device tools
    """

    def setUp(self):
        """
        Verifies if we have list of packages installed on OS
        and also skips the test if user gives the current OS boot disk as
        disk input it may erase the data
        :param disk: test disk where the disk operations can be done
        :param fs: type of filesystem to create
        :param dir: path of the directory to mount the disk device
        """
        smm = SoftwareManager()
        pkg = ""
        if 'ppc' not in platform.processor():
            self.cancel("Processor is not ppc64")
        self.disk = self.params.get('disk', default=None)
        self.dirs = self.params.get('dir', default=self.workdir)
        self.fstype = self.params.get('fs', default='ext4')
        self.log.info("disk: %s, dir: %s, fstype: %s",
                      self.disk, self.dirs, self.fstype)
        if not self.disk:
            self.cancel("No disk input, please update yaml and re-run")
        cmd = "df --output=source"
        if self.disk in process.system_output(cmd, ignore_status=True) \
                .decode("utf-8"):
            self.cancel("Given disk is os boot disk,"
                        "it will be harmful to run this test")
        pkg_list = ["lshw"]
        self.distro = distro.detect().name
        if self.distro == 'Ubuntu':
            pkg_list.append("hwinfo")
        if self.fstype == 'ext4':
            pkg_list.append('e2fsprogs')
        if self.fstype == 'xfs':
            pkg_list.append('xfsprogs')
        if self.fstype == 'btrfs':
            if self.distro == 'Ubuntu':
                pkg_list.append("btrfs-tools")
        for pkg in pkg_list:
            if pkg and not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Package %s is missing and could not be installed"
                            % pkg)

    def run_command(self, cmd):
        """
        Run command and fail the test if any command fails
        """
        try:
            process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            self.fail("Command %s failed %s" % (cmd, details))

    def test_commands(self):
        """
        Test block device tools to list different disk devices
        """
        cmd_list = ["lsblk -l", "fdisk -l", "sfdisk -l", "parted -l",
                    "df -h", "blkid", "lshw -c disk", "grub2-probe /boot"]
        if self.distro == 'Ubuntu':
            cmd_list.append("hwinfo --block --short")
        for cmd in cmd_list:
            self.run_command(cmd)

    def test(self):
        """
        Test disk devices with different operations of creating filesystem and
        mount it on a directory and verify it with certain parameters name,
        size, UUID and IO sizes etc
        """
        msg = []
        disk = (self.disk.split("/dev/"))[1]
        if process.system("ls /dev/disk/by-id -l| grep -i %s" % disk,
                          ignore_status=True, shell=True, sudo=True) != 0:
            msg.append("Given disk %s is not in /dev/disk/by-id" % disk)
        if process.system("ls /dev/disk/by-path -l| grep -i %s" % disk,
                          ignore_status=True, shell=True, sudo=True) != 0:
            msg.append("Given disk %s is not in /dev/disk/by-path" % disk)

        # Verify disk listed in all tools
        cmd_list = ["fdisk -l ", "parted -l", "lsblk ",
                    "lshw -c disk "]
        if self.distro == 'Ubuntu':
            cmd_list.append("hwinfo --short --block")
        for cmd in cmd_list:
            cmd = cmd + " | grep -i %s" % disk
            if process.system(cmd, ignore_status=True,
                              shell=True, sudo=True) != 0:
                msg.append("Given disk %s is not present in %s" % (disk, cmd))

        # Get the size and UUID of the disk
        cmd = "lsblk -l %s --output SIZE -b |sed -n 2p" % self.disk
        output = process.system_output(cmd, ignore_status=True,
                                       shell=True, sudo=True).decode("utf-8")
        if not output:
            self.cancel("No information available in lsblk")
        self.size_b = (output.strip("\n"))[0]
        self.log.info("Disk: %s Size: %s", self.disk, self.size_b)

        # Get the physical/logical and minimal/optimal sector sizes
        pbs_sysfs = "/sys/block/%s/queue/physical_block_size" % disk
        pbs = genio.read_file(pbs_sysfs).rstrip("\n")
        lbs_sysfs = "/sys/block/%s/queue/logical_block_size" % disk
        lbs = genio.read_file(lbs_sysfs).rstrip("\n")
        mis_sysfs = "/sys/block/%s/queue/minimum_io_size" % disk
        mis = genio.read_file(mis_sysfs).rstrip("\n")
        ois_sysfs = "/sys/block/%s/queue/optimal_io_size" % disk
        ois = genio.read_file(ois_sysfs).rstrip("\n")
        self.log.info("pbs: %s, lbs: %s, mis: %s, ois: %s", pbs, lbs, mis, ois)

        # Verify sector sizes
        sector_string = "Sector size (logical/physical): %s " \
                        "bytes / %s bytes" % (lbs, pbs)
        output = process.system_output("fdisk -l %s" % self.disk,
                                       ignore_status=True, shell=True,
                                       sudo=True).decode("utf-8")
        if sector_string not in output:
            msg.append("Mismatch in sector sizes of lbs,pbs in "
                       "fdisk o/p w.r.t sysfs paths")
        io_size_string = "I/O size (minimum/optimal): %s " \
                         "bytes / %s bytes" % (mis, mis)
        if io_size_string not in output:
            msg.append("Mismatch in IO sizes of mis and ois"
                       " in fdisk o/p w.r.t sysfs paths")

        # Verify disk size in other tools
        cmd = "fdisk -l %s | grep -i %s" % (self.disk, self.disk)
        if self.size_b not in process.system_output(cmd,
                                                    ignore_status=True,
                                                    shell=True,
                                                    sudo=True).decode("utf-8"):
            msg.append("Size of disk %s mismatch in fdisk o/p" % self.disk)
        cmd = "sfdisk -l %s | grep -i %s" % (self.disk, self.disk)
        if self.size_b not in process.system_output(cmd,
                                                    ignore_status=True,
                                                    shell=True,
                                                    sudo=True).decode("utf-8"):
            msg.append("Size of disk %s mismatch in sfdisk o/p" % self.disk)

        # Mount
        self.part_obj = Partition(self.disk, mountpoint=self.dirs)
        self.log.info("Unmounting disk/dir before creating file system")
        self.part_obj.unmount()
        self.log.info("creating file system")
        self.part_obj.mkfs(self.fstype)
        self.log.info("Mounting disk %s on directory %s",
                      self.disk, self.dirs)
        try:
            self.part_obj.mount()
        except PartitionError:
            msg.append("failed to mount %s fs on %s to %s" % (self.fstype,
                                                              self.disk,
                                                              self.dirs))

        # Get UUID of the disk for each filesystem mount
        cmd = "blkid %s | cut -d '=' -f 2" % self.disk
        output = process.system_output(cmd, ignore_status=True,
                                       shell=True, sudo=True).decode("utf-8")
        self.uuid = output.split('"')[1]
        self.log.info("Disk: %s UUID: %s", self.disk, self.uuid)

        # Verify mount point, filesystem type and UUID for each test variant
        output = process.system_output("lsblk -l %s" % self.disk,
                                       ignore_status=True, shell=True,
                                       sudo=True).decode("utf-8")
        if self.dirs in output:
            self.log.info("Mount point %s for disk %s updated in lsblk o/p",
                          self.dirs, self.disk)
        output = process.system_output("df %s" % self.disk,
                                       ignore_status=True, shell=True,
                                       sudo=True).decode("utf-8")
        if self.dirs in output:
            self.log.info("Mount point %s for disk %s updated in df o/p",
                          self.dirs, self.disk)

        if process.system("ls /dev/disk/by-uuid -l| grep -i %s" % disk,
                          ignore_status=True, shell=True, sudo=True) != 0:
            msg.append("Given disk %s not having uuid" % disk)

        output = process.system_output("blkid %s" % self.disk,
                                       ignore_status=True, shell=True,
                                       sudo=True).decode("utf-8")
        if (self.disk in output and self.fstype in output and
                self.uuid in output):
            self.log.info("Disk %s of file system %s and "
                          "uuid %s is updated in blkid o/p",
                          self.disk, self.fstype, self.uuid)

        if process.system("grub2-probe %s" % self.dirs, ignore_status=True):
            msg.append("Given disk %s's fs not detected by grub2" % disk)

        # Un-mount the directory
        self.log.info("Unmounting directory %s", self.dirs)
        self.part_obj.unmount()
        cmd = 'lshw -c disk | grep -n "%s" | cut -d ":" -f 1' % self.disk
        middle = process.system_output(cmd, ignore_status=True,
                                       shell=True, sudo=True)
        if middle:
            cmd = r'lshw -c disk | grep -n "\-disk" | cut -d ":" -f 1'
            total = process.system_output(cmd, ignore_status=True,
                                          shell=True, sudo=True)
            lst = total.splitlines() + middle.splitlines()
            lst.sort()
            index = lst.index(middle.splitlines()[0])
            low = lst[index-1]
            high = lst[index+1]
            cmd = "lshw -c disk |sed -n '%s, %sp'" % (low, high)
            disk_details = process.system_output(cmd, ignore_status=True,
                                                 shell=True, sudo=True)
            ls_string = "logicalsectorsize=%s sectorsize=%s" % (lbs, pbs)
            if ls_string not in disk_details:
                msg.append("Mismatch in sector sizes of lbs,pbs"
                           " in lshw o/p w.r.t sysfs paths")

        if msg:
            self.fail("Some tests failed. Details below:\n%s" % "\n".join(msg))

    def tearDown(self):
        '''
        Unmount the directory at the end if incase of test fails in between
        '''
        if hasattr(self, "part_obj"):
            if self.disk is not None:
                self.log.info("Unmounting directory %s", self.dirs)
                self.part_obj.unmount()
        self.log.info("Removing the filesystem created on %s", self.disk)
        delete_fs = "dd if=/dev/zero bs=512 count=512 of=%s" % self.disk
        if process.system(delete_fs, shell=True, ignore_status=True):
            self.fail("Failed to delete filesystem on %s", self.disk)


if __name__ == "__main__":
    main()

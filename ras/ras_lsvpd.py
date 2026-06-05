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
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>
# Author: Sachin Sant <sachinp@linux.ibm.com>
# Author: R Nageswara Sastry <rnsastry@linux.ibm.com>

import os
import re
import shutil
import fnmatch
from avocado.utils import pci
from avocado import Test
from avocado.utils import process, distro, build, archive
from avocado import skipIf
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class RASToolsLsvpd(Test):

    """
    This test checks various RAS tools bundled as a part of lsvpd
    package/repository

    :avocado: tags=ras,ppc64le
    """
    is_fail = 0

    def run_cmd(self, cmd):
        if (process.run(cmd, ignore_status=True, sudo=True,
                        shell=True)).exit_status:
            self.is_fail += 1
        return

    def setUp(self):
        """
        Ensure corresponding packages are installed
        """
        if "ppc" not in distro.detect().arch:
            self.cancel("supported only on Power platform")
        self.run_type = self.params.get('type', default='distro')
        self.sm = SoftwareManager()
        for package in ("lsvpd", "sysfsutils", "pciutils"):
            if not self.sm.check_installed(package) and not \
                    self.sm.install(package):
                self.cancel("Fail to install %s required for this"
                            " test." % package)
        self.var_lib_lsvpd_dir = "/var/lib/lsvpd/"

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True,
                                     sudo=True).decode("utf-8").strip()

    def test_build_upstream(self):
        """
        For upstream target download and compile source code
        Caution : This function will overwrite system installed
        lsvpd package binaries with upstream code.
        """
        if self.run_type == 'upstream':
            self.detected_distro = distro.detect()
            deps = ['gcc', 'make', 'automake', 'autoconf', 'bison', 'flex',
                    'libtool', 'zlib-devel', 'ncurses-devel', 'librtas-devel']
            if 'SuSE' in self.detected_distro.name:
                deps.extend(['libsgutils-devel', 'sqlite3-devel',
                             'libvpd2-devel'])
            elif self.detected_distro.name in ['centos', 'fedora', 'rhel']:
                deps.extend(['sqlite-devel', 'libvpd-devel',
                             'sg3_utils-devel'])
            else:
                self.cancel("Unsupported Linux distribution")
            for package in deps:
                if not self.sm.check_installed(package) and not \
                        self.sm.install(package):
                    self.cancel("Fail to install %s required for this test." %
                                package)
            url = self.params.get(
                'lsvpd_url', default='https://github.com/power-ras/'
                'lsvpd/archive/refs/heads/master.zip')
            tarball = self.fetch_asset('lsvpd.zip', locations=[url],
                                       expire='7d')
            archive.extract(tarball, self.workdir)
            self.sourcedir = os.path.join(self.workdir, 'lsvpd-master')
            os.chdir(self.sourcedir)
            self.run_cmd('./bootstrap.sh')
            # TODO : For now only this test is marked as failed.
            # Additional logic should be added to skip all the remaining
            # test_() functions for upstream target if source code
            # compilation fails. This will require a way to share
            # variable/data across test_() functions.
            self.run_cmd('./configure --prefix=/usr')
            if self.is_fail >= 1:
                self.fail("Source code compilation error")
            build.make(self.sourcedir)
            build.make(self.sourcedir, extra_args='install')
        else:
            self.cancel("This test is supported with upstream as a target")

    def _find_vpd_db_and_execute(self, path, cmd):
        """
        Finds vpd.db file based on the path
        And copies the vpd.db file to the outputdir, then
        executes the command along with the copyfile_path
        """
        # Equivalent Python code for bash command
        # find /var/lib/lsvpd/ -iname vpd.db | head -1
        path_db = ""
        for root, dirs, files in os.walk(path):
            for file in files:
                if file.lower() == 'vpd.db':
                    path_db = os.path.join(root, file)
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            shutil.copyfile(path_db, copyfile_path)
            self.run_cmd("%s=%s" % (cmd, copyfile_path))

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_vpdupdate(self):
        """
        Update Vital Product Data (VPD) database
        """
        self.log.info("===============Executing vpdupdate tool test===="
                      "===========")
        self.run_cmd("vpdupdate")
        list = ['--help', '--version', '--archive', '--scsi']
        for list_item in list:
            cmd = "vpdupdate %s" % list_item
            self.run_cmd(cmd)
        self._find_vpd_db_and_execute(self.var_lib_lsvpd_dir,
                                      "vpdupdate --path")
        path = ""
        var_run = '/var/lib/lsvpd/run.vpdupdate'
        run_run = '/run/run.vpdupdate'
        if os.path.exists(var_run):
            path = var_run
        elif os.path.exists(run_run):
            path = run_run
        move_path = '/root/run.vpdupdate'
        shutil.move(path, move_path)
        self.log.info("Running vpdupdate after removing run.vpdupdate")
        self.run_cmd("vpdupdate")
        shutil.move(move_path, path)
        vpd_db = '/var/lib/lsvpd/vpd.db'
        if os.path.exists(vpd_db):
            os.remove(vpd_db)
        process.run("touch %s" % vpd_db, shell=True)
        for command in ["lsvpd", "lscfg", "lsmcode"]:
            output = self.run_cmd_out(command).splitlines()
            flag = False
            for line in output:
                if 'run' in line and 'vpdupdate' in line:
                    flag = True
            if not flag:
                self.fail("Error message is not displayed when vpd.db "
                          "is corrupted.")
        self.run_cmd("vpdupdate")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in vpdupdate tool "
                      "verification" % self.is_fail)

    def _find_vpd_gzip_and_execute(self, path, cmd):
        """
        Finds vpd.*.gz file based on the path
        And execute command
        """
        # Equivalent Python code for bash command
        # find /var/lib/lsvpd/ -iname vpd.*.gz | head -1
        path_tar = ""
        for root, dirs, files in os.walk(path):
            for file in files:
                if fnmatch.fnmatch(file.lower(), 'vpd.*.gz'):
                    path_tar = os.path.join(root, file)
        if path_tar:
            self.run_cmd("%s --zip=%s" % (cmd, path_tar))
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsvpd tool verification"
                      % self.is_fail)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_lsvpd(self):
        """
        List Vital Product Data (VPD)
        """
        self.log.info("===============Executing lsvpd tool test============="
                      "==")
        self.run_cmd("vpdupdate")
        self.run_cmd("lsvpd")
        list = ['--debug', '--version', '--mark',
                '--serial=STR', '--type=STR', '--list=raid']
        for list_item in list:
            cmd = "lsvpd %s" % list_item
            self.run_cmd(cmd)
        self._find_vpd_db_and_execute(self.var_lib_lsvpd_dir, "lsvpd --path")
        self._find_vpd_gzip_and_execute(self.var_lib_lsvpd_dir, "lsvpd")

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_lscfg(self):
        """
        List hardware configuration information
        """
        self.log.info("===============Executing lscfg tool test============="
                      "==")
        self.run_cmd("lscfg")
        list = ['--debug', '--version', '-p']
        device = self.run_cmd_out('lscfg').splitlines()[-1]
        if device.startswith("+"):
            list.append("-l%s" % device.split(" ")[1])

        for list_item in list:
            cmd = "lscfg %s" % list_item
            self.run_cmd(cmd)
        self._find_vpd_db_and_execute(self.var_lib_lsvpd_dir, "lscfg --data")
        self._find_vpd_gzip_and_execute(self.var_lib_lsvpd_dir, "lscfg")

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_lsmcode(self):
        """
        lsmcode provides FW version information
        """
        self.log.info("===============Executing lsmcode tool test============="
                      "==")
        self.run_cmd("vpdupdate")
        if IS_POWER_NV:
            if 'bmc-firmware-version' not in self.run_cmd_out("lsmcode"):
                self.fail("lsmcode command failed in verification")
        elif 'FW' not in self.run_cmd_out("lsmcode"):
            self.fail("lsmcode command failed in verification")
        list = ['-A', '-v', '-D']
        for list_item in list:
            self.run_cmd('lsmcode %s' % list_item)

        if self.isAccelerator():
            self.log.info("Accelerator detected, verifying Spyre card details")
            lsmcode_output = self.run_cmd_out('lsmcode -A')
            spyre_devices = self.run_cmd_out(
                "lspci | grep -i spyre | awk '{print $1}'").strip().split('\n')
            if not spyre_devices or spyre_devices == ['']:
                self.fail("No Spyre devices found in the system")

            for device in spyre_devices:
                if device and device not in lsmcode_output:
                    self.fail(
                        f"Spyre device {device} not found in lsmcode -A output")

            self.log.info("Spyre card details verified.")

        self._find_vpd_db_and_execute(self.var_lib_lsvpd_dir, "lsmcode --path")
        self._find_vpd_gzip_and_execute(self.var_lib_lsvpd_dir, "lsmcode")

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "Not supported in PowerNV/KVM guest ")
    def test_lsvio(self):
        """
        lsvio lists the virtual I/O adopters and devices
        """
        self.log.info("===============Executing lsvio tool test============="
                      "==")
        list = ['-h', '-v', '-s', '-e', '-d']
        for list_item in list:
            self.run_cmd('lsvio %s' % list_item)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsvio tool verification"
                      % self.is_fail)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_locking_mechanism(self):
        """
        This tests database (vpd.db) locking mechanism when multiple
        instances of vpdupdate and lsvpd are running simultaneously.
        Locking mechanism prevents corruption of database file
        when running vpdupdate multiple instances
        """

        cmd = "for i in $(seq 500) ; do vpdupdate & done ;"
        ret = process.run(cmd, ignore_bg_processes=True, ignore_status=True,
                          shell=True)
        cmd1 = "for in in $(seq 200) ; do lsvpd & done ;"
        ret1 = process.run(cmd1, ignore_bg_processes=True, ignore_status=True,
                           shell=True)
        if 'SQLITE Error' in ret.stderr.decode("utf-8").strip()\
                or 'corrupt' in ret1.stdout.decode("utf-8").strip():
            self.fail("Database corruption detected")
        else:
            self.log.info("Locking mechanism prevented database corruption")

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_pci_lsvpd(self):
        '''
        Verify data from sysfs and lsvpd tool output match correctly.
        '''
        if process.system("vpdupdate",
                          ignore_status=True,
                          shell=True):
            self.fail("VPD Update fails")
        error = []
        for pci_addr in pci.get_pci_addresses():
            self.log.info("================================================")
            self.log.info("Checking PCI Address: %s", pci_addr)
            self.log.info("================================================")

            vpd_output = pci.get_vpd(pci_addr)
            if not vpd_output:
                self.log.warning("No VPD output available for %s", pci_addr)
                continue
            # Slot Validation
            if 'slot' in vpd_output:
                sys_slot = pci.get_slot_from_sysfs(pci_addr)
                if sys_slot:
                    sys_slot = sys_slot.strip('\0').strip()
                vpd_slot = vpd_output['slot'].strip()
                self.log.info("Slot from sysfs : %s", sys_slot)
                self.log.info("Slot from lsvpd : %s", vpd_slot)
                # Some systems append suffixes
                vpd_slot_base = vpd_slot
                if '-' in vpd_slot:
                    vpd_slot_base = \
                        vpd_slot[:vpd_slot.rfind('-')]

                if sys_slot in [vpd_slot,
                                vpd_slot_base]:
                    self.log.info("Slot match successful")

                else:
                    self.log.error("Slot mismatch")
                    error.append(pci_addr + "-> slot")

            else:
                self.log.warning("Slot info not found in VPD output")

            # Read PCI IDs from sysfs
            try:
                sys_vendor_id = process.system_output(
                    "cat /sys/bus/pci/devices/%s/vendor"
                    % pci_addr,
                    shell=True).decode().strip().replace(
                        "0x", "")
                sys_dev_id = process.system_output(
                    "cat /sys/bus/pci/devices/%s/device"
                    % pci_addr,
                    shell=True).decode().strip().replace(
                        "0x", "")
                sys_subvendor_id = process.system_output(
                    "cat /sys/bus/pci/devices/%s/subsystem_vendor"
                    % pci_addr,
                    shell=True).decode().strip().replace(
                        "0x", "")
                sys_subdev_id = process.system_output(
                    "cat /sys/bus/pci/devices/%s/subsystem_device"
                    % pci_addr,
                    shell=True).decode().strip().replace(
                        "0x", "")

            except Exception as e:
                self.log.error("Failed reading PCI IDs from sysfs")
                self.log.error("Exception: %s", str(e))
                error.append(pci_addr + "-> pci_sysfs_read")
                continue
            # Parse PCI IDs from VPD

            try:
                vpd_pci_id = \
                    vpd_output.get('pci_id',
                                   '').strip()
                self.log.info(
                    "Raw PCI ID from VPD : %s",
                    vpd_pci_id)
                # Expected format:
                # (10df,f500), (1014,06c2)
                matches = re.findall(
                    r'\(([^,]+),([^)]+)\)',
                    vpd_pci_id)

                if len(matches) < 2:
                    raise ValueError(
                        "Unexpected VPD PCI ID format: %s"
                        % vpd_pci_id)
                # First tuple = vendor/device
                vpd_vendor_id = matches[0][0].strip()
                vpd_dev_id = matches[0][1].strip()

                # Second tuple = subsystem vendor/device
                vpd_subvendor_id = matches[1][0].strip()
                vpd_subdev_id = matches[1][1].strip()

            except Exception as e:
                self.log.error("Failed parsing VPD PCI ID")
                self.log.error("VPD output: %s", vpd_output)
                self.log.error("Exception: %s", str(e))
                error.append(pci_addr + "-> pci_id_parse")
                continue
            # Debug Logs
            self.log.info("sys_vendor_id      = %s", sys_vendor_id)
            self.log.info("sys_dev_id         = %s", sys_dev_id)
            self.log.info("sys_subvendor_id   = %s", sys_subvendor_id)
            self.log.info("sys_subdev_id      = %s", sys_subdev_id)
            self.log.info("vpd_vendor_id      = %s", vpd_vendor_id)
            self.log.info("vpd_dev_id         = %s", vpd_dev_id)
            self.log.info("vpd_subvendor_id   = %s", vpd_subvendor_id)
            self.log.info("vpd_subdev_id      = %s", vpd_subdev_id)
            self.log.info("full_vpd_output    = %s", vpd_output)

            # Vendor ID Match
            self.log.info("Vendor ID from sysfs : %s", sys_vendor_id)
            self.log.info("Vendor ID from VPD   : %s", vpd_vendor_id)

            if sys_vendor_id == vpd_vendor_id:
                self.log.info("Vendor ID match successful")

            else:
                self.log.error("Vendor ID mismatch")
                error.append(pci_addr + "-> Vendor_id")

            # Device ID Match
            self.log.info("Device ID from sysfs : %s", sys_dev_id)
            self.log.info("Device ID from VPD   : %s", vpd_dev_id)

            if sys_dev_id == vpd_dev_id:
                self.log.info("Device ID match successful")

            else:
                self.log.error("Device ID mismatch")
                error.append(pci_addr + "-> Device_id")

            # Subvendor ID Match
            self.log.info("Subvendor ID from sysfs : %s", sys_subvendor_id)
            self.log.info("Subvendor ID from VPD   : %s", vpd_subvendor_id)
            if sys_subvendor_id == vpd_subvendor_id:
                self.log.info("Subvendor ID match successful")

            else:
                self.log.error("Subvendor ID mismatch")
                error.append(pci_addr + "-> Subvendor_id")

            # Subdevice ID Match
            self.log.info("Subdevice ID from sysfs : %s", sys_subdev_id)
            self.log.info("Subdevice ID from VPD   : %s", vpd_subdev_id)
            if sys_subdev_id == vpd_subdev_id:
                self.log.info("Subdevice ID match successful")
            else:
                self.log.error("Subdevice ID mismatch")
                error.append(pci_addr + "-> Subdevice_id")

            # PCI Config Space Validation
            cmd = "lspci -xxxx -s %s" % pci_addr
            self.log.info(
                "Checking PCI config space using: %s",
                cmd)
            if process.system(cmd,
                              ignore_status=True,
                              sudo=True):
                self.log.error("PCI config space read failed")
                error.append(
                    pci_addr +
                    "-> pci_config_space")

        if error:
            self.fail(
                "Errors for above pci addresses: %s"
                % error)
        self.log.info(
            "All PCI VPD checks passed successfully")

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_pci_lscfg(self):
        '''
        Capture data from lscfg and lspci then compare data
        '''
        error = []
        for pci_addr in pci.get_pci_addresses():
            self.log.info("================================================")
            self.log.info("Checking PCI Address: %s", pci_addr)
            self.log.info("================================================")
            try:
                raw_lscfg = process.run(
                    "lscfg -vl %s" % pci_addr,
                    sudo=True,
                    shell=True).stdout_text
                self.log.info(
                    "RAW LSCFG OUTPUT:\n%s",
                    raw_lscfg)
            except Exception as e:
                self.log.error(
                    "Failed to collect lscfg output "
                    "for %s", pci_addr)
                self.log.error(str(e))
                error.append(pci_addr + "-> raw_lscfg")
                continue

            try:
                pci_info_dict = pci.get_pci_info(pci_addr)
                self.log.info(
                    "PCI INFO DICT : %s", pci_info_dict)
            except Exception as e:
                self.log.error(
                    "Failed to get pci info for %s", pci_addr)
                self.log.error(str(e))
                error.append(pci_addr + "-> pci_info")
                continue

            try:
                match = re.search(
                    r'\(([0-9a-fA-F]{4}),([0-9a-fA-F]{4})\),\s*'
                    r'\(([0-9a-fA-F]{4}),([0-9a-fA-F]{4})\)',
                    raw_lscfg)
                if not match:
                    self.log.error(
                        "Failed to parse PCI IDs "
                        "from lscfg output")
                    error.append(pci_addr + "-> pci_id_parse")
                    continue

                vendor_id = match.group(1).lower()
                device_id = match.group(2).lower()
                subvendor_id = match.group(3).lower()
                subdevice_id = match.group(4).lower()
                self.log.info("vendor_id      = %s", vendor_id)
                self.log.info("device_id      = %s", device_id)
                self.log.info("subvendor_id   = %s", subvendor_id)
                self.log.info("subdevice_id   = %s", subdevice_id)
            except Exception as e:
                self.log.error("PCI ID parsing failed for %s", pci_addr)
                self.log.error(str(e))
                error.append(pci_addr + "-> pci_parse")
                continue

            try:
                yl_match = re.search(
                    r'Location Code\.\(YL\)\.*([A-Za-z0-9\.\-\:]+)',
                    raw_lscfg)
                if yl_match:
                    yl_value = yl_match.group(1).strip()
                else:
                    yl_value = ""
                self.log.info("YL Value = %s", yl_value)
            except Exception as e:
                self.log.error("YL parse failed for %s", pci_addr)
                self.log.error(str(e))
                yl_value = ""

            if 'Vendor' in pci_info_dict:
                self.log.info(
                    "Vendor ID from lspci : %s",
                    pci_info_dict['Vendor'])
                if vendor_id == pci_info_dict['Vendor'].lower():
                    self.log.info("Vendor ID matched")
                else:
                    self.log.error("Vendor ID mismatch")
                    error.append(pci_addr + "-> vendor_id")

            if 'Device' in pci_info_dict:
                self.log.info(
                    "Device ID from lspci : %s",
                    pci_info_dict['Device'])
                if device_id == pci_info_dict['Device'].lower():
                    self.log.info("Device ID matched")
                else:
                    self.log.error("Device ID mismatch")
                    error.append(pci_addr + "-> device_id")

            if 'SVendor' in pci_info_dict:
                self.log.info(
                    "Subvendor ID from lspci : %s",
                    pci_info_dict['SVendor'])
                if subvendor_id == pci_info_dict['SVendor'].lower():
                    self.log.info("Subvendor ID matched")
                else:
                    self.log.error("Subvendor ID mismatch")
                    error.append(pci_addr + "-> subvendor_id")

            if 'SDevice' in pci_info_dict:
                self.log.info(
                    "Subdevice ID from lspci : %s",
                    pci_info_dict['SDevice'])
                if subdevice_id == pci_info_dict['SDevice'].lower():
                    self.log.info("Subdevice ID matched")
                else:
                    self.log.error("Subdevice ID mismatch")
                    error.append(pci_addr + "-> subdevice_id")

            if ('PhySlot' in pci_info_dict and yl_value):
                physlot = pci_info_dict['PhySlot']
                self.log.info("PhySlot from lspci : %s", physlot)
                if physlot in yl_value:
                    self.log.info("Physical Slot matched")
                else:
                    self.log.error("Physical Slot mismatch")
                    error.append(pci_addr + "-> physical_slot")

            cmd = "lspci -xxxx -s %s" % pci_addr
            self.log.info("Running command: %s", cmd)
            if process.system(
                    cmd,
                    sudo=True,
                    ignore_status=True):
                self.log.error("PCI config space read failed")
                error.append(pci_addr + "-> pci_config_space")

        if error:
            self.fail("Errors for above pci addresses: %s" % error)
        self.log.info("All PCI lscfg checks passed successfully")

    def isAccelerator(self):
        for dev in os.listdir('/sys/bus/pci/devices'):
            try:
                if pci.get_pci_class_name(dev) == "accelerator":
                    return True
            except Exception:
                pass
        return False

    def extract_spyre_block(self, lsvpd_out, location_codes):
        spyre_blocks, current_block, address = {}, [], ""
        location_codes_set = set(location_codes)

        def process_block():
            if not (current_block and address):
                return
            for line in current_block:
                if '*YL' in line:
                    yl_value = line.split()[-1]
                    if yl_value in location_codes_set:
                        spyre_blocks[address] = current_block
                        break

        for line in lsvpd_out.splitlines():
            if '*FC' in line:
                process_block()
                current_block = []
                address = ""
            current_block.append(line)
            if '*AX' in line and not address:
                ax_value = line.split()[-1]
                if ':' in ax_value and '.' in ax_value:
                    address = ax_value

        process_block()
        return spyre_blocks

    def parse_lscfg_output(self, lscfg_out):
        data = {}
        current_key = None

        for line in lscfg_out.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            if stripped[0] == '.':
                value = stripped.lstrip('.')
                if current_key and value:
                    data[current_key] = value
                    current_key = None
                continue

            key_chars = []
            value_chars = []
            in_value = False
            dot_count = 0

            for char in stripped:
                if not in_value:
                    if char == '.':
                        dot_count += 1
                        if dot_count >= 2:
                            in_value = True
                    else:
                        if dot_count > 0:
                            key_chars.extend(['.'] * dot_count)
                            dot_count = 0
                        key_chars.append(char)
                else:
                    value_chars.append(char)

            key = ''.join(key_chars).strip()
            value = ''.join(value_chars).lstrip('.')

            if key:
                if key.endswith(')') and '(' in key:
                    paren_idx = key.rfind('(')
                    short_key = key[paren_idx+1:-1]
                    if value:
                        data[short_key] = value
                        current_key = None
                    else:
                        current_key = short_key
                else:
                    if value:
                        data[key] = value
                        current_key = None
                    else:
                        current_key = key

        return data

    def parse_lsvpd_block(self, block):
        data, missing_values = {}, []

        for line in block:
            stripped = line.strip()
            if not stripped.startswith('*'):
                continue

            parts = stripped.split(None, 1)
            key = parts[0].lstrip('*')

            if len(parts) < 2:
                missing_values.append(key)
                data[key] = None
                continue

            value = parts[1].strip()

            if key in data:
                if not isinstance(data[key], list):
                    data[key] = [data[key]]
                data[key].append(value)
            else:
                data[key] = value

        if missing_values:
            data['missing_fields'] = missing_values

        return data

    @skipIf("ppc" not in os.uname()[4], "Skip, Powerpc specific tests")
    @skipIf(lambda self: not self.isAccelerator(), "Unsupported: PCI adapter is not an accelerator")
    def test_spyre_lsvpd_validation(self):
        self.run_cmd("vpdupdate")

        lsvpd_out = self.run_cmd_out("lsvpd")
        location_codes = []
        pci_addresses = []
        failures = []

        for dev in pci.get_pci_addresses():
            try:
                class_name = pci.get_pci_class_name(dev)
                if class_name == "accelerator":
                    lscfg_out = self.run_cmd_out(f"lscfg -vl {dev}")
                    cfg_output = self.parse_lscfg_output(lscfg_out)
                    if 'YL' in cfg_output:
                        location_codes.append(cfg_output['YL'])
                        pci_addresses.append(dev)
            except Exception as e:
                self.log.warning(f"Failed to get config for {dev}: {e}")
                continue

        spyre_blocks = self.extract_spyre_block(lsvpd_out, location_codes)
        if not spyre_blocks:
            failures.append("No lsvpd entry found for the Spyre card(s).")

        for dev in pci_addresses:
            if dev not in spyre_blocks:
                failures.append(f"{dev}: No lsvpd block found for this device")
                continue

            spyre_block = spyre_blocks[dev]
            lsvpd_data = self.parse_lsvpd_block(spyre_block)

            if 'missing_fields' in lsvpd_data:
                missing = ', '.join(lsvpd_data['missing_fields'])
                failures.append(
                    f"{dev}: lsvpd fields missing values: {missing}")

            lscfg_out = self.run_cmd_out(f"lscfg -vl {dev}")
            lscfg_data = self.parse_lscfg_output(lscfg_out)

            validations = {
                'TM': 'Machine Type-Model',
                'MF': 'Manufacturer Name',
                'PN': 'Part Number of assembly',
                'SN': 'Serial Number',
                'FN': 'Field Replaceable Unit Number',
                'EC': 'Engineering Change Level',
                'RL': 'Non-alterable ROM level',
                'CC': 'CC',
                'YC': 'YC',
                'YL': 'YL'
            }

            for lsvpd_key, lscfg_key in validations.items():
                if lsvpd_key in lsvpd_data and lscfg_key in lscfg_data:
                    lsvpd_val = lsvpd_data[lsvpd_key]
                    if isinstance(lsvpd_val, list):
                        lsvpd_val = lsvpd_val[0]
                    if lsvpd_val.strip() != lscfg_data[lscfg_key].strip():
                        failures.append(
                            f"{dev}: {lsvpd_key} mismatch - lsvpd: {lsvpd_val}, lscfg: {lscfg_data[lscfg_key]}")

        if failures:
            fail_msg = "Spyre device validation failed:\n" + \
                "\n".join(failures)
            self.fail(fail_msg)

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
        if process.system("vpdupdate", ignore_status=True, shell=True):
            self.fail("VPD Update fails")

        error = []
        for pci_addr in pci.get_pci_addresses():
            self.log.info("Checking for PCI Address: %s\n\n", pci_addr)
            vpd_output = pci.get_vpd(pci_addr)
            if vpd_output:

                # Slot Match
                if 'slot' in vpd_output:
                    sys_slot = pci.get_slot_from_sysfs(pci_addr)
                    if sys_slot:
                        sys_slot = sys_slot.strip('\0')
                    vpd_slot = vpd_output['slot']
                    self.log.info("Slot from sysfs: %s", sys_slot)
                    self.log.info("Slot from lsvpd: %s", vpd_slot)
                    if sys_slot in [sys_slot, vpd_slot[:vpd_slot.rfind('-')]]:
                        self.log.info("=======>>> slot matches perfectly\n\n")
                    else:
                        error.append(pci_addr + "-> slot")
                        self.log.info("--->>Slot Numbers not Matched\n\n")
                else:
                    self.log.error("Slot info not available in vpd output\n")

                # Device ID match
                sys_pci_id_output = pci.get_pci_id_from_sysfs(pci_addr)
                vpd_dev_id = vpd_output['pci_id'][4:]
                sysfs_dev_id = sys_pci_id_output[5:-10]
                sysfs_sdev_id = sys_pci_id_output[15:]
                self.log.info("Device ID from sysfs: %s", sysfs_dev_id)
                self.log.info("Sub Device ID from sysfs: %s", sysfs_sdev_id)
                self.log.info("Device ID from vpd: %s", vpd_dev_id)
                if vpd_dev_id == sysfs_sdev_id or vpd_dev_id == sysfs_dev_id:
                    self.log.info("=======>>Device ID Match Success\n\n")
                else:
                    self.log.error("----->>Device ID did not Match\n\n")
                    error.append(pci_addr + "-> Device_id")

                # Subvendor ID Match
                sysfs_subvendor_id = sys_pci_id_output[10:-5]
                vpd_subvendor_id = vpd_output['pci_id'][:4]
                self.log.info("Subvendor ID frm sysfs: %s", sysfs_subvendor_id)
                self.log.info("Subvendor ID from vpd : %s", vpd_subvendor_id)
                if sysfs_subvendor_id == vpd_subvendor_id:
                    self.log.info("======>>>Subvendor ID Match Success\n\n")
                else:
                    self.log.error("---->>Subvendor_id Not Matched\n\n")
                    error.append(pci_addr + "-> Subvendor_id")

                # PCI ID Match
                lspci_pci_id = pci.get_pci_id(pci_addr)
                self.log.info(" PCI ID from Sysfs: %s", sys_pci_id_output)
                self.log.info("PCI ID from Vpd : %s", lspci_pci_id)

                if sys_pci_id_output == lspci_pci_id:
                    self.log.info("======>>>> All PCI ID match Success\n\n")
                else:
                    self.log.error("---->>>PCI info Did not Matches\n\n")
                    error.append(pci_addr + "-> pci_id")

                # PCI Config Space Check
                if process.system("lspci -xxxx -s %s" % pci_addr,
                                  ignore_status=True, sudo=True):
                    error.append(pci_addr + "->pci_config_space")

        if error:
            self.fail("Errors for above pci addresses: %s" % error)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_pci_lscfg(self):
        '''
        Capture data from lscfg and lspci then compare data
        '''
        error = []
        for pci_addr in pci.get_pci_addresses():
            self.log.info("Checking for PCI Address: %s\n\n", pci_addr)
            pci_info_dict = pci.get_pci_info(pci_addr)
            self.log.info(pci_info_dict)
            cfg_output = pci.get_cfg(pci_addr)
            self.log.info(cfg_output)
            if cfg_output and pci_info_dict:
                if 'YL' in cfg_output and 'PhySlot' in pci_info_dict:
                    # Physical Slot Match
                    self.log.info("Physical Slot from lscfg is %s"
                                  " and lspci is %s",
                                  cfg_output['YL'], pci_info_dict['PhySlot'])
                    cfg_output['YL'] = \
                        cfg_output['YL'][:cfg_output['YL'].rfind('-')]
                    if (cfg_output['YL'] == pci_info_dict['PhySlot']):
                        self.log.info("Physical Slot matched")
                    else:
                        error.append("Physical slot info didn't match")
                # Sub Device ID match
                if ('subvendor_device' in cfg_output and
                        'SDevice' in pci_info_dict):
                    self.log.info("Device iD from lscfg is %s"
                                  " and lspci is %s",
                                  cfg_output['subvendor_device'][4:],
                                  pci_info_dict['SDevice'])
                    if (cfg_output['subvendor_device'][4:]
                       == pci_info_dict['SDevice']):
                        self.log.info("Sub Device ID matched")
                    else:
                        error.append("Device ID info didn't match")
                # Subvendor ID Match
                if ('subvendor_device' in cfg_output and
                        'SVendor' in pci_info_dict):
                    self.log.info("Subvendor ID from lscfg is %s"
                                  "and lspci is %s",
                                  cfg_output['subvendor_device'],
                                  pci_info_dict['SVendor'])
                    if (cfg_output['subvendor_device'][0:4] ==
                            pci_info_dict['SVendor']):
                        self.log.info("Sub vendor ID matched")
                    else:
                        error.append("Sub vendor ID didn't match")
                # PCI Slot ID Match
                if 'pci_id' in cfg_output and 'Slot' in pci_info_dict:
                    self.log.info("PCI ID from lscfg is %s and lspci is %s",
                                  cfg_output['pci_id'], pci_info_dict['Slot'])
                    if (cfg_output['pci_id'] ==
                       pci_info_dict['Slot']):
                        self.log.info("PCI Slot ID matched")
                    else:
                        error.append("PCI slot ID didn't match")
                # PCI Config Space Check
                if process.system(f"lspci -xxxx -s {pci_addr}",
                                  sudo=True):
                    error.append(pci_addr + " : pci_config_space")
        if error:
            self.fail(f"Errors for above pci addresses: {error}")

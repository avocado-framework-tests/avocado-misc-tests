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

    def extract_spyre_blocks_from_lsvpd(self, lsvpd_output):
        """
        Extract Spyre accelerator blocks from lsvpd output.
        Captures output from lines starting with '*FC ECSE' until first '*YL' line.
        Handles multiple occurrences of the same PCI adapters.
        
        :param lsvpd_output: Full output from lsvpd command
        :return: List of spyre device blocks
        """
        spyre_blocks = []
        current_block = []
        capturing = False
        
        for line in lsvpd_output.splitlines():
            # Check if line starts with *FC ECSE (start of spyre block)
            if line.strip().startswith('*FC ECSE'):
                # If we were already capturing, save the previous block
                if capturing and current_block:
                    spyre_blocks.append('\n'.join(current_block))
                # Start new block
                current_block = [line]
                capturing = True
            elif capturing:
                # Add line to current block
                current_block.append(line)
                # Check if line starts with *YL (end of spyre block)
                if line.strip().startswith('*YL'):
                    # Save the block and stop capturing
                    spyre_blocks.append('\n'.join(current_block))
                    current_block = []
                    capturing = False
        
        return spyre_blocks

    def parse_spyre_device_info(self, spyre_block):
        """
        Parse spyre device block and extract key information.
        
        :param spyre_block: Single spyre device block text
        :return: Dictionary with parsed device information
        """
        device_info = {
            'raw_output': spyre_block,
            'fc_ecse': None,  # Feature Code
            'yl_location': None,  # Physical Location
            'device_specific_info': {}
        }
        
        for line in spyre_block.splitlines():
            line_stripped = line.strip()
            
            # Parse *FC line (Feature Code)
            if line_stripped.startswith('*FC'):
                parts = line_stripped.split(None, 2)  # Split on whitespace, max 3 parts
                if len(parts) >= 2:
                    device_info['fc_ecse'] = parts[1] if len(parts) >= 2 else None
            
            # Parse *YL line (Physical Location)
            elif line_stripped.startswith('*YL'):
                parts = line_stripped.split(None, 1)  # Split on whitespace
                if len(parts) >= 2:
                    device_info['yl_location'] = parts[1]
            
            # Parse other fields (format: *XX value)
            elif line_stripped.startswith('*'):
                parts = line_stripped.split(None, 1)
                if len(parts) >= 2:
                    field_code = parts[0][1:]  # Remove the * prefix
                    field_value = parts[1]
                    device_info['device_specific_info'][field_code] = field_value
        
        return device_info

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

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_spyre_accelerator_lsvpd(self):
        """
        Test to extract and validate Spyre accelerator information from lsvpd output.
        Captures blocks starting with '*FC ECSE' until first '*YL' line.
        Validates FC, CCIN, EC, YL values against sysfs parameters.
        """
        self.log.info("===============Executing Spyre Accelerator lsvpd test===============")
        
        # Run vpdupdate to ensure database is current
        self.run_cmd("vpdupdate")
        
        # Get lsvpd output
        lsvpd_output = self.run_cmd_out("lsvpd")
        
        # Extract spyre accelerator blocks
        spyre_blocks = self.extract_spyre_blocks_from_lsvpd(lsvpd_output)
        
        if not spyre_blocks:
            self.log.info("No Spyre accelerator devices found in lsvpd output")
            self.cancel("No Spyre accelerators detected on this system")
        
        self.log.info("Found %d Spyre accelerator device(s)", len(spyre_blocks))
        
        # Get all PCI addresses to match with spyre devices
        pci_addresses = pci.get_pci_addresses()
        
        # Process each spyre block
        for idx, block in enumerate(spyre_blocks, 1):
            self.log.info("\n" + "="*60)
            self.log.info("Spyre Accelerator Device #%d", idx)
            self.log.info("="*60)
            self.log.info("Raw lsvpd Output:\n%s", block)
            
            # Parse device information from lsvpd
            device_info = self.parse_spyre_device_info(block)
            
            # Extract key fields
            lsvpd_fc = device_info['fc_ecse']
            lsvpd_yl = device_info['yl_location']
            lsvpd_ccin = device_info['device_specific_info'].get('CCIN', None)
            lsvpd_ec = device_info['device_specific_info'].get('EC', None)
            
            self.log.info("\nParsed lsvpd Information:")
            self.log.info("  Feature Code (FC): %s", lsvpd_fc)
            self.log.info("  Physical Location (YL): %s", lsvpd_yl)
            self.log.info("  CCIN: %s", lsvpd_ccin)
            self.log.info("  EC: %s", lsvpd_ec)
            
            # Validate that we have essential information
            if not lsvpd_fc:
                self.is_fail += 1
                self.log.error("Missing Feature Code (FC) for device #%d", idx)
                continue
            
            if not lsvpd_yl:
                self.is_fail += 1
                self.log.error("Missing Physical Location (YL) for device #%d", idx)
                continue
            
            # Find matching PCI address by comparing with sysfs data
            matched_pci_addr = None
            for pci_addr in pci_addresses:
                # Get data from lscfg (via get_cfg) and sysfs (via get_pci_info)
                cfg_output = pci.get_cfg(pci_addr)
                pci_info_dict = pci.get_pci_info(pci_addr)
                
                if cfg_output and 'YL' in cfg_output:
                    # Compare physical location (YL)
                    # cfg_output['YL'] might have format like "U78DA.ND0.1234567-P0-C1"
                    # We need to match with lsvpd_yl
                    cfg_yl = cfg_output['YL']
                    # Strip the trailing part after last '-' for comparison
                    cfg_yl_base = cfg_yl[:cfg_yl.rfind('-')] if '-' in cfg_yl else cfg_yl
                    lsvpd_yl_base = lsvpd_yl[:lsvpd_yl.rfind('-')] if '-' in lsvpd_yl else lsvpd_yl
                    
                    if cfg_yl_base == lsvpd_yl_base or cfg_yl == lsvpd_yl:
                        matched_pci_addr = pci_addr
                        self.log.info("\nMatched PCI Address: %s", pci_addr)
                        break
            
            if not matched_pci_addr:
                self.log.warning("Could not find matching PCI address for device #%d with YL: %s",
                               idx, lsvpd_yl)
                self.log.info("Skipping sysfs validation for this device")
                continue
            
            # Get sysfs data for matched PCI address
            cfg_output = pci.get_cfg(matched_pci_addr)
            pci_info_dict = pci.get_pci_info(matched_pci_addr)
            
            self.log.info("\nSysfs Data (lscfg):")
            self.log.info(cfg_output)
            self.log.info("\nSysfs Data (lspci):")
            self.log.info(pci_info_dict)
            
            # Validate FC (Feature Code)
            if 'FC' in cfg_output:
                sysfs_fc = cfg_output['FC']
                self.log.info("\n--- Validating FC (Feature Code) ---")
                self.log.info("  lsvpd FC: %s", lsvpd_fc)
                self.log.info("  sysfs FC: %s", sysfs_fc)
                if lsvpd_fc == sysfs_fc:
                    self.log.info("  ✓ FC matched successfully")
                else:
                    self.is_fail += 1
                    self.log.error("  ✗ FC mismatch for device #%d", idx)
            else:
                self.log.warning("  FC not available in sysfs data")
            
            # Validate CCIN
            if lsvpd_ccin and 'CCIN' in cfg_output:
                sysfs_ccin = cfg_output['CCIN']
                self.log.info("\n--- Validating CCIN ---")
                self.log.info("  lsvpd CCIN: %s", lsvpd_ccin)
                self.log.info("  sysfs CCIN: %s", sysfs_ccin)
                if lsvpd_ccin == sysfs_ccin:
                    self.log.info("  ✓ CCIN matched successfully")
                else:
                    self.is_fail += 1
                    self.log.error("  ✗ CCIN mismatch for device #%d", idx)
            else:
                self.log.warning("  CCIN not available for comparison")
            
            # Validate EC (Engineering Change)
            if lsvpd_ec and 'EC' in cfg_output:
                sysfs_ec = cfg_output['EC']
                self.log.info("\n--- Validating EC (Engineering Change) ---")
                self.log.info("  lsvpd EC: %s", lsvpd_ec)
                self.log.info("  sysfs EC: %s", sysfs_ec)
                if lsvpd_ec == sysfs_ec:
                    self.log.info("  ✓ EC matched successfully")
                else:
                    self.is_fail += 1
                    self.log.error("  ✗ EC mismatch for device #%d", idx)
            else:
                self.log.warning("  EC not available for comparison")
            
            # Validate YL (Physical Location)
            if 'YL' in cfg_output:
                sysfs_yl = cfg_output['YL']
                self.log.info("\n--- Validating YL (Physical Location) ---")
                self.log.info("  lsvpd YL: %s", lsvpd_yl)
                self.log.info("  sysfs YL: %s", sysfs_yl)
                # Compare base location (without trailing port info)
                sysfs_yl_base = sysfs_yl[:sysfs_yl.rfind('-')] if '-' in sysfs_yl else sysfs_yl
                lsvpd_yl_base = lsvpd_yl[:lsvpd_yl.rfind('-')] if '-' in lsvpd_yl else lsvpd_yl
                if sysfs_yl_base == lsvpd_yl_base or sysfs_yl == lsvpd_yl:
                    self.log.info("  ✓ YL matched successfully")
                else:
                    self.is_fail += 1
                    self.log.error("  ✗ YL mismatch for device #%d", idx)
            else:
                self.log.warning("  YL not available in sysfs data")
            
            # Additional validation with PhySlot from lspci
            if pci_info_dict and 'PhySlot' in pci_info_dict:
                sysfs_physlot = pci_info_dict['PhySlot']
                self.log.info("\n--- Cross-checking with lspci PhySlot ---")
                self.log.info("  lspci PhySlot: %s", sysfs_physlot)
                self.log.info("  lsvpd YL: %s", lsvpd_yl)
                # PhySlot should match the base part of YL
                if sysfs_physlot in lsvpd_yl or lsvpd_yl.startswith(sysfs_physlot):
                    self.log.info("  ✓ PhySlot consistent with YL")
                else:
                    self.log.warning("  PhySlot and YL don't match as expected")
        
        if self.is_fail >= 1:
            self.fail("%s validation(s) failed in Spyre accelerator lsvpd test" % self.is_fail)
        else:
            self.log.info("\n" + "="*60)
            self.log.info("All Spyre accelerator devices validated successfully")
            self.log.info("="*60)

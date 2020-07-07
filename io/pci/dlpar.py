#!/usr/bin/python

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
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>

"""
DLPAR operations
"""

import os
import shutil
from avocado import Test
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.ssh import Session
from avocado.utils import pci
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError


class DlparPci(Test):
    '''
    DLPAR PCI script does pci add,remove and also move operation from one
    lpar to another lpar. Update the details in yaml file.
    For move operation, please configure another lpar and update in yaml file.
    And also make sure both rsct and rsct_rm services up and running
    '''

    def setUp(self):
        '''
        Gather necessary test inputs.
        Test all services.
        '''
        self.install_packages()
        self.rsct_service_start()
        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel("HMC IP not got")
        self.hmc_user = self.params.get("hmc_username", default='hscroot')
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default='********')
        self.sriov = self.params.get("sriov", default="no")
        self.lpar_1 = self.get_partition_name("Partition Name")
        if not self.lpar_1:
            self.cancel("LPAR Name not got from lparstat command")
        self.session = Session(self.hmc_ip, user=self.hmc_user,
                               password=self.hmc_pwd)
        if not self.session.connect():
            self.cancel("failed connecting to HMC")
        cmd = 'lssyscfg -r sys  -F name'
        output = self.session.cmd(cmd)
        self.server = ''
        for line in output.stdout_text.splitlines():
            if line in self.lpar_1:
                self.server = line
                break
        if not self.server:
            self.cancel("Managed System not got")
        self.lpar_2 = self.params.get("lpar_2", '*', default=None)
        if self.lpar_2 is not None:
            cmd = 'lshwres -r io -m %s --rsubtype slot --filter \
                   lpar_names=%s -F lpar_id' % (self.server, self.lpar_2)
            output = self.session.cmd(cmd)
            self.lpar2_id = output.stdout_text[0]
        self.pci_device = self.params.get("pci_device", '*', default=None)
        self.loc_code = pci.get_slot_from_sysfs(self.pci_device)
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        if self.loc_code is None:
            self.cancel("Failed to get the location code for the pci device")
        self.session.cmd("uname -a")
        if self.sriov == "yes":
            cmd = "lshwres -r sriov --rsubtype logport -m %s \
            --level eth --filter lpar_names=%s -F \
            'adapter_id,logical_port_id,phys_port_id,lpar_id,location_code,drc_name'" \
                   % (self.server, self.lpar_1)
            output = self.session.cmd(cmd)
            for line in output.stdout_text.splitlines():
                if self.loc_code in line:
                    self.adapter_id = line.split(',')[0]
                    self.logical_port_id = line.split(',')[1]
                    self.phys_port_id = line.split(',')[2]
                    self.lpar_id = line.split(',')[3]
                    self.location_code = line.split(',')[4]
                    self.phb = line.split(',')[5].split(' ')[1]
                    break
            self.log.info("lpar_id : %s, loc_code: %s",
                          self.lpar_id, self.loc_code)
        else:
            cmd = 'lshwres -r io -m %s --rsubtype slot \
                   --filter lpar_names=%s -F drc_index,lpar_id,drc_name,bus_id' \
                   % (self.server, self.lpar_1)
            output = self.session.cmd(cmd)
            for line in output.stdout_text.splitlines():
                if self.loc_code in line:
                    self.drc_index = line.split(',')[0]
                    self.lpar_id = line.split(',')[1]
                    self.phb = line.split(',')[3]
                    break

            self.log.info("lpar_id : %s, loc_code: %s, drc_index: %s, phb: %s",
                          self.lpar_id, self.loc_code, self.drc_index,
                          self.phb)

    @staticmethod
    def get_mcp_component(component):
        '''
        probes IBM.MCP class for mentioned component and returns it.
        '''
        for line in process.system_output('lsrsrc IBM.MCP %s' % component,
                                          ignore_status=True, shell=True,
                                          sudo=True).decode("utf-8") \
                                                    .splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def get_partition_name(component):
        '''
        get partition name from lparstat -i
        '''

        for line in process.system_output('lparstat -i',
                                          ignore_status=True, shell=True,
                                          sudo=True).decode("utf-8") \
                                                    .splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    def install_packages(self):
        '''
        Install required packages
        '''
        smm = SoftwareManager()
        packages = ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                    'rsct.core', 'DynamicRM', 'pciutils']
        detected_distro = distro.detect()
        if detected_distro.name == "Ubuntu":
            packages.extend(['python-paramiko'])
        self.log.info("Test is running on: %s", detected_distro.name)
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)
        if detected_distro.name == "Ubuntu":
            ubuntu_url = self.params.get('ubuntu_url', default=None)
            debs = self.params.get('debs', default=None)
            for deb in debs:
                deb_url = os.path.join(ubuntu_url, deb)
                deb_install = self.fetch_asset(deb_url, expire='7d')
                shutil.copy(deb_install, self.workdir)
                process.system("dpkg -i %s/%s" % (self.workdir, deb),
                               ignore_status=True, sudo=True)

    def rsct_service_start(self):
        '''
        Start required services
        '''
        try:
            process.run("startsrc -g rsct", shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.cancel("Command startsrc -g rsct failed")

        try:
            process.run("startsrc -g rsct_rm", shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.cancel("Command startsrc -g rsct_rm failed")

        output = process.system_output("lssrc -a", ignore_status=True,
                                       shell=True, sudo=True).decode("utf-8")

        if "inoperative" in output:
            self.cancel("Failed to start the rsct and rsct_rm services")

    def test_dlpar(self):
        '''
        DLPAR remove, add and move operations from lpar_1 to lpar_2
        '''
        for _ in range(self.num_of_dlpar):
            self.dlpar_remove()
            self.dlpar_add()
            self.dlpar_move()

    def test_drmgr_pci(self):
        '''
        drmgr remove, add and replace operations
        '''
        for _ in range(self.num_of_dlpar):
            self.do_drmgr_pci('r')
            self.do_drmgr_pci('a')
        for _ in range(self.num_of_dlpar):
            self.do_drmgr_pci('R')

    def test_drmgr_phb(self):
        '''
        drmgr remove, add and replace operations
        '''
        for _ in range(self.num_of_dlpar):
            self.do_drmgr_phb('r')
            self.do_drmgr_phb('a')

    def do_drmgr_pci(self, operation):
        '''
        drmgr operation for pci
        '''
        cmd = "echo -e \"\n\" | drmgr -c pci -s %s -%s" % (self.loc_code,
                                                           operation)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail("drmgr operation %s fails for PCI" % operation)

    def do_drmgr_phb(self, operation):
        '''
        drmgr operation for phb
        '''
        cmd = "drmgr -c phb -s \"PHB %s\" -%s" % (self.phb, operation)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail("drmgr operation %s fails for PHB" % operation)

    def dlpar_remove(self):
        '''
        dlpar remove operation
        '''
        if self.sriov == "yes":
            self.changehwres_sriov(self.server, 'r', self.lpar_id,
                                   self.adapter_id, self.logical_port_id,
                                   self.phys_port_id, 'remove')
            output = self.listhwres_sriov(self.server, self.lpar_1,
                                          self.logical_port_id)
            if output:
                self.log.debug(output)
                self.fail("lshwres still lists the drc after dlpar remove")
        else:
            self.changehwres(self.server, 'r', self.lpar_id, self.lpar_1,
                             self.drc_index, 'remove')
            output = self.listhwres(self.server, self.lpar_1, self.drc_index)
            if output:
                self.log.debug(output)
                self.fail("lshwres still lists the drc after dlpar remove")

    def dlpar_add(self):
        '''
        dlpar add operation
        '''
        if self.sriov == "yes":
            self.changehwres_sriov(self.server, 'a', self.lpar_id,
                                   self.adapter_id, self.logical_port_id,
                                   self.phys_port_id, 'add')
            output = self.listhwres_sriov(self.server, self.lpar_1,
                                          self.logical_port_id)
            if self.logical_port_id not in output:
                self.log.debug(output)
                self.fail("lshwres fails to list the drc after dlpar add")
        else:
            self.changehwres(self.server, 'a', self.lpar_id, self.lpar_1,
                             self.drc_index, 'add')
            output = self.listhwres(self.server, self.lpar_1, self.drc_index)
            if self.drc_index not in output:
                self.log.debug(output)
                self.fail("lshwres fails to list the drc after dlpar add")

    def dlpar_move(self):
        '''
        dlpar move operation from lpar_1 to lpar2 and back from
        lpar_2 to lpar_1
        '''
        if self.lpar_2 is None:
            return

        self.changehwres(self.server, 'm', self.lpar_id, self.lpar_2,
                         self.drc_index, 'move')
        output = self.listhwres(self.server, self.lpar_1, self.drc_index)
        if self.drc_index in output:
            self.log.debug(output)
            self.fail("lshwres still lists the drc in lpar_1 after \
                      dlpar move to lpar_2")

        output = self.listhwres(self.server, self.lpar_2, self.drc_index)
        if self.drc_index not in output:
            self.log.debug(output)
            self.fail("lshwres fails to list the drc in lpar_2 after \
                       dlpar move")

        # dlpar move operation from lpar2 to lpar1
        self.changehwres(self.server, 'm', self.lpar2_id, self.lpar_1,
                         self.drc_index, 'move')

        output = self.listhwres(self.server, self.lpar_1, self.drc_index)
        if self.drc_index not in output:
            self.log.debug(output)
            self.fail("lshwres fails to list the drc in lpar_1 after \
                       dlpar move")

        output = self.listhwres(self.server, self.lpar_2, self.drc_index)
        if self.drc_index in output:
            self.log.debug(output)
            self.fail("lshwres still lists the drc in lpar_2 after \
                      dlpar move to lpar_1")

    def listhwres(self, server, lpar, drc_index):
        '''
        lists the drc index resources
        '''
        cmd = 'lshwres -r io -m %s \
               --rsubtype slot --filter lpar_names= %s \
               | grep -i %s' % (server, lpar, drc_index)
        try:
            cmd = self.session.cmd(cmd).stdout_text
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("lshwres operation failed ")
        return cmd

    def listhwres_sriov(self, server, lpar, logical_port_id):
        cmd = 'lshwres -r sriov -m %s \
              --rsubtype logport --filter lpar_names= %s --level eth \
              | grep -i %s' % (server, lpar, logical_port_id)
        try:
            cmd = self.session.cmd(cmd).stdout_text
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("lshwres operation failed ")
        return cmd

    def changehwres(self, server, operation, lpar_id, lpar, drc_index, msg):
        '''
        changes the drc index resource: add / remove / move
        '''
        if operation == 'm':
            cmd = 'chhwres -r io --rsubtype slot -m %s \
               -o %s --id %s -t %s -l %s ' % (server, operation, lpar_id,
                                              lpar, drc_index)
        else:
            cmd = 'chhwres -r io --rsubtype slot -m %s \
                   -o %s --id %s -l %s ' % (server, operation, lpar_id,
                                            drc_index)
        cmd = self.session.cmd(cmd)
        if cmd.exit_status != 0:
            self.log.debug(cmd.stderr)
            self.fail("dlpar %s operation failed" % msg)

    def changehwres_sriov(self, server, operation, lpar_id, adapter_id,
                          logical_port_id, phys_port_id, msg):
        '''
        operation add / remove for sriov ports
        '''
        if operation == 'r':
            cmd = 'chhwres -r sriov -m %s --rsubtype logport -o r --id %s -a \
                  adapter_id=%s,logical_port_id=%s' \
                  % (server, lpar_id, adapter_id, logical_port_id)
        elif operation == 'a':
            cmd = 'chhwres -r sriov -m %s --rsubtype logport -o a --id %s -a \
                  phys_port_id=%s,adapter_id=%s,logical_port_id=%s, \
                  logical_port_type=eth' % (server, lpar_id, phys_port_id,
                                            adapter_id, logical_port_id)
        cmd = self.session.cmd(cmd)
        if cmd.exit_status != 0:
            self.log.debug(cmd.stderr)
            self.fail("dlpar %s operation failed" % msg)

    def tearDown(self):
        self.session.quit()

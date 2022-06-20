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
# Copyright: 2019 IBM
# Author: Naresh Bannoth <nbannoth@in.ibm.com>

'''
Tests for Virtual FC
'''

import time
from avocado import Test
from avocado.utils import process
from avocado.utils import multipath
from avocado.utils import distro
from avocado.utils.ssh import Session
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.process import CmdError
from avocado import skipIf, skipUnless

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class VirtualFC(Test):
    '''
    Removing and Adding and Fibre Chanel Virtualized devices from the HMC
    '''
    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def setUp(self):
        '''
        set up required packages and gather necessary test inputs
        '''
        self.install_packages()
        self.rsct_service_start()
        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel("HMC IP not got")
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default=None)
        self.hmc_username = self.params.get("hmc_username", '*', default=None)
        self.count = self.params.get("count", default=1)
        self.skip_drc = self.params.get("skip_drc_name", default=None)
        self.opp_sleep_time = 150
        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")
        self.session = Session(self.hmc_ip, user=self.hmc_username,
                               password=self.hmc_pwd)
        if not self.session.connect():
            self.cancel("failed connecting to HMC")
        cmd = 'lssyscfg -r sys  -F name'
        output = self.session.cmd(cmd)
        self.server = ''
        for line in output.stdout_text.splitlines():
            if line in self.lpar:
                self.server = line
        if not self.server:
            self.cancel("Managed System not got")
        self.dic_list = []
        cmd = 'lshwres -r virtualio --rsubtype fc --level lpar -m %s \
               --filter "lpar_names=%s"' % (self.server, self.lpar)
        for line in self.session.cmd(cmd).stdout_text.splitlines():
            self.vfc_dic = {}
            for i in line.split(","):
                if i.split("=")[0] == "slot_num":
                    self.vfc_dic["c_slot"] = i.split("=")[-1]
                elif i.split("=")[0] == "remote_slot_num":
                    self.vfc_dic["r_slot"] = i.split("=")[-1]
                elif i.split("=")[0] == "remote_lpar_name":
                    self.vfc_dic["r_lpar"] = i.split("=")[-1]
            self.vfc_dic["wwpn"] = self.get_wwpn(self.vfc_dic["c_slot"])
            self.vfc_dic["drc"] = self.get_drc_name(self.vfc_dic["c_slot"])
            self.vfc_dic["paths"] = self.get_paths(self.vfc_dic["drc"])
            if self.vfc_dic["drc"] != self.skip_drc:
                self.dic_list.append(self.vfc_dic)
        self.log.info("complete list : %s" % self.dic_list)

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

        for line in process.system_output('lparstat -i', ignore_status=True,
                                          shell=True,
                                          sudo=True).decode("utf-8") \
                                                    .splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    def rsct_service_start(self):
        '''
        Running rsct services which is necessary for Network
        virtualization tests
        '''
        try:
            for svc in ["rsct", "rsct_rm"]:
                process.run('startsrc -g %s' % svc, shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Starting service %s failed", svc)

        output = process.system_output("lssrc -a", ignore_status=True,
                                       shell=True, sudo=True).decode("utf-8")
        if "inoperative" in output:
            self.fail("Failed to start the rsct and rsct_rm services")

    def install_packages(self):
        '''
        Install required packages
        '''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.log.info("Test is running on: %s", detected_distro.name)
        for pkg in ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                    'rsct.core', 'DynamicRM']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)

    def test(self):
        '''
        Remove and add vfc interfaces Dynamically from HMC
        '''
        for _ in range(self.count):
            for vfc_dic in self.dic_list:
                self.device_add_remove("remove", vfc_dic)
                time.sleep(self.opp_sleep_time)
                self.device_add_remove("add", vfc_dic)

    def get_drc_name(self, c_slot):
        '''
        Returns the drc_name i,e vfc slot name mapped to lpar
        '''
        cmd = 'lshwres -r virtualio --rsubtype slot --level slot -m %s -F \
               slot_num,lpar_name,drc_name | grep -i %s' \
               % (self.server, self.lpar)
        for line in self.session.cmd(cmd).stdout_text.splitlines():
            if c_slot in line:
                return line.split(",")[-1]
        return None

    def get_linux_name_drc(self, drc):
        '''
        returns the linux_name of corresponding drc_name
        '''
        cmd = 'lsslot -c slot'
        output = process.system_output(cmd).decode('utf-8').splitlines()
        self.log.info("output value : %s" % output)
        for line in output:
            if drc in line:
                linux_name = " ".join(line.split())
                return linux_name.split(" ")[-2]
        return None

    def get_paths(self, drc_name):
        '''
        returns the mpaths corresponding to linux name
        '''
        paths = []
        linux_name = self.get_linux_name_drc(drc_name)
        cmd = "ls -l /sys/block/"
        output = process.system_output(cmd).decode('utf-8').splitlines()
        for line in output:
            if "/%s/" % linux_name in line:
                paths.append(line.split("/")[-1])
        return paths

    def get_wwpn(self, client_slot):
        '''
        Returns the WWPNs of give client slot number
        '''
        cmd = 'lshwres -r virtualio --rsubtype fc --level lpar -m %s -F \
               lpar_name,slot_num,wwpns | grep -i %s' \
               % (self.server, self.lpar)
        output = self.session.cmd(cmd)
        for line in output.stdout_text.splitlines():
            if self.lpar and client_slot in line:
                wwpn = line.split('"')[1]
        self.log.info("wwpns of slot %s is : %s" % (client_slot, wwpn))
        return wwpn
        if output.exit_status != 0:
            self.log.debug(output.stderr)
            self.fail("Failed to get the wwpn, from give slot")

    def device_add_remove(self, operation, vfc_dic):
        '''
        Adds and removes a Network virtualized device based
        on the operation
        '''
        if operation == 'add':
            cmd = 'chhwres -r virtualio -m %s -o a -p %s --rsubtype fc -s %s \
                   -a "adapter_type=client,remote_lpar_name=%s, \
                   remote_slot_num=%s,\\"wwpns=%s\\""' \
                   % (self.server, self.lpar, vfc_dic["c_slot"],
                      vfc_dic["r_lpar"], vfc_dic["r_slot"], vfc_dic["wwpn"])
        else:
            cmd = 'chhwres -r virtualio -m %s -o r -p %s  -s %s' \
                   % (self.server, self.lpar, vfc_dic["c_slot"])

        output = self.session.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
            self.fail("Network virtualization %s device operation \
                       failed" % operation)
        time.sleep(self.opp_sleep_time)
        self.drc_name_verification_hmc(operation, vfc_dic["c_slot"])
        self.linux_name_verification_host(operation, vfc_dic["drc"])
        self.mpath_verification(operation, vfc_dic["paths"],
                                vfc_dic["drc"])

    def drc_name_verification_hmc(self, operation, c_slot):
        '''
        verify the vfc slot/rdc_name exists in HMC
        '''
        err_slot = []
        drc_name = self.get_drc_name(c_slot)
        if operation == "add":
            if not drc_name:
                err_slot.append(c_slot)
        elif operation == "remove":
            if drc_name:
                err_slot.append(c_slot)

        if err_slot:
            self.fail("HMC verifction fail for %s: %s" % (drc_name, operation))
        else:
            self.log.info("HMC verfction succes %s:%s" % (drc_name, operation))

    def linux_name_verification_host(self, operation, drc_name):
        '''
        verify the linux_name or drc_name in host
        '''
        err_slot = []
        linux_name = self.get_linux_name_drc(drc_name)
        if operation == "add":
            if not linux_name:
                err_slot.append(drc_name)
        elif operation == "remove":
            if linux_name:
                err_slot.append(drc_name)

        if err_slot:
            self.fail("Host verifction fail for %s:%s" % (drc_name, operation))
        else:
            self.log.info("Host verfction suces %s:%s" % (drc_name, operation))

    def mpath_verification(self, operation, paths, drc):
        '''
        verify the paths status on add or remove operations of vfc
        '''
        err_paths = []
        curr_paths = self.get_paths(drc)
        if operation == "add":
            for path in paths:
                path_stat = multipath.get_path_status(path)
                if path_stat[0] != "active" or path_stat[2] != "ready":
                    err_paths.append(path)
        elif curr_paths:
            for path in paths:
                path_stat = multipath.get_path_status(path)
                if path_stat[0] != "failed" or path_stat[2] != "faulty":
                    err_paths.append(path)

        if err_paths:
            self.fail("path verfction failed for drc %s:%s" % (drc, err_paths))
        else:
            self.log.info("path verfction success for drc :%s" % drc)

    def tearDown(self):
        '''
        close ssh session gracefully
        '''
        self.session.quit()

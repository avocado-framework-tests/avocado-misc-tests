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
# Copyright: 2020 IBM
# Author: Naresh Bannoth <nbannoth@in.ibm.com>

'''
Tests for Virtual FC
'''

import time
try:
    import pxssh
except ImportError:
    from pexpect import pxssh
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import multipath
from avocado.utils import distro
from avocado.utils import wait
from avocado.utils import genio
from avocado.utils.process import CmdError
from avocado.utils.software_manager import SoftwareManager
from avocado import skipIf, skipUnless

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class CommandFailed(Exception):
    '''
    Defines the exception called when a
    command fails
    '''

    def __init__(self, command, output, exitcode):
        Exception.__init__(self, command, output, exitcode)
        self.command = command
        self.output = output
        self.exitcode = exitcode

    def __str__(self):
        return "Command '%s' exited with %d.\nOutput:\n%s" \
               % (self.command, self.exitcode, self.output)


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
        self.vioses = self.params.get("vioses", default=None)
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default=None)
        self.hmc_username = self.params.get("hmc_username", '*', default=None)
        self.count = self.params.get("count", default=1)
        self.vfc_id = self.params.get("vfchost_id", default=None)
        self.vfchost_count = int(self.params.get("vfc_count", default=1))
        # Since the command in each layer doesn't take same time to complete
        # there is delay observed in status reflect (like host and multipath).
        # even though we have used the wait.wait_for funtion, this is not
        # enough to handle the case. since the operation flow reflect in 3
        # stages (lpar, HMC, vios), giving a short sleep time helps the flow
        # to happen smoother. Hence adding the sleep time after each major
        # operation like unamp, map, define, undefine, create, delete.
        # we can remove this sleep time in future if the flow happens smoother
        self.opp_sleep_time = 20
        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")
        self.login(self.hmc_ip, self.hmc_username, self.hmc_pwd)
        cmd = 'lssyscfg -r sys  -F name'
        output = self.run_command(cmd)
        self.server = ''
        for line in output:
            if line in self.lpar:
                self.server = line
        if not self.server:
            self.cancel("Managed System not got")
        self.dic_list = []
        self.err_mesg = []
        for vios in self.vioses.split(" "):
            for vfchost in self.get_vfchost(vios):
                vfc_dic = {}
                vfc_dic["vios"] = vios
                vfc_dic["vfchost"] = vfchost
                vfc_dic["fcs"] = self.get_fcs_name(vfchost, vios)
                vfc_dic["vfc_client"] = self.get_vfc_client(vfchost, vios)
                vfc_dic["paths"] = self.get_paths(vfc_dic["vfc_client"])
                self.dic_list.append(vfc_dic)

        self.log.info("complete list : %s" % self.dic_list)

    def login(self, ipaddr, username, password):
        '''
        SSH Login method for remote server
        '''
        pxh = pxssh.pxssh()
        # Work-around for old pxssh not having options= parameter
        pxh.SSH_OPTS = pxh.SSH_OPTS + " -o 'StrictHostKeyChecking=no'"
        pxh.SSH_OPTS = pxh.SSH_OPTS + " -o 'UserKnownHostsFile /dev/null' "
        pxh.force_password = True

        pxh.login(ipaddr, username, password)
        pxh.sendline()
        pxh.prompt(timeout=60)
        # Ubuntu likes to be "helpful" and alias grep to
        # include color, which isn't helpful at all. So let's
        # go back to absolutely no messing around with the shell
        pxh.set_unique_prompt()
        pxh.prompt(timeout=60)
        self.pxssh = pxh

    def run_command(self, command, timeout=300):
        '''
        SSH Run command method for running commands on remote server
        '''
        self.log.info("Running the command on hmc %s", command)
        con = self.pxssh
        con.sendline(command)
        con.expect("\n")  # from us
        con.expect(con.PROMPT, timeout=timeout)
        output = con.before.decode('utf-8').splitlines()
        con.sendline("echo $?")
        con.prompt(timeout)
        return output

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

    def test_unmap_map(self):
        '''
        Remove and add vfc interfaces Dynamically from HMC
        '''
        for _ in range(self.count):
            for vfc_dic in self.dic_list:
                self.vfchost_map_unmap("unmap", vfc_dic)
                time.sleep(self.opp_sleep_time)
                self.vfchost_map_unmap("map", vfc_dic)
                # sleeping between the operation. can be enhanced in future.
                time.sleep(self.opp_sleep_time)
        if self.err_mesg:
            self.fail("test failed due to folowing reasons:%s" % self.err_mesg)

    def get_vfchost(self, vios_name):
        '''
        Returns the drc_name i,e vfc slot name mapped to lpar
        '''
        vfchost = []
        cmd = 'viosvrcmd -m %s -p %s -c "lsmap -all -npiv -field  Name \
               ClntName -fmt :"' % (self.server, vios_name)
        for line in self.run_command(cmd):
            if self.lpar in line:
                vfchost.append(line.split(":")[0])
        return vfchost

    def get_fcs_name(self, vfchost, vios_name):
        '''
        returns the linux_name of corresponding drc_name
        '''
        cmd = 'viosvrcmd -m %s -p %s -c "lsmap -all -npiv -field Name \
               fc -fmt :"' % (self.server, vios_name)
        output = self.run_command(cmd)
        self.log.info("output value : %s" % output)
        for line in output:
            if vfchost in line:
                return line.split(":")[-1]
        return ''

    def get_vfc_client(self, vfchost, vios_name):
        '''
        returns the linux_name of corresponding drc_name
        '''
        cmd = 'viosvrcmd -m %s -p %s -c "lsmap -all -npiv -field  name\
               vfcclient -fmt :"' % (self.server, vios_name)
        output = self.run_command(cmd)
        self.log.info("output value : %s" % output)
        for line in output:
            if vfchost in line:
                return line.split(":")[-1]
        return ''

    def get_vfchost_status(self, vfchost, vios_name):
        '''
        returns the linux_name of corresponding drc_name
        '''
        cmd = 'viosvrcmd -m %s -p %s -c "lsmap -all -npiv -field  name\
               Status -fmt :"' % (self.server, vios_name)
        output = self.run_command(cmd)
        self.log.info("output value : %s" % output)
        for line in output:
            if vfchost in line:
                return line.split(":")[-1]
        return ''

    def get_paths(self, vfc_client):
        '''
        returns the mpaths corresponding to linux name
        '''
        paths = []
        cmd = "ls -l /sys/block/"
        output = process.system_output(cmd).decode('utf-8').splitlines()
        for line in output:
            if "/%s/" % vfc_client in line:
                paths.append(line.split("/")[-1])
        return paths

    def vfchost_map_unmap(self, operation, vfc_dic):
        '''
        Adds and removes a Network virtualized device based
        on the operation
        '''
        self.log.info("%sing %s" % (operation, vfc_dic["vfchost"]))
        if operation == 'map':
            cmd = 'viosvrcmd -m %s -p %s -c "vfcmap -vadapter %s -fcp %s"' \
                   % (self.server, vfc_dic["vios"],
                      vfc_dic["vfchost"], vfc_dic["fcs"])
        else:
            cmd = 'viosvrcmd -m %s -p %s -c "vfcmap -vadapter %s -fcp"' \
                   % (self.server, vfc_dic["vios"], vfc_dic["vfchost"])
        try:
            self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.fail("vfchost %s operation failed" % operation)
        self.vfchost_status_verify(operation, vfc_dic["vfchost"],
                                   vfc_dic["vios"])
        self.vfc_client_status_verify(operation, vfc_dic["vfc_client"])
        self.mpath_verification(operation, vfc_dic["paths"])

    def vfc_client_status_verify(self, operation, vfc_client):
        '''
        Returns the WWPNs of give client slot number
        '''
        self.log.info("verifying %s status after %s its \
                       vfchost" % (vfc_client, operation))

        def is_host_online():
            file_name = '/sys/class/fc_host/%s/port_state' % vfc_client
            status = genio.read_file(file_name).strip("\n")
            if operation == "map":
                if status == 'Online':
                    return True
                return False
            elif operation == 'unmap':
                if status == 'Linkdown':
                    return True
                return False

        if not wait.wait_for(is_host_online, timeout=10):
            self.err_mesg.append("after %s %s staus change \
                                  failed" % (operation, vfc_client))
        else:
            self.log.info("%s status change success \
                           after %s" % (operation, vfc_client))

    def vfchost_status_verify(self, operation, vfchost, vios_name):
        '''
        verify the vfc slot/rdc_name exists in HMC
        '''
        self.log.info("verifying % status after its %s" % (vfchost, operation))

        def status_check():
            vfchost_status = self.get_vfchost_status(vfchost, vios_name)
            if operation == "map":
                if vfchost_status == 'LOGGED_IN':
                    return True
                return False
            elif operation == "unmap":
                if vfchost_status == 'NOT_LOGGED_IN':
                    return True
                return False

        if not wait.wait_for(status_check, timeout=10):
            self.err_mesg.append("after %s %s staus change \
                                  failed" % (operation, vfchost))
        else:
            self.log.info("%s status change success \
                           after %s" % (operation, vfchost))

    def mpath_verification(self, operation, paths):
        '''
        verify the paths status on add or remove operations of vfc
        '''
        self.path = ''
        self.log.info("mpath verification for %s operation for \
                       paths: %s" % (operation, paths))

        def is_path_online():
            path_stat = multipath.get_path_status(self.path)
            if operation == "map":
                if path_stat[0] != "active" or path_stat[2] != "ready":
                    return False
                return True
            elif operation == "unmap":
                if path_stat[0] != "failed" or path_stat[2] != "faulty":
                    return False
                return True

        for path in paths:
            self.path = path
            if not wait.wait_for(is_path_online, timeout=10):
                self.err_mesg.append("after %s path %s status did not \
                                      changed" % (operation, path))
            else:
                self.log.info("%s mpath verification success " % operation)

    def test_undefine_define(self):
        '''
        Undefin and define the vfchost from vios
        '''
        self.err_mesg = []
        for _ in range(self.count):
            for vfc_dic in self.dic_list:
                self.vfchost_define_undefine("undefine", vfc_dic)
                time.sleep(self.opp_sleep_time)
                self.vfchost_define_undefine("define", vfc_dic)
                # sleep time between operations, can be enhanced in future.
                time.sleep(self.opp_sleep_time)
        if self.err_mesg:
            self.fail("test failed due to folowing reasons:%s" % self.err_mesg)

    def vfchost_define_undefine(self, operation, vfc_dic):
        '''
        removes and adds back the vfchost from vios as a root user.
        '''
        if operation == 'undefine':
            cmd = 'viosvrcmd -m %s -p %s -c "rmdev -dev %s -ucfg"' \
                   % (self.server, vfc_dic["vios"], vfc_dic["vfchost"])
        else:
            cmd = 'viosvrcmd -m %s -p %s -c "cfgdev -dev %s"' \
                   % (self.server, vfc_dic["vios"], vfc_dic["vfchost"])
        try:
            self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.fail("vfchost %s operation failed" % operation)
        self.vfchost_config_status_verify(operation, vfc_dic["vfchost"],
                                          vfc_dic["vios"])
        self.vfc_client_status_verify(operation, vfc_dic["vfc_client"])
        self.mpath_verification(operation, vfc_dic["paths"])

    def get_vfchost_config_status(self, vios, vfchost):
        '''
        '''
        cmd = 'viosvrcmd -m %s -p %s -c "lsdev -dev %s -field  name status \
               -fmt :"' % (self.server, vios, vfchost)
        output = self.run_command(cmd)
        self.log.info("output value : %s" % output)
        for line in output:
            if vfchost in line:
                return line.split(":")[-1]
        return ''

    def vfchost_config_status_verify(self, operation, vfchost, vios):
        '''
        check the vfchost config status and returns True or False
        '''
        def is_define():
            status = self.get_vfchost_config_status(vios, vfchost)
            if operation == 'define':
                if status == 'Available':
                    return True
                return False
            elif operation == 'undefine':
                if status == 'Defined':
                    return True
                return False
        if not wait.wait_for(is_define, timeout=30):
            self.err_mesg.append("after %s %s staus change \
                                  failed" % (operation, vfchost))
        else:
            self.log.info("%s status change success \
                           after %s" % (operation, vfchost))

    def test_create_delete_vfchost(self):
        '''
        start of create delete vfchost here
        '''
        self.err_mesg = []
        vfc_id = {}
        vfc_start_id = int(self.vfc_id.split("-")[0])
        vfc_end_id = int(self.vfc_id.split("-")[-1])
        for vios in self.vioses.split(","):
            for _ in range(self.vfchost_count):
                if vfc_start_id < vfc_end_id:
                    if self.create_vfchost(vios, vfc_start_id,
                                           "server") is True:
                        vfc_id[vfc_start_id] = []
                        self.log.info("server vfchost created with \
                                       id=%s" % vfc_start_id)
                        vfc_id[vfc_start_id].append(vios)
                        if self.create_vfchost(vios, vfc_start_id,
                                               "client") is True:
                            self.log.info("client vfchost created success \
                                           with id=%s" % vfc_start_id)
                            vfc_id[vfc_start_id].append(self.lpar)
                    vfc_start_id = vfc_start_id + 1
                else:
                    self.err_mesg.append("start host id is not in range")

        for v_id in vfc_id:
            for lpar in vfc_id[v_id]:
                self.log.info("deleting vfchost ID=%s lpar=%s" % (v_id, lpar))
                if self.delete_vfchost(v_id, lpar) is True:
                    self.log.info("vfchost deleted sucesfully: %s" % v_id)
                else:
                    self.err_mesg.append("vfc_id=%s delete failed:" % v_id)
        if self.err_mesg:
            self.fail("failed for following IDs:%s" % self.err_mesg)
        else:
            self.log.info("test passed successfully")

    def create_vfchost(self, vios, vfchost_id, vfc_type):
        '''
        creates the number of vfchost with the give adapter ID range
        '''
        if vfc_type == "client":
            cmd = 'chhwres -m %s -r virtualio --rsubtype fc -o a \
                    -p %s -a "adapter_type=%s,remote_lpar_name=%s, \
                   remote_slot_num=%s" -s %s' % (self.server, self.lpar,
                                                 vfc_type, vios,
                                                 vfchost_id, vfchost_id,)
        else:
            cmd = 'chhwres -m %s -r virtualio --rsubtype fc -o a \
                   -p %s -s %s -a "adapter_type=%s,remote_lpar_name=%s, \
                   remote_slot_num=%s"' % (self.server, vios, vfchost_id,
                                           vfc_type, self.lpar, vfchost_id)
        try:
            self.log.info("create-command=%s" % cmd)
            self.run_command(cmd)
            if self.vfchost_exists("create", vfchost_id, vfc_type) is True:
                return True
            else:
                self.err_mesg.append("%s=%scommand success but not \
                                     deleted" % (vfc_type, vfchost_id))
                return False
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.err_mesg.append("failed to create %s vfchost%s on \
                                  %s" % (vfc_type, vfchost_id, vios))

    def delete_vfchost(self, vfchost_id, lpar):
        '''
        delete the given vfchost using vfchost slot number and vfchost type
        '''
        cmd = 'chhwres -r virtualio -m %s -o r -p %s -s %s' % (self.server,
                                                               lpar,
                                                               vfchost_id)
        try:
            self.log.info("delete-command=%s" % cmd)
            self.run_command(cmd)
            if self.vfchost_exists("delete", vfchost_id, lpar) is True:
                self.log.info("%s vfchost with ID: %s deleted \
                               successfully" % (lpar, vfchost_id))
                return True
            else:
                self.err_mesg.append("%s=%scommand success but not \
                                      deleted" % (lpar, vfchost_id))
                return False
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.err_mesg.append("failed to delete %s vfchost%s \
                                  on" % (lpar, vfchost_id))

    def vfchost_exists(self, operation, vfc_slot, lpar):
        '''
        checks whether vfchost is exists or not
        '''
        cmd = 'lshwres -r virtualio --rsubtype fc --level lpar -m %s -F \
               slot_num,adapter_type | grep -i %s' % (self.server, lpar)

        def is_vfc_exist():
            output = self.run_command(cmd)
            if operation == "create":
                for line in output:
                    if str(vfc_slot) == line.split(",")[0]:
                        return True
                return False
            else:
                for line in output:
                    if str(vfc_slot) == line.split(",")[0]:
                        return False
                return True

        return wait.wait_for(is_vfc_exist, timeout=30) or False

    def tearDown(self):
        '''
        close ssh session gracefully
        '''
        if self.pxssh.isalive():
            self.pxssh.terminate()


if __name__ == "__main__":
    main()

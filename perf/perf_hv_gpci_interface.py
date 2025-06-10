#!/usr/bin/env python
#
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
# Copyright: 2024 IBM
# Author: Tejas Manhas <Tejas.Manhas1@ibm.com>
import os
from avocado import Test
from avocado.utils import distro, process, genio, cpu, dmesg
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session


class perf_hv_gpci_interface(Test):
    """
    Tests hv_gpci interface files, permission and access
    :avocado: tags=perf,hv_gpci,events
    """
    interface_directory = '/sys/devices/hv_gpci/interface'

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        if 'ppc64' not in detected_distro.arch:
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)
        if 'PowerNV' in genio.read_file('/proc/cpuinfo'):
            self.cancel('This test is only supported on LPAR')
        self.rev = cpu.get_revision()
        if self.rev not in ['0080', '0082']:
            self.cancel("Test is supported on Power10 and above")
        deps = ['ksh', 'src', 'rsct.basic', 'rsct.core.utils', 'rsct.core']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        self.expected_files = self.params.get("access_files", default=None)
        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel("HMC IP not got")
        self.hmc_username = self.params.get("hmc_username", '*', default=None)
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default=None)
        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")
        self.session = Session(self.hmc_ip, user=self.hmc_username,
                               password=self.hmc_pwd)
        if not self.session.connect():
            self.cancel("failed connecting to HMC")
        cmd = 'lssyscfg -r sys -F name'
        output = self.session.cmd(cmd).stdout_text
        self.server = ''
        for line in output.splitlines():
            if line in self.lpar:
                self.server = line
        if not self.server:
            self.cancel("Managed System not got")
        performance_cmd = f"lssyscfg -m {self.server} -r lpar --filter" \
            f" lpar_names={self.lpar} -F allow_perf_collection"
        output = self.session.cmd(performance_cmd).stdout_text.strip()
        if output != '1':
            self.cancel(
                "Performance property not enabled. Test cannot continue")
        # create temporary user
        if process.system('useradd test', sudo=True, ignore_status=True):
            self.log.warning('test useradd failed')
        # Clear the dmesg, by that we can capture the delta at the end of the test.
        dmesg.clear_dmesg()

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

    def run_cmd(self, cmd, user=None):
        """
        run command on SUT as root and non root user
        """
        if user == 'test':  # i.e., we are running as non root
            result = process.run(
                f"su - test -c '{cmd}'", shell=True, ignore_status=True)
        else:
            result = process.run(cmd, shell=True, ignore_status=True)
        output = result.stdout_text + result.stderr_text
        return output

    def _check_file_access(self, user=None):
        """
        Check if all expected files are present and have the correct permissions.
        This function runs the checks for a given user.
        """
        self.log.info(
            f"Checking file access and permissions as {'root' if user is None else user} user")
        for filename in self.expected_files:
            filepath = os.path.join(self.interface_directory, filename)
            if not os.path.isfile(filepath):
                self.log.info(f"File {filename} is missing.")
            else:
                # Check read/write permissions as the specified user
                read_access = self.run_cmd(f'cat {filepath}', user=user)
                if read_access is None:
                    self.fail(
                        f"Read access to {filename} failed as {'root' if user is None else user}.")
                # Attempt write access
                output = self.run_cmd(f'echo Test > {filepath}', user=user)
                if 'Permission denied' not in output:
                    self.fail(
                        f"{'root' if user is None else user} user able to write to {filename}")

    def _disable_and_check_read_access(self):
        """
        Disable performance property of SUT and then check for access again
        """
        dis_performance_cmd = f"chsyscfg -m {self.server} -r lpar" \
            f" -i 'name={self.lpar},allow_perf_collection=0'"
        self.session.cmd(dis_performance_cmd).stdout_text
        performance_cmd = f"lssyscfg -m {self.server} -r lpar --filter" \
            f" lpar_names={self.lpar} -F allow_perf_collection"
        output = self.session.cmd(performance_cmd).stdout_text.strip()
        if output == '1':
            self.cancel(
                "Test cannot continue as Performance property is enabled.")

        for filename in self.expected_files:
            # Check permissions as the specified user
            filepath = os.path.join(self.interface_directory, filename)
            output = self.run_cmd(f'cat {filepath}')
            if 'Operation not permitted' not in output:
                self.fail(
                    f"Read access to {filename} is working with performance property disabled")

    def test_hv_gpci_interface(self):
        """
        Test function to check hv_gpci interface files for perf
        """
        # Check as root user
        self._check_file_access()
        # Switch to non-root user and check access
        non_root_user = "test"
        self._check_file_access(user=non_root_user)
        # Check with performance property disabled
        self._disable_and_check_read_access()

    def tearDown(self):
        """
        tear down function to remove non root user.
        """
        if not (process.system('id test', sudo=True, ignore_status=True)):
            process.system('userdel -f test', sudo=True)
        # Collect the dmesg
        process.run("dmesg -T")

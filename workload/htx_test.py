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
# Copyright: 2017 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#

"""
HTX Test
"""

import os
import time
import shutil
import re

from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import build
from avocado.utils import process, archive
from avocado.utils import distro


class HtxTest(Test):

    """
    HTX [Hardware Test eXecutive] is a test tool suite. The goal of HTX is to
    stress test the system by exercising all hardware components concurrently
    in order to uncover any hardware design flaws and hardware-hardware or
    hardware-software interaction issues.
    :see:https://github.com/open-power/HTX.git
    :param mdt_file: mdt file used to trigger HTX
    :params time_limit: how much time(hours) you want to run this stress.
    """

    def install_latest_htx_rpm(self):
        """
        Search for the latest htx-version for the intended distro and
        install the same.
        """
        distro_pattern = "%s%s" % (
            self.dist_name, self.detected_distro.version)
        temp_string = process.getoutput(
            "curl --silent -k  %s" % (self.rpm_link),
            verbose=False, shell=True, ignore_status=True)
        matching_htx_versions = re.findall(
            r"(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*", str(temp_string))
        distro_specific_htx_versions = [
            htx_rpm for htx_rpm in matching_htx_versions
            if distro_pattern in htx_rpm]
        distro_specific_htx_versions.sort(reverse=True)
        tmp_htx_rpm = distro_specific_htx_versions[0]
        self.latest_htx_rpm = tmp_htx_rpm
        tmp_dir = "/tmp/" + tmp_htx_rpm
        cmd = "curl -k %s/%s -o %s" % (self.rpm_link, self.latest_htx_rpm,
                                       tmp_dir)
        if process.system(cmd,
                          shell=True, ignore_status=True):
            self.cancel("rpm download failed")
        cmd = "rpm -ivh --nodeps %s" % (tmp_dir)
        if process.system(cmd,
                          shell=True, ignore_status=True):
            self.cancel("rpm installation failed")
        cmd = "rm -rf %s" % (tmp_dir)
        # Remove the downloaded HTX rpm from /tmp directory
        process.run(cmd)

    def setUp(self):
        """
        Setup
        """
        if 'ppc64' not in distro.detect().arch:
            self.cancel("Supported only on Power Architecture")

        self.mdt_file = self.params.get('mdt_file', default='mdt.mem')
        self.time_limit = int(self.params.get('time_limit', default=2))
        self.time_unit = self.params.get('time_unit', default='m')
        self.run_type = self.params.get('run_type', default='')
        if self.time_unit == 'm':
            self.time_limit = self.time_limit * 60
        elif self.time_unit == 'h':
            self.time_limit = self.time_limit * 3600
        else:
            self.cancel(
                "running time unit is not proper, please pass as 'm' or 'h' ")
        if not os.path.exists("/usr/lpp/htx/mdt/"):
            self.log.info("mdt directory is created")

        if str(self.name.name).endswith('test_start'):
            # Build HTX only at the start phase of test
            self.setup_htx()
        if not os.path.exists("/usr/lpp/htx/mdt/%s" % self.mdt_file):
            self.cancel("MDT file %s not found due to config" % self.mdt_file)

    def setup_htx(self):
        """
        Builds HTX
        """
        self.detected_distro = distro.detect()
        packages = ['git', 'gcc', 'make']
        if self.detected_distro.name in ['centos', 'fedora', 'rhel']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif self.detected_distro.name == "Ubuntu":
            packages.extend(['libncurses5', 'g++',
                             'ncurses-dev', 'libncurses-dev'])
        elif self.detected_distro.name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            self.cancel("Test not supported in  %s" %
                        self.detected_distro.name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Can not install %s" % pkg)

        if self.run_type == 'git':
            if self.detected_distro.name == 'rhel' and \
                    self.detected_distro.version <= "9":
                self.cancel("Test not supported in  %s_%s"
                            % (self.detected_distro.name,
                               self.detected_distro.version))
            url = "https://github.com/open-power/HTX/archive/master.zip"
            tarball = self.fetch_asset("htx.zip", locations=[url], expire='7d')
            archive.extract(tarball, self.teststmpdir)
            htx_path = os.path.join(self.teststmpdir, "HTX-master")
            os.chdir(htx_path)

            exercisers = ["hxecapi_afu_dir", "hxedapl", "hxecapi", "hxeocapi"]
            for exerciser in exercisers:
                process.run("sed -i 's/%s//g' %s/bin/Makefile" % (exerciser,
                                                                  htx_path))

            build.make(htx_path, extra_args='all')
            build.make(htx_path, extra_args='tar')
            process.run('tar --touch -xvzf htx_package.tar.gz')
            os.chdir('htx_package')
            if process.system('./installer.sh -f'):
                self.fail("Installation of htx fails:please refer job.log")
        else:
            self.dist_name = self.detected_distro.name.lower()
            if self.dist_name == 'suse':
                self.dist_name = 'sles'
            rpm_check = "htx%s%s" % (
                self.dist_name, self.detected_distro.version)
            skip_install = False
            ins_htx = process.system_output(
                'rpm -qa | grep htx', shell=True, ignore_status=True).decode()

            if ins_htx:
                if not smm.check_installed(rpm_check):
                    self.log.info("Clearing existing HTX rpm")
                    process.system('rpm -e %s' %
                                   ins_htx, shell=True, ignore_status=True)
                    if os.path.exists('/usr/lpp/htx'):
                        shutil.rmtree('/usr/lpp/htx')
                else:
                    self.log.info("Using existing HTX")
                    skip_install = True
            if not skip_install:
                self.rpm_link = self.params.get('htx_rpm_link', default=None)
                if self.rpm_link:
                    self.install_latest_htx_rpm()
                else:
                    self.cancel("RPM link is required for RPM run type")
        self.log.info("Starting the HTX Daemon")
        # Kill existing HTXD process if running
        htxd_pid = process.getoutput("pgrep -f htxd")
        if htxd_pid:
            self.log.info(
                "HTXD is already running with PID: %s. Killing it.",
                htxd_pid)
            process.run("pkill -f htxd", ignore_status=True)
            time.sleep(10)
        process.run('/usr/lpp/htx/etc/scripts/htxd_run')

        cmd = "hcl -set_htx_env HTX_ON_DEMAND_MDT_CREATION 1"
        self.log.info("Enabling on demand HTX mdt support")
        process.run(cmd)
        self.log.info("Creating the on demand HTX mdt files")
        cmd = "hcl -createmdt -mdt %s" % (self.mdt_file)
        process.run(cmd)

    def test_start(self):
        """
        Execute 'HTX' with appropriate parameters.
        """

        self.log.info("selecting the mdt file")
        cmd = "htxcmdline -select -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        self.log.info("Activating the %s", self.mdt_file)
        cmd = "htxcmdline -activate -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        self.log.info("Running the HTX ")
        cmd = "htxcmdline -run  -mdt %s" % self.mdt_file

        process.system(cmd, ignore_status=True)

    def test_check(self):
        """
        Checks if HTX is running, and if no errors.
        """
        for _ in range(0, self.time_limit, 60):
            self.log.info("HTX Error logs")
            process.system('htxcmdline -geterrlog', ignore_status=True)
            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("check errorlogs for exact error and failure")
            cmd = 'htxcmdline -query  -mdt %s' % self.mdt_file
            process.system(cmd, ignore_status=True)
            time.sleep(60)

    def test_stop(self):
        '''
        Shutdown the mdt file and the htx daemon and set SMT to original value
        '''
        self.stop_htx()

    def stop_htx(self):
        """
        Stop the HTX Run
        """
        self.log.info("shutting down the %s ", self.mdt_file)
        cmd = 'htxcmdline -shutdown -mdt %s' % self.mdt_file
        process.system(cmd, timeout=120, ignore_status=True)

        if self.run_type == 'rpm':
            process.system(
                '/usr/lpp/htx/etc/scripts/htxd_shutdown', ignore_status=True)
            process.system('umount /htx_pmem*', shell=True, ignore_status=True)
        else:
            cmd = '/usr/lpp/htx/etc/scripts/htx.d status'
            daemon_state = process.system_output(cmd)
            if daemon_state.decode().split(" ")[-1] == 'running':
                process.system('/usr/lpp/htx/etc/scripts/htxd_shutdown')

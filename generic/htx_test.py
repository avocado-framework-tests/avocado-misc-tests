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


import os
import time
from avocado import Test
from avocado import main
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import build
from avocado.utils import process, archive
from avocado.utils import distro
from avocado.utils import cpu


class HtxTest(Test):

    """
    HTX [Hardware Test eXecutive] is a test tool suite. The goal of HTX is to
    stress test the system by exercising all hardware components concurrently
    in order to uncover any hardware design flaws and hardware-hardware or
    hardware-software interaction issues.
    :see:https://github.com/open-power/HTX.git
    :param mdt_file: mdt file used to trigger HTX
    :params time_limit: how much time(hours) you want to run this stress.
    :smt_change : if user want to change smt value as well while running test
    """

    def setUp(self):
        """
        Build 'HTX'.
        """
        if 'ppc64' not in process.system_output('uname -a', shell=True):
            self.cancel("Supported only on Power Architecture")

        detected_distro = distro.detect()
        self.mdt_file = self.params.get('mdt_file', default='mdt.mem')
        self.time_limit = int(self.params.get('time_limit', default=2)) * 3600
        self.smt = self.params.get('smt_change', default=False)

        packages = ['git', 'gcc', 'make']
        if detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel',
                             'dapl-devel', 'libcxl-devel'])
        elif detected_distro.name == "Ubuntu":
            packages.extend(['libncurses5', 'g++', 'libdapl-dev',
                             'ncurses-dev', 'libncurses-dev', 'libcxl-dev'])
        else:
            self.cancel("Test not supported in  %s" % detected_distro.name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Can not install %s" % pkg)

        url = "https://github.com/open-power/HTX/archive/master.zip"
        tarball = self.fetch_asset("htx.zip", locations=[url], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        htx_path = os.path.join(self.teststmpdir, "HTX-master")
        os.chdir(htx_path)

        build.make(htx_path, extra_args='all')
        build.make(htx_path, extra_args='tar')
        process.run('tar --touch -xvzf htx_package.tar.gz')
        os.chdir('htx_package')
        if process.system('./installer.sh -f'):
            self.fail("Installation of htx fails:please refer job.log")

        if self.smt:
            self.max_smt_value = 8
            if cpu.get_cpu_arch().lower() == 'power7':
                self.max_smt_value = 4
            if cpu.get_cpu_arch().lower() == 'power6':
                self.max_smt_value = 2
            self.smt_values = ["off", "on"]
            for i in range(2, self.max_smt_value + 1):
                self.smt_values.append(str(i))
            self.curr_smt = process.system_output("ppc64_cpu --smt | awk -F'=' \
                '{print $NF}' | awk '{print $NF}'", shell=True)

    def test(self):
        """
        Execute 'HTX' with appropriate parameters.
        """
        self.log.info("Starting the HTX Deamon")
        process.run('/usr/lpp/htx/etc/scripts/htxd_run')

        self.log.info("selecting the mdt file")
        cmd = "htxcmdline -select -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        self.log.info("Activating the %s", self.mdt_file)
        cmd = "htxcmdline -activate -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        self.log.info("Running the HTX ")
        cmd = "htxcmdline -run  -mdt %s" % self.mdt_file

        process.system(cmd, ignore_status=True)
        for time_loop in range(0, self.time_limit, 60):
            # Running SMT changes every hour
            if self.smt and time_loop % 3600 == 0:
                self.run_smt()
            self.log.info("HTX Error logs")
            process.run('htxcmdline -geterrlog')
            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("check errorlogs for exact error and failure")
            cmd = 'htxcmdline -query  -mdt %s' % self.mdt_file
            process.system(cmd, ignore_status=True)
            time.sleep(60)

    def run_smt(self):
        """
        Sets each of the supported SMT value.
        """
        for value in self.smt_values:
            process.system("ppc64_cpu --smt=%s" %
                           value, shell=True, ignore_status=True)
            process.system("ppc64_cpu --smt" %
                           value, shell=True, ignore_status=True)
            process.system("ppc64_cpu --info", ignore_status=True)

    def tearDown(self):
        '''
        Shutdown the mdt file and the htx daemon and set SMT to original value
        '''
        self.log.info("shutting down the %s ", self.mdt_file)
        cmd = 'htxcmdline -shutdown -mdt %s' % self.mdt_file
        process.system(cmd, ignore_status=True)

        daemon_state = process.system_output('/etc/init.d/htx.d status')
        if daemon_state.split(" ")[-1] == 'running':
            process.system('/usr/lpp/htx/etc/scripts/htxd_shutdown')
        if self.smt:
            process.system("ppc64_cpu --smt=%s" %
                           self.curr_smt, shell=True, ignore_status=True)
        process.system("./uninstaller.sh -f")


if __name__ == "__main__":
    main()

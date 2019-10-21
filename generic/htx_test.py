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
from avocado import Test
from avocado import main
from avocado.utils.software_manager import SoftwareManager
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

    def setUp(self):
        """
        Setup
        """
        if 'ppc64' not in distro.detect().arch:
            self.cancel("Supported only on Power Architecture")

        self.mdt_file = self.params.get('mdt_file', default='mdt.mem')
        self.time_limit = int(self.params.get('time_limit', default=2))
        self.time_unit = self.params.get('time_unit', default='m')
        self.failed = False
        if self.time_unit == 'm':
            self.time_limit = self.time_limit * 60
        elif self.time_unit == 'h':
            self.time_limit = self.time_limit * 3600
        else:
            self.cancel("running time unit is not proper, please pass as 'm' or 'h' ")
        if str(self.name.name).endswith('test_start'):
            # Build HTX only at the start phase of test
            self.setup_htx()
        if not os.path.exists("/usr/lpp/htx/mdt/%s" % self.mdt_file):
            self.cancel("MDT file %s not found due to config" % self.mdt_file)

    def setup_htx(self):
        """
        Builds HTX
        """
        detected_distro = distro.detect()
        packages = ['git', 'gcc', 'make']
        if detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif detected_distro.name == "Ubuntu":
            packages.extend(['libncurses5', 'g++',
                             'ncurses-dev', 'libncurses-dev'])
        elif detected_distro.name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
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
        self.log.info("Starting the HTX Deamon")
        process.run('/usr/lpp/htx/etc/scripts/htxd_run')

        self.log.info("Creating the HTX mdt files")
        process.run('htxcmdline -createmdt')

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
                self.failed = True
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
        process.system(cmd, ignore_status=True)

        daemon_state = process.system_output('/etc/init.d/htx.d status')
        if daemon_state.decode().split(" ")[-1] == 'running':
            process.system('/usr/lpp/htx/etc/scripts/htxd_shutdown')

    def tearDown(self):
        """
        tearDown
        """
        if self.failed:
            self.stop_htx()


if __name__ == "__main__":
    main()

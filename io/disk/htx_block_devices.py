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
# Author: Naresh Bannoth<nbannoth@in.ibm.com>
# this script run IO stress on block devices for give time.

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
    in order to uncover any hardware design flaws and hardware hardware or
    hardware-software interaction issues.
    :see:https://github.com/open-power/HTX.git
    :param block_devices: names of block_devices on which you want to run HTX
    :param mdt_file: mdt file used to trigger HTX
    :param time_limit: how much time(hours) you want to run this stress
    :param all: if all disks in selected mdt needs to be used for HTX run
    """

    def setUp(self):
        """
        Setup
        """
        if 'ppc64' not in distro.detect().arch:
            self.cancel("Platform does not supports")

        self.mdt_file = self.params.get('mdt_file', default='mdt.hd')
        self.time_limit = int(self.params.get('time_limit', default=1)) * 60
        self.block_devices = self.params.get('htx_disks', default=None)
        self.all = self.params.get('all', default=False)

        if not self.all and self.block_devices is None:
            self.cancel("Needs the block devices to run the HTX")
        if self.all:
            self.block_device = ""
        else:
            self.block_device = []
            for disk in self.block_devices.split():
                self.block_device.append(disk.rsplit("/")[-1])
            self.block_device = " ".join(self.block_device)
        self.failed = False

    def setup_htx(self):
        """
        Builds HTX
        """
        packages = ['git', 'gcc', 'make']
        detected_distro = distro.detect().name
        if detected_distro in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif detected_distro == "Ubuntu":
            packages.extend(['libncurses5', 'g++', 'ncurses-dev',
                             'libncurses-dev', 'tar'])
        elif detected_distro == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            self.cancel("Test not supported in  %s" % detected_distro)

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

    def test_start(self):
        """
        Execute 'HTX' with appropriate parameters.
        """
        self.setup_htx()
        self.log.info("Starting the HTX Deamon")
        process.run('/usr/lpp/htx/etc/scripts/htxd_run')

        self.log.info("Creating the HTX mdt files")
        process.run('htxcmdline -createmdt')

        if not os.path.exists("/usr/lpp/htx/mdt/%s" % self.mdt_file):
            self.failed = True
            self.fail("MDT file %s not found" % self.mdt_file)

        self.log.info("selecting the mdt file ")
        cmd = "htxcmdline -select -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        if not self.all:
            if self.is_block_device_in_mdt() is False:
                self.failed = True
                self.fail("Block devices %s are not available in %s",
                          self.block_device, self.mdt_file)

        self.suspend_all_block_device()

        self.log.info("Activating the %s", self.block_device)
        cmd = "htxcmdline -activate %s -mdt %s" % (self.block_device,
                                                   self.mdt_file)
        process.system(cmd, ignore_status=True)
        if not self.all:
            if self.is_block_device_active() is False:
                self.failed = True
                self.fail("Block devices failed to activate")

        self.log.info("Running the HTX on %s", self.block_device)
        cmd = "htxcmdline -run -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

    def test_check(self):
        """
        Checks if HTX is running, and if no errors.
        """
        for _ in range(0, self.time_limit, 60):
            self.log.info("HTX Error logs")
            process.run('htxcmdline -geterrlog')
            if os.stat('/tmp/htxerr').st_size != 0:
                self.failed = True
                self.fail("check errorlogs for exact error and failure")
            self.log.info("status of block devices after every 60 sec")
            cmd = 'htxcmdline -query %s -mdt %s' % (self.block_device,
                                                    self.mdt_file)
            process.system(cmd, ignore_status=True)
            time.sleep(60)

    def is_block_device_in_mdt(self):
        '''
        verifies the presence of given block devices in selected mdt file
        '''
        self.log.info("checking if the given block_devices are present in %s",
                      self.mdt_file)
        cmd = "htxcmdline -query -mdt %s" % self.mdt_file
        output = process.system_output(cmd).decode("utf-8")
        device = []
        for disk in self.block_device.split(" "):
            if disk not in output:
                device.append(disk)
        if device:
            self.log.info("block_devices %s are not avalable in %s ",
                          device, self.mdt_file)
        self.log.info("BLOCK DEVICES %s ARE AVAILABLE %s",
                      self.block_device, self.mdt_file)
        return True

    def suspend_all_block_device(self):
        '''
        Suspend the Block devices, if active.
        '''
        self.log.info("suspending block_devices if any running")
        cmd = "htxcmdline -suspend all  -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

    def is_block_device_active(self):
        '''
        Verifies whether the block devices are active or not
        '''
        self.log.info("checking whether all block_devices are active ot not")
        cmd = 'htxcmdline -query %s -mdt %s' % (self.block_device,
                                                self.mdt_file)
        output = process.system_output(cmd).decode("utf-8").split('\n')
        device_list = self.block_device.split(" ")
        active_devices = []
        for line in output:
            for disk in device_list:
                if disk in line and 'ACTIVE' in line:
                    active_devices.append(disk)
        non_active_device = list(set(device_list) - set(active_devices))
        if non_active_device:
            return False
        self.log.info("BLOCK DEVICES %s ARE ACTIVE", self.block_device)
        return True

    def test_stop(self):
        '''
        Shutdown the mdt file and the htx daemon and set SMT to original value
        '''
        self.stop_htx()

    def stop_htx(self):
        """
        Stop the HTX Run
        """
        if self.is_block_device_active() is True:
            self.log.info("suspending active block_devices")
            self.suspend_all_block_device()
            self.log.info("shutting down the %s ", self.mdt_file)
            cmd = "htxcmdline -shutdown -mdt %s" % self.mdt_file
            process.system(cmd, ignore_status=True)

        daemon_state = process.system_output('/etc/init.d/htx.d status')
        if daemon_state.decode("utf-8").split(" ")[-1] == 'running':
            process.system('/usr/lpp/htx/etc/scripts/htxd_shutdown')

    def tearDown(self):
        """
        tearDown
        """
        if self.failed:
            self.stop_htx()


if __name__ == "__main__":
    main()

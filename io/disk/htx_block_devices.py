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

import os
import time
from avocado import Test
from avocado import main
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import build
from avocado.utils import process, git
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
    :params time_limit: how much time you want to run this stress.
    """

    def setUp(self):
        """
        Build 'HTX'.
        """
        self.distro_name = distro.detect().name
        packages = ['git', 'gcc', 'make', 'libncurses5', 'g++', 'libdapl-dev',
                    'ncurses-dev', 'libncurses-dev']
        smm = SoftwareManager()
        if self.distro_name == 'Ubuntu':
            for pkg in packages:
                if not smm.check_installed(pkg) and not smm.install(pkg):
                    self.skip("Can not install %s" % pkg)
        else:
            self.skip("skipping for other than Ubuntu Distro")

        htx_path = os.path.join(self.teststmpdir, "HTX/")
        git.get_repo('https://github.com/open-power/HTX.git',
                     destination_dir=htx_path)

        build.run_make(htx_path, extra_args='all')
        build.run_make(htx_path, extra_args='deb')
        process.run('dpkg -r htxubuntu')
        process.run('dpkg --purge htxubuntu')
        process.run('dpkg -i htxubuntu.deb')
        self.mdt_file = self.params.get('mdt_file', default='mdt.hd')
        self.time_limit = self.params.get('time_limit', default=600)
        self.block_device = self.params.get('disk', default=None)
        if self.block_device is None:
            self.skip("Needs the block devices to run the HTX")

    def test(self):
        """
        Execute 'HTX' with appropriate parameters.
        """
        self.log.info("Starting the HTX Deamon")
        process.run('/usr/lpp/htx/etc/scripts/htxd_run')

        self.log.info("selecting the mdt file ")
        cmd = "htxcmdline -select -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        if self.is_block_device_in_mdt() is False:
            self.fail("Block devices %s are not available in %s",
                      self.block_device, self.mdt_file)

        self.suspend_all_block_device()

        self.log.info("Activating the %s", self.block_device)
        cmd = "htxcmdline -activate %s -mdt %s" % (self.block_device,
                                                   self.mdt_file)
        process.system(cmd, ignore_status=True)
        if self.is_block_device_active() is False:
            self.fail("Block devices failed to activate")

        self.log.info("Running the HTX on %s", self.block_device)
        cmd = "htxcmdline -run %s -mdt %s" % (self.block_device, self.mdt_file)
        process.system(cmd, ignore_status=True)
        for _ in range(0, self.time_limit, 60):
            self.log.info("Error logs")
            process.run('htxcmdline -geterrlog')
            if os.stat('/tmp/htxerr').st_size != 0:
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
        output = process.system_output(cmd)
        device = []
        for disk in self.block_device.split(" "):
            if disk not in output:
                device.append(disk)
        if device:
            self.log.info("block_devices %s are not avalable in %s ",
                          device, self.mdt_file)
            return False
        else:
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
        output = process.system_output(cmd).split('\n')
        device_list = self.block_device.split(" ")
        active_devices = []
        for line in output:
            for disk in device_list:
                if disk in line and 'ACTIVE' in line:
                    active_devices.append(disk)
        non_active_device = list(set(device_list) - set(active_devices))
        if non_active_device:
            return False
        else:
            self.log.info("BLOCK DEVICES %s ARE ACTIVE", self.block_device)
            return True

    def tearDown(self):
        '''
        Shutdown the mdt file and the htx daemon
        '''
        if self.is_block_device_active() is True:
            self.log.info("suspending active block_devices")
            self.suspend_all_block_device()
            self.log.info("shutting down the %s ", self.mdt_file)
            cmd = 'htxcmdline -shutdown -mdt mdt.hd'
            process.system(cmd, ignore_status=True)

        daemon_state = process.system_output('/etc/init.d/htx.d status')
        if daemon_state.split(" ")[-1] == 'running':
            process.system('/etc/init.d/htx.d stop')


if __name__ == "__main__":
    main()

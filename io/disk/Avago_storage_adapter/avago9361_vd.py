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
#
# Copyright: 2016 IBM
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>


"""
This scripts performs Virtual Drive(VD) operations on drives
"""

import time
from avocado import Test
from avocado.utils import process
from avocado import main


class Avago9361(Test):

    """
    This class contains functions for VD operations
    """

    def setUp(self):
        """
        All basic set up is done here
        """
        self.controller = int(self.params.get('controller', default='0'))
        self.tool = str(self.params.get('tool_location'))
        self.disk = str(self.params.get('disk')).split(" ")
        self.raid_level = str(self.params.get('raid_level', default='0'))
        self.size = str(self.params.get('size', default='all'))
        self.on_off = str(self.params.get('on_off'))
        self.hotspare = str(self.params.get('hotspare'))
        self.copyback = self.on_off.replace("e", "").replace("s", "").replace(
            "/", ":")
        self.add_disk = str(self.params.get('add_disk')).split(" ")
        if not self.hotspare:
            self.cancel("Hotspare test needs a drive to create/test hotspare")
        if not self.on_off:
            self.cancel("Online/Offline test needs a drive to operate on")
        if not self.disk:
            self.cancel("Please provide disk to perform VD operations")
        self.dict_raid = {'r0': [1, None], 'r1': [2, 'Multiple2'],
                          'r5': [3, None], 'r6': [3, None],
                          'r00': [4, 'Multiple2'], 'r10': [4, 'Multiple2'],
                          'r50': [6, 'Multiple3'], 'r60': [6, 'Multiple3']}
        self.value = self.dict_raid[self.raid_level]

        if len(self.disk) < self.value[0]:
            self.cancel("Please give enough number of drives to create %s"
                        % self.raid_level)
        if self.value[1] is not None:
            multiple = int(self.value[1].split("Multiple")[-1])
            self.disk = self.disk[:len(self.disk) -
                                  (len(self.disk) % multiple)]
        self.raid_disk = ",".join(self.disk).strip(" ")
        if self.raid_level == 'r10' or self.raid_level == 'r00':
            self.pdperarray = 2
        elif self.raid_level == 'r50' or self.raid_level == 'r60':
            self.pdperarray = 3
        if self.raid_level == 'r0':
            for test in ['cc', 'offline', 'rebuild', 'ghs_dhs']:
                if test in str(self.name):
                    self.cancel("Test not applicable for Raid0")
        if 'migrate' in str(self.name):
            self.raid_disk = self.disk.pop()
            if self.raid_level != 'r0':
                self.cancel("Script runs for raid0")
        self.write_policy = ['WT', 'WB', 'AWB']
        self.read_policy = ['nora', 'ra']
        self.io_policy = ['direct', 'cached']
        self.stripe = [64, 128, 256, 512, 1024]
        self.state = ['start', 'stop', 'start', 'pause', 'resume']
        self.list_test = ['online_offline', 'rebuild']
        if str(self.name) in self.list_test:
            cmd = "%s /c%d set autorebuild=off" % (self.tool, self.controller)
            self.check_pass(cmd, "Failed to set auto rebuild off")
        if 'ghs_dhs' in str(self.name):
            cmd = "%s /c%d set autorebuild=on" % (self.tool, self.controller)
            self.check_pass(cmd, "Failed to set auto rebuild on")

    def test_createall(self):
        """
        Function to create different raid level
        """
        for write in self.write_policy:
            for read in self.read_policy:
                for iopolicy in self.io_policy:
                    for stripe in self.stripe:
                        self.vd_create(write, read, iopolicy, stripe)
                        self.vd_delete()

    def test_maxvd(self):
        """
        Function to create max VD
        """
        for _ in range(1, 17):
            self.vd_create('WT', 'nora', 'direct', 1024)
        for write in self.write_policy:
            for read in self.read_policy:
                for iopolicy in self.io_policy:
                    self.change_vdpolicy(write, read, iopolicy)
        self.vd_delete()
        if self.raid_level == 'r0':
            for disk in range(0, 4):
                if disk < len(self.disk):
                    self.raid_disk = self.disk[disk]
                    for _ in range(1, 17):
                        self.vd_create('WT', 'nora', 'direct', 512)
            self.vd_delete()

    def test_init(self):
        """
        Test case to start Fast and Full init on VD
        """
        self.vd_create('WB', 'ra', 'cached', 256)
        self.full_init()
        self.vd_delete()

    def test_cc(self):
        """
        Function to do consistency operations on VD
        """
        self.vd_create('WT', 'nora', 'direct', 256)
        self.full_init()
        self.cc_operations()
        self.vd_delete()

    def test_jbod(self):
        """
        Function to format a drive to JBOD
        """
        cmd = "%s /c%d set jbod=on" % (self.tool, self.controller)
        self.check_pass(cmd, "Failed to set JBOD on")
        cmd = "%s /c%d show jbod" % (self.tool, self.controller)
        self.check_pass(cmd, "Failed to show the JBOD status")
        cmd = "%s /c%d/eall/sall set jbod" % (self.tool, self.controller)
        self.check_pass(cmd, "Failed to convert the drives to JBOD")
        cmd = "%s /c%d show " % (self.tool, self.controller)
        self.check_pass(cmd, "Failed to show the adapter details")
        cmd = "%s /c0/eall/sall set good force" % self.tool
        self.check_pass(cmd, "Failed to set JBOD drives to good")

    def test_online_offline(self):
        """
        Test to run drive Online/Offline
        """
        self.vd_create('WT', 'nora', 'direct', 256)
        for _ in range(0, 5):
            for state in ['offline', 'online']:
                self.set_online_offline(state)
                time.sleep(10)
        self.vd_delete()

    def test_ghs_dhs(self):
        """
        Test to create Global hot spare and Dedicated hot spare
        """
        self.vd_create('WT', 'nora', 'direct', 512)
        for spare in ['', 'DGs=0']:
            cmd = "%s /c%d/%s add hotsparedrive %s" % (self.tool,
                                                       self.controller,
                                                       self.hotspare, spare)
            self.check_pass(cmd, "Failed to create")
            self.set_online_offline('offline')
            self.rebuild('progress', self.hotspare)
            self.copyback_operation()
            cmd = "%s /c%d/%s delete hotsparedrive" % (self.tool,
                                                       self.controller,
                                                       self.hotspare)
            self.check_pass(cmd, "Failed to delete hotsparedrive")
        self.vd_delete()

    def copyback_state(self, state):
        """
        Helper function to run copyback test
        """
        if state == 'start':
            cmd = "%s /c%d/%s start copyback target=%s" % (self.tool,
                                                           self.controller,
                                                           self.hotspare,
                                                           self.copyback)
        else:
            cmd = "%s /c%d/%s %s copyback" % (self.tool, self.controller,
                                              self.on_off, state)
        self.check_pass(cmd, "Failed to %s copyback" % state)

    def copyback_operation(self):
        """
        Function to run copyback operations
        """
        for state in self.state:
            self.copyback_state(state)
            cmd = "%s /c%d/%s show copyback" % (self.tool, self.controller,
                                                self.on_off)
            self.showprogress(cmd)
        self.sleep_function(cmd)

    def test_rebuild(self):
        """
        Function to handle rebuild scenario
        """
        self.vd_create('WB', 'nora', 'direct', 256)
        self.set_online_offline('offline')
        self.rebuild('operations')
        self.vd_delete()

    def test_patrolread(self):
        """
        Function to handle PR operations
        """
        self.vd_create('WT', 'nora', 'direct', 256)
        self.pr_operations()
        self.vd_delete()

    def test_migrate(self):
        """
        Test case to execute Raid Migration
        """
        self.vd_create('WT', 'NORA', 'direct', 256)
        for level in [1, 5, 6]:
            if not self.add_disk:
                break
            cmd = "%s /c%d/v0 start migrate type=raid%s \
                   option=add drives=%s" % (self.tool, self.controller, level,
                                            self.add_disk.pop())
            self.check_pass(cmd, "Failed to migrate")
            cmd = "%s /c%d/v0 show migrate" % (self.tool, self.controller)
            self.showprogress(cmd)
            self.sleep_function(cmd)
        self.vd_delete()

    def rebuild(self, perform, disk=None):
        """
        Helper function of all types of rebuild operations
        """
        if perform.lower() == "operations":
            for state in self.state:
                self.rebuild_state(state)
                cmd = "%s /c%d/%s show rebuild" % (self.tool, self.controller,
                                                   self.on_off)
                self.showprogress(cmd)
            self.sleep_function(cmd)
        elif perform.lower() == "progress":
            cmd = "%s /c%d/%s show rebuild" % (self.tool, self.controller,
                                               disk)
            self.showprogress(cmd)
            self.sleep_function(cmd)

    def sleep_function(self, cmd):
        """
        Helper function for scrit to wait, till the background operation is
        complete
        """
        while self.showprogress(cmd):
            time.sleep(30)

    def rebuild_state(self, state):
        """
        Helper function for all CC operations
        """
        cmd = "%s /c%d/%s %s rebuild" % (self.tool, self.controller,
                                         self.on_off, state)
        self.check_pass(cmd, "Failed to %s Rebuild" % state)
        time.sleep(10)

    def set_online_offline(self, state):
        """
        Helper function to set drives online and offline
        """
        cmd = "%s /c%d/%s set %s" % (self.tool, self.controller,
                                     self.on_off, state)
        self.check_pass(cmd, "Failed to set drive to %s state" % state)
        self.rebuild('progress', self.hotspare)

    def jbod_show(self):
        """
        Helper function to show JBOD details
        """
        cmd = "%s /c%d show jbod" % (self.tool, self.controller)
        self.check_pass(cmd, "Failed to show the JBOD status")

    def vd_details(self):
        """
        Function to display the VD details
        """
        cmd = "%s /c%d/vall show" % (self.tool, self.controller)
        self.check_pass(cmd, "Failed to display VD configuration")

    def vd_delete(self):
        """
        Function to delete the VD
        """
        cmd = "%s /c%d/vall delete force" % (self.tool, self.controller)
        self.check_pass(cmd, "Failed to delete VD")

    def vd_create(self, write, read, iopolicy, stripe):
        """
        Function to create a VD
        """
        if self.raid_level in ['r00', 'r10', 'r50', 'r60']:
            cmd = "%s /c%d add vd %s size=%s drives=%s PDperArray=%d %s %s %s \
                   strip=%d" % (self.tool, self.controller, self.raid_level,
                                self.size, self.raid_disk, self.pdperarray,
                                write, read, iopolicy, stripe)
            self.check_pass(cmd, "Failed to create raid")

        else:
            cmd = "%s /c%d add vd %s size=%s drives=%s %s %s %s \
                   strip=%d" % (self.tool, self.controller, self.raid_level,
                                self.size, self.raid_disk, write, read,
                                iopolicy, stripe)
            self.check_pass(cmd, "Failed to create raid")
        self.vd_details()

    def check_pass(self, cmd, errmsg):
        """
        Helper function to check, if the cmd is passed or failed
        """
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail(errmsg)

    def showprogress(self, cmd):
        """
        Helper function to see progress of a given/specified operation
        """
        output = process.run(cmd, ignore_status=True, shell=True)
        if output.exit_status != 0:
            self.fail("Failed to display the progress")
        for lines in output.stdout.splitlines():
            for times in ['Hour', 'Minute', 'Second']:
                if times in lines:
                    return True

    def cc_operations(self):
        """
        Helper function CC operations
        """
        for state in self.state:
            self.cc_state(state)
            cmd = "%s /c%d/v0 show cc" % (self.tool, self.controller)
            self.showprogress(cmd)
        self.sleep_function(cmd)

    def cc_state(self, state):
        """
        Helper function for all CC operations
        """
        if state == 'start':
            cmd = "%s /c%d/v0 %s cc force" % (self.tool, self.controller,
                                              state)
        else:
            cmd = "%s /c%d/v0 %s cc" % (self.tool, self.controller, state)
        self.check_pass(cmd, "Failed to %s CC" % state)
        time.sleep(10)

    def pr_operations(self):
        """
        Helper function for PR operations
        """
        for state in self.state:
            self.pr_state(state)
            cmd = "%s /c%d show patrolread" % (self.tool, self.controller)
            self.check_pass(cmd, "Failed to show the PR progress")

    def pr_state(self, state):
        """
        Helper function for all PR operatoins
        """
        cmd = "%s /c%d %s patrolread" % (self.tool, self.controller, state)
        self.check_pass(cmd, "Failed to %s PR" % state)
        time.sleep(10)

    def full_init(self):
        """
        Helper function to start Fast/Full init
        """
        cmd = "%s /c%d/vall start init full" % (self.tool, self.controller)
        self.check_pass(cmd, "Failed to start init")
        cmd = "%s /c%d/vall show init" % (self.tool, self.controller)
        self.showprogress(cmd)
        self.sleep_function(cmd)

    def change_vdpolicy(self, write, read, iopolicy):
        """
        Helper function to change the VD policy
        """
        cmd = "%s /c%d/vall set wrcache=%s" % (self.tool, self.controller,
                                               write)
        self.check_pass(cmd, "Failed to change the write policy")
        cmd = "%s /c%d/vall set rdcache=%s" % (self.tool, self.controller,
                                               read)
        self.check_pass(cmd, "Failed to change the read policy")
        cmd = "%s /c%d/vall set iopolicy=%s" % (self.tool, self.controller,
                                                iopolicy)
        self.check_pass(cmd, "Failed to change the IO policy")

    def tearDown(self):
        """
        Function to reset the chages made for a particular test
        """
        if str(self.name) in self.list_test:
            cmd = "%s /c%d set autorebuild=on" % (self.tool, self.controller)
            self.check_pass(cmd, "Failed to set auto rebuild on")
        if 'ghs_dhs' in str(self.name):
            cmd = "%s /c%d set autorebuild=off" % (self.tool, self.controller)
            self.check_pass(cmd, "Failed to set auto rebuild off")


if __name__ == "__main__":
    main()

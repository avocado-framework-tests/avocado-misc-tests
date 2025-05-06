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
# Copyright: 2017 IBM
# Author: Pridhiviraj Paidipeddi <ppaidipe@linux.vnet.ibm.com>

"""
Mvcli Test for OpenPower based Marvell adapter 88SE9230.
"""

import re
import platform
import shutil
from avocado import Test
from avocado.utils import process, dmesg
from avocado.utils.process import CmdError


class MvcliTest(Test):

    """
    Mvcli Test, tests the different mvcli tool operations like
    info, flash, get, set, smart, locate, register, delete, create, event
    on RAID Marvell adapter 88SE9230
    """

    def setUp(self):
        """
        This fetches the mvcli asset from tool_url and make it
        executable binary for running mvcli commands with
        different options
        :param tool_url: URL location of mvcli tool
        :param fw_url: URL location of Mvcli FW
        :param fw_upgrade: <yes|no> Whether to upgrade the firmware or not
        :param adapter_id: ID of the adapter where the tests will be running
        :param pd_ids: List of phyisical disk ID's under adapter id adapter_id
        """
        if 'ppc64le' not in platform.processor():
            self.cancel("Processor is not ppc64le")
        self.tool_url = self.params.get('tool_url', '*', default=None)
        self.fw_url = self.params.get('fw_url', '*', default=None)
        self.fw_upgrade = self.params.get("fw_upgrade", '*', default="no")
        self.adapter_id = self.params.get('adapter_id', '*', default=None)
        self.pd_ids = self.params.get('pd_ids', '*', default=None).split(" ")
        path = self.fetch_asset("mvcli", locations=[self.tool_url],
                                expire="7d")
        shutil.copy(path, self.teststmpdir)
        mvcli_path = "%s/mvcli" % self.teststmpdir
        self.run_command("chmod +x %s" % mvcli_path)
        self.base = "%s %s" % (mvcli_path, self.adapter_id)
        self.base_force = "echo y | %s %s" % (mvcli_path, self.adapter_id)
        dmesg.clear_dmesg()
        if self.fw_upgrade == "yes":
            path = self.fetch_asset("fw", locations=[self.fw_url],
                                    expire="7d")
            shutil.copy(path, self.teststmpdir)
            self.fw_path = "%s/fw" % self.teststmpdir

    def run_command(self, cmd):
        """
        Run command and fail the test if any command fails
        """
        try:
            process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            self.fail("Command %s failed %s" % (cmd, details))

    @staticmethod
    def run_cmd_output(cmd):
        """
        Execute the command and return output
        """
        return process.system_output(cmd, ignore_status=True,
                                     shell=True, sudo=True)

    def test_help(self):
        """
        Get brief help for all commands or detail help for one command.
        """
        self.log.info("Mvcli help test")
        self.run_command("%s help" % self.base)

    def test_flash(self):
        """
        Flash the given firmware using given mvcli tool
        mvcli flash -a update -f /test-dir/fw.bin -t firmware
        """
        if self.fw_upgrade == "yes":
            cmd = "%s flash -a update -f %s -t firmware" \
                  % (self.base, self.fw_path)
            self.run_command(cmd)
            self.log.info("Mvcli FW Flash got success")
        else:
            self.cancel("Skipping the Mvcli FW Flash test")

    def test_info(self):
        """
        Display adapter(hba), virtual disk(vd), disk array,
               physical disk(pd), Port multiplexer(pm), expander(exp),
               block disk(blk) or spare drive information.
        """
        self.log.info("Mvcli info test")
        for obj in ["hba", "pd", "vd", "pm", "blk"]:
            self.run_command("%s info -o %s" % (self.base, obj))
        for pd in self.pd_ids:
            self.run_command("%s info -o pd -i %s" % (self.base, pd))

    def test_get(self):
        """
        Get configuration information of VD, PD, Array, HBA or Driver.
        """
        self.log.info("Mvcli get test")
        self.run_command("%s get -o hba" % self.base)
        for pd in self.pd_ids:
            self.run_command("%s get -o pd -i %s" % (self.base, pd))

    def test_set(self):
        """
        Set configuration parameters of VD, PD, HBA or Driver.
        """
        self.log.info("Mvcli set configuration parameters test")
        for state in ["on", "off"]:
            self.run_command("%s set -o hba -i %s --rawupdate%s" % (self.base,
                                                                    self.adapter_id, state))
            get_cmd = "%s get -o hba -i %s" % (self.base, self.adapter_id)
            for line in self.run_cmd_output(get_cmd).split("\n"):
                if "Raw Update:" in line and state in line:
                    self.log.info("Mvcli set --rawupdate%s operation passed \
                                  on adapter %s", state, self.adapter_id)
                    break
            else:
                self.fail("Mvcli set --rawupdate%s operation failed \
                          on adapter %s", state, self.adapter_id)

    def test_smart(self):
        """
        Display the smart info of physical disk.
        """
        self.log.info("Mvcli smart test")
        for pd in self.pd_ids:
            self.run_command("%s smart -p %s" % (self.base, pd))

    def test_locate(self):
        """
        Locate the specified PD.
        """
        self.log.info("Mvcli locate test")
        for pd in self.pd_ids:
            cmd = "%s locate -o pd -i %s -a " % (self.base, pd)
            self.run_command("%s on" % cmd)
            self.run_command("%s off" % cmd)
            self.run_command("%s on" % cmd)

    def test_register(self):
        """
        operation the register on adapter.
        test read/write mailbox registers on a test adapter
        """
        self.log.info("Mvcli register read/write test")
        for reg in ["0", "1"]:
            for value in ["1", "0"]:
                read_cmd = "%s register -t mailbox -a read -d %s" \
                           % (self.base, reg)
                write_cmd = "%s register -t mailbox -a write -d %s -v %s" \
                            % (self.base, reg, value)
                self.run_command(read_cmd)
                self.run_command(write_cmd)
                output = self.run_cmd_output(read_cmd)
                string = "register value is 0x%s." % value
                if string in output:
                    self.log.info("Mvcli read/write mailbox register %s with \
                                  value %s is passed", reg, value)
                else:
                    self.fail("Mvcli read/write mailbox register %s with \
                              value %s is failed", reg, value)

    def test_delete(self):
        """
        Delete virtual disk or spare drive.
        """
        self.log.info("Mvcli delete VD test")
        output = self.run_cmd_output("%s info -o vd" % self.base)
        if "No virtual disk is found." in output:
            self.log.info("No VD's are created yet/ skipping delete \
                          VD operation")
            return
        vd_list = []
        search_string = r"id:.*(\d)"
        for line in output.split("\n"):
            obj = re.search(search_string, line)
            if obj:
                vd_list.append(obj.group(1))
        if vd_list is None:
            self.log.info("Not able to found any VD's are found")
        self.log.info("List of VD's to be deleted: %s", vd_list)
        for vd in vd_list:
            self.run_command("%s delete -o vd -i %s" % (self.base_force, vd))
        if "No virtual disk is found." in self.run_cmd_output("%s info -o vd"
                                                              % self.base):
            self.log.info("Mvcli delete operation success")
        else:
            self.fail("Mvcli delete operation failed")

    def test_create(self):
        """
        Create virtual disk on supported raid levels
        and try to delete VD which was created
        for RAID 0, Use all disks from PD,
        for RAID 1, Use minimum of two disks from PD
        for RAID 10, Use minimum of four disks from PD
        """
        base = "%s create -o vd " % self.base_force
        pd_list_len = len(self.pd_ids)
        self.log.info("PD List %s, length: %s", self.pd_ids, pd_list_len)
        for level in ["0", "1", "10"]:
            name = "MyRaid_%s" % level
            if level == "0":
                pd_list = ",".join(self.pd_ids)
            elif level == "1":
                if pd_list_len < 2:
                    continue
                pd_list = "%s,%s" % (self.pd_ids[0], self.pd_ids[1])
            elif level == "10":
                if pd_list_len < 4:
                    continue
                pd_list = "%s,%s,%s,%s" % (self.pd_ids[0], self.pd_ids[1],
                                           self.pd_ids[2], self.pd_ids[3])
            cmd = "%s -r%s -d %s -n %s" % (base, level, pd_list, name)
            self.log.info("Mvcli RAID create level: %s, pd_list: %s, name: %s",
                          level, pd_list, name)
            self.log.info("Mvcli RAID VD create: %s", cmd)
            self.run_command(cmd)
            self.log.info("Mvcli RAID VD create success")
            self.run_command("%s info -o vd" % self.base)
            self.run_command("%s get -o vd -i 0" % self.base)
            self.run_command("%s delete -o vd -i 0" % self.base_force)
            self.log.info("Mvcli RAID VD delete success")
            output = self.run_cmd_output("%s info -o vd" % self.base)
            if "No virtual disk is found." in output:
                self.log.info("Mvcli delete operation success")
            else:
                self.fail("Mvcli delete operation failed")

    def test_event(self):
        """
        Get the current events.
        """
        self.log.info("Mvcli event test")
        self.run_command("%s event -s 10" % self.base)

    def tearDown(self):
        """
        Gather any kernels errors at the end of test
        """
        self.test_delete()
        self.log.info("Gathering any kernel errors")
        self.run_command("dmesg -T --level=alert,crit,err,warn")

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
# Author: Bismruti Bidhibrata Pattjoshi<bbidhibr@in.ibm.com>

"""
Veth DLPAR operations
"""

import time

from avocado import Test
from avocado.utils import process
from avocado.utils.network.hosts import LocalHost
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.ssh import Session


class VethdlparTest(Test):
    '''
    DLPAR veth script does veth device add,remove.
    Update the details in yaml file.
    '''

    def setUp(self):
        '''
        Gather necessary test inputs.
        '''
        self.interface = self.params.get('interface', default=None)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        self.vios_ip = self.params.get('vios_ip', '*', default=None)
        self.vios_user = self.params.get('vios_username', '*', default=None)
        self.vios_pwd = self.params.get('vios_pwd', '*', default=None)
        self.session = Session(self.vios_ip, user=self.vios_user,
                               password=self.vios_pwd)
        self.session.connect()
        local = LocalHost()
        self.networkinterface = NetworkInterface(self.interface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        cmd = "lscfg -l %s" % self.interface
        for line in process.system_output(cmd, shell=True).decode("utf-8") \
                                                          .splitlines():
            if self.interface in line:
                self.slot = line.split()[-1].split('-')[-2]
        cmd = "ioscli lsmap -all -net"
        output = self.session.cmd(cmd)
        for line in output.stdout_text.splitlines():
            if self.slot in line:
                self.iface = line.split()[0]
        cmd = "ioscli lsmap -vadapter %s -net" % self.iface
        output = self.session.cmd(cmd)
        for line in output.stdout_text.splitlines():
            if "SEA" in line:
                self.sea = line.split()[-1]
        if not self.sea:
            self.cancel("failed to get SEA")
        self.log.info(self.sea)
        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.cancel("peer connection is failed")

    def veth_dlpar_remove(self):
        '''
        veth dlpar remove operation
        '''
        cmd = "rmdev -l %s" % self.sea
        cmd_l = "echo \"%s\" | ioscli oem_setup_env" % cmd
        output = self.session.cmd(cmd_l)
        self.log.info(output.stdout_text)
        if output.exit_status != 0:
            self.fail("failed dlpar remove operation")

    def veth_dlpar_add(self):
        '''
        veth dlpar add operation
        '''
        cmd = "mkdev -l %s" % self.sea
        cmd_l = "echo \"%s\" | ioscli oem_setup_env" % cmd
        output = self.session.cmd(cmd_l)
        self.log.info(output.stdout_text)
        if output.exit_status != 0:
            self.fail("Failed dlpar add operation")

    def test_dlpar(self):
        '''
        veth dlapr remove and add operation
        '''
        for _ in range(self.num_of_dlpar):
            self.veth_dlpar_remove()
            time.sleep(30)
            self.veth_dlpar_add()
            if self.networkinterface.ping_check(self.peer_ip,
                                                count=5) is not None:
                self.fail("ping failed after add operation")

    def tearDown(self):
        self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
        self.networkinterface.restore_from_backup()
        self.session.quit()

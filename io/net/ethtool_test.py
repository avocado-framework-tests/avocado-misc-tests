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
# Copyright: 2019 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
#

"""
Tests the network driver and interface with 'ethtool' command.
Different parameters are specified in Parameters section of multiplexer file.
Interfaces are specified in Interfaces section of multiplexer file.
This test needs to be run as root.
"""

import os
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils import wait


class Ethtool(Test):
    '''
    To test different types of pings
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        smm = SoftwareManager()
        pkgs = ["ethtool", "net-tools"]
        detected_distro = distro.detect()
        if detected_distro.name == "Ubuntu":
            pkgs.extend(["iputils-ping"])
        elif detected_distro.name == "SuSE":
            pkgs.extend(["iputils"])
        else:
            pkgs.extend(["iputils"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        interfaces = os.listdir('/sys/class/net')
        local = LocalHost()
        device = self.params.get("interface")
        if device in interfaces:
            self.interface = device
        elif local.validate_mac_addr(device) and device in local.get_all_hwaddr():
            self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.interface = None
            self.cancel("Please check the network device")
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.hbond = self.params.get("hbond", default=False)
        self.peer = self.params.get("peer_ip")
        self.tx = self.params.get("tx_channel", default='')
        self.rx = self.params.get("rx_channel", default='')
        self.other = self.params.get("other_channel", default='')
        self.combined = self.params.get("combined_channel", default='')
        self.count = self.params.get("ping_count", default=500000)
        self.args = self.params.get("arg", default='')
        if not self.peer:
            self.cancel("No peer provided")
        if self.interface[0:2] == 'ib':
            self.networkinterface = NetworkInterface(self.interface, local,
                                                     if_type='Infiniband')
        elif self.hbond:
            self.networkinterface = NetworkInterface(self.interface, local,
                                                     if_type='Bond')
        else:
            self.networkinterface = NetworkInterface(self.interface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.cancel("Link up of interface is taking longer than 120s")
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.cancel("No connection to peer")
        self.elapse = self.params.get("action_elapse", default='')
        self.priv_test = self.params.get("privflag_test", default=False)
        if self.priv_test:
            cmd = "ethtool --show-priv-flags %s" % (self.interface)
            self.ret_val = process.run(cmd, shell=True, verbose=True,
                                       ignore_status=True)
            if self.ret_val.exit_status:
                self.cancel("Device Doesn't support Private flags")

    def interface_state_change(self, interface, state, status):
        '''
        Set the interface state specified, and return True if done.
        Returns False otherwise.
        '''
        cmd = "ip link set dev %s %s" % (interface, state)
        if state == "up":
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                return False
            if not wait.wait_for(self.networkinterface.is_link_up,
                                 timeout=120):
                self.fail("Link up of interface is taking longer than 120s")
        else:
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                return False
        if status != self.interface_link_status(interface):
            return False
        return True

    def interface_link_status(self, interface):
        '''
        Return the status of the interface link from ethtool.
        '''
        cmd = "ethtool %s" % interface
        for line in process.system_output(cmd, shell=True,
                                          ignore_status=True).decode("utf-8") \
                                                             .splitlines():
            if 'Link detected' in line:
                return line.split()[-1]
        return ''

    def test_ethtool(self):
        '''
        Test the ethtool args provided
        '''
        for state, status in zip(["down", "up"], ["no", "yes"]):
            if not self.interface_state_change(self.interface, state, status):
                self.fail("interface %s failed" % state)
            if self.args == "-L":
                value = [self.tx, self.rx, self.other, self.combined]
                self.param = ['tx', 'rx', 'other', 'combined']
                default = []
                cmd_l = "ethtool %s %s %s" % (
                    "-l", self.interface, self.elapse)
                output = process.run(cmd_l, shell=True, verbose=True,
                                     ignore_status=True).stdout_text \
                                                        .splitlines()[7:11]
                for i in range(len(output)):
                    default.append(output[i].split(':')[1])
                    if 'n/a' in output[i]:
                        self.param[i], value[i], default[i] = '', '', ''
                self.default_set = default.copy()
                elements = all([elem == '' for elem in value])
                if elements:
                    self.log.warn("Cannot set device channel for null")
                else:
                    for i in range(4):
                        if default[i] != '':
                            default[i] = ['0', '1', int(default[i])//2,
                                          default[i], int(default[i])+1]
                            for j in range(5):
                                if value[i] != '':
                                    cmd = "ethtool %s %s %s %s" % (
                                        self.args, self.interface,
                                        self.param[i], default[i][j])
                                    result = process.run(cmd, shell=True,
                                                         verbose=True,
                                                         ignore_status=True)
                                    if state is 'up':
                                        if self.networkinterface.ping_check(
                                           self.peer, count=5) is not None:
                                            self.cancel("ping fail value %s \
                                                    to %s parameter" % (
                                                default[i][j],
                                                self.param[i]))
                                    err_channel = "no RX or TX channel"
                                    err_count = "count exceeds maximum"
                                    if result.exit_status != 0:
                                        if err_channel in result.stderr_text:
                                            self.log.info("Cannot set %s \
                                                    value on %s parameter" % (
                                                default[i][j],
                                                self.param[i]))
                                        elif err_count in result.stderr_text:
                                            self.log.info("Cannot set %s \
                                                    value on %s parameter" % (
                                                default[i][j],
                                                self.param[i]))
                                        else:
                                            self.fail("%s %s" % (
                                                self.args, result.stderr_text))
                    cmd = (
                        f"ethtool {self.args} {self.interface} {self.param[0]} {value[0]}"
                        f"{self.param[1]} {value[1]} {self.param[2]} {value[2]}"
                        f"{self.param[3]} {value[3]}"
                        )
                    ret = process.run(cmd, shell=True, verbose=True,
                                      ignore_status=True)
                    if ret.exit_status != 0:
                        self.fail(f"{self.args} {ret.stderr_text}")
                    # Set queue values to original values
                    cmd = (
                        f"ethtool {self.args} {self.interface} {self.param[0]} {self.default_set[0]}"
                        f"{self.param[1]} {self.default_set[1]} {self.param[2]}"
                        f"{self.default_set[2]} {self.param[3]} {self.default_set[3]}"
                        )
                    ret = process.run(cmd, shell=True, verbose=True,
                                      ignore_status=True)
                    if ret.exit_status != 0:
                        self.fail("%s %s" % (self.args, ret.stderr_text))
            elif self.args == "-e":
                cmd = "ethtool %s %s >> /tmp/eeprom.log 2>&1" % (self.args, self.interface)
                ret = process.run(cmd, shell=True, verbose=True, ignore_status=True)
                if ret.exit_status != 0:
                    if "Operation not supported" in ret.stderr_text:
                        self.cancel("%s failed" % self.args)
                    else:
                        self.fail("%s failed" % self.args)
            else:
                cmd = "ethtool %s %s %s" % (
                    self.args, self.interface, self.elapse)
                ret = process.run(cmd, shell=True, verbose=True,
                                  ignore_status=True)
                if ret.exit_status != 0:
                    if "Operation not supported" in ret.stderr_text:
                        self.cancel("%s failed" % self.args)
                    else:
                        self.fail("%s failed" % self.args)
        if wait.wait_for(lambda: self.networkinterface.are_packets_lost(
                self.peer, options=['-c 10000', '-f']), timeout=30):
            self.cancel("Packet recieved in Ping flood is not 100 percent \
                         after waiting for 30sec")
        if self.priv_test:
            self.ethtool_toggle_priv_flags()

    def ethtool_toggle_priv_flags(self):
        '''
        Toggle the priv flag settings of the driver.
        '''
        priv_pass = []
        priv_fail = []
        for oper in ('toggle', 'setback'):
            for line in self.ret_val.stdout_text.splitlines():
                if "off" in line:
                    val = "on"
                else:
                    val = "off"
                if "flags" not in line:
                    priv_flag = line.split(':')[0]
                    cmd = "ethtool --set-priv-flags %s \"%s\" %s" % \
                          (self.interface, priv_flag.rstrip(), val)
                    ret1 = process.run(cmd, shell=True, verbose=True,
                                       ignore_status=True)
                    if ret1.exit_status == 0 or 'supported' in \
                       ret1.stderr_text:
                        priv_pass.append(priv_flag.rstrip())
                    else:
                        priv_fail.append(priv_flag.rstrip())
            if self.networkinterface.ping_check(self.peer, self.count,
                                                options='-f') is not None:
                self.fail("Ping failed oper = %s" % oper)
        if priv_fail:
            self.fail("Private flags could not be toggled: %s" %
                      ",".join(list(set(priv_fail))))

    def tearDown(self):
        '''
        Set the interface up at the end of test.
        '''
        self.interface_state_change(self.interface, "up", "yes")
        self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
        try:
            self.networkinterface.restore_from_backup()
        except Exception:
            self.networkinterface.remove_cfg_file()
            self.log.info("backup file not availbale, could not restore file.")

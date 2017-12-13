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
# Copyright: 2016 IBM
# Author: Basheer K<basheer@linux.vnet.ibm.com>
#
# Based on code by Hong Bo Peng <penghb@cn.ibm.com>
# copyright: 2003, 2015 IBM Corp

import os
import re
import avocado
from avocado import Test
from avocado import main
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager


def install_dependencies():
    """
    To check and install dependencies for the test
    """
    detected_distro = distro.detect()
    sm = SoftwareManager()
    if detected_distro.name == "SuSE":
        net_tools = ("net-tools", "traceroute")
    else:
        net_tools = ("net-tools", "hostname", "traceroute")
    for pkg in net_tools:
        if not sm.check_installed(pkg) and not sm.install(pkg):
            raise AssertionError("%s package is need to test" % pkg)


class Hostname(Test):
    """
    hostname: set/get hostname by cmd. Check it with the expected result.
    Test to verify the functionality of the hostname command
    """

    def setUp(self):
        install_dependencies()
        self.restore_hostname = False
        # Get Hostname
        hostname = process.system_output("hostname").strip('\n')
        if not hostname:
            # set hostname if not set
            process.system("hostname localhost.localdomain", sudo=True)
            hostname = "localhost.localdomain"
        self.hostname = hostname

    @avocado.fail_on(process.CmdError)
    def test_hostname(self):
        """
        i.Verifies hostname command options and
        ii.Test to change the hostname
        """
        output = process.system_output("hostname")
        if not output:
            self.fail("unexpected response from hostname command")

        # Verifying different options provided by hostname
        options_to_verify = self.params.get('hostname_opt', default="f")
        for option in options_to_verify:
            ret = process.run("hostname -%s" % option, ignore_status=True)
            if ret.exit_status:
                self.fail("Hostname reported non-zero status %s for option %s"
                          % (ret.exit_status, option))
            if not ret.stdout:
                self.fail("No output for %s option" % (option))

        # Test to change hostname
        myhostname_file = os.path.join(self.workdir, "MYHOSTNAME")
        myhostname = "myhost.my-domain"
        if myhostname == self.hostname:
            myhostname += '1'
        with open(myhostname_file, 'w') as fobj:
            fobj.write(myhostname)

        process.system("hostname -F %s" % myhostname_file,
                       sudo=True)
        self.restore_hostname = True
        if myhostname not in process.system_output("hostname",
                                                   env={"LANG": "C"}):
            self.fail("unexpected response from hostname -F command and " +
                      "hostname -F didn't set hostname")

    def tearDown(self):
        if self.restore_hostname:
            # Restore hostname
            process.system("hostname %s" % self.hostname,
                           sudo=True)
            if self.hostname not in process.system_output("hostname",
                                                          env={"LANG": "C"}):
                self.error("Failed to restore Hostname")


class Ifconfig(Test):
    """
    ifconfig - configure a network interface
    Test to verify the ifconfig functionality.
    """

    def setUp(self):
        if process.system("ping -c 5 -w 5 localhost", ignore_status=True):
            self.cancel("Unable to ping localhost")
        self.lo_up = True
        if "lo:1" in process.system_output("ifconfig", env={"LANG": "C"}):
            self.cancel("alias for an loopback interface is configured")
        self.alias = None
        install_dependencies()
        self.ipv6 = False
        if os.path.exists("/proc/net/if_inet6"):
            self.ipv6 = True

    @avocado.fail_on(process.CmdError)
    def test_ifconfig(self):
        """
        Verify the functionality of the ifconfig
        """
        output = process.run("ifconfig", env={"LANG": "C"})
        if "Local Loopback" not in output.stdout:
            self.fail("unexpected output of ifconfig")
        if self.ipv6:
            if "inet6" not in output.stdout:
                self.fail("Did not see IPV6 info")
        # setup and verify an alias interface
        self.alias = "lo:1"
        process.system("ifconfig %s 127.0.0.240 netmask 255.0.0.0" %
                       self.alias,
                       sudo=True)
        if "lo:1" not in process.system_output("ifconfig", env={"LANG": "C"}):
            self.fail("Failed to configure alias for loopback")

        self._remove_alias(self.alias)
        self.alias = None
        # Test to make loopback interface up and down
        process.system("ifconfig lo down", sudo=True)
        self.lo_up = False
        if not process.system("ping -c 5 -w 5 localhost", ignore_status=True):
            self.fail("Failed to change loopback interface to down state")

    @staticmethod
    def _remove_alias(name):
        process.system("ifconfig %s down" % name,
                       sudo=True)
        if "lo:1" in process.system_output("ifconfig", env={"LANG": "C"}):
            raise AssertionError("Failed to remove alias for loopback")

    @staticmethod
    def _restore_lo_intf_state():
        process.system("ifconfig lo up", sudo=True)
        if process.system("ping -c 5 -w 5 localhost", ignore_status=True):
            raise AssertionError("Failed to restore loopback interface state")

    def tearDown(self):
        errs = []
        if self.alias:
            try:
                self._remove_alias(self.alias)
            except Exception:
                errs.append("remove alias")
        if not self.lo_up:
            try:
                self._restore_lo_intf_state()
            except Exception:
                errs.append("restore lo state")
        if errs:
            self.error("Failed to: %s" % ", ".join(errs))


class Arp(Test):
    """
    arp: run it with different options. Check the return code.
    """

    def setUp(self):
        interface_out = process.system_output("ip route show default",
                                              env={"LANG": "C"})
        if "default via" not in interface_out:
            self.cancel("No active interface with deafult gateway configured")
        install_dependencies()
        search_obj = re.search(r"^default via\s+(\S+)\s+dev\s+(\w+)",
                               interface_out)
        self.default_router = search_obj.group(1)

    @avocado.fail_on(process.CmdError)
    def test_arp(self):
        """
        Test to resolve Mac addr of default gateway router using arp
        """
        process.system("ping -c 2 -w 5 %s" % self.default_router)
        output = process.run(cmd="arp -n", ignore_status=True,
                             env={"LANG": "C"})
        if output.exit_status:
            self.fail("Arp reported non zero exit status")
        if self.default_router not in output.stdout:
            self.fail("unexpected response from arp")

    def tearDown(self):
        pass


class NetworkUtilities(Test):
    """
    traceroute,traceroute6: run for localhost. It should report 1 hop.
    route: run it with -n. Check the return code.
    ipmaddr: run it and check the return code.
    """

    def setUp(self):
        install_dependencies()
        self.ipv6 = False
        if os.path.exists("/proc/net/if_inet6"):
            self.ipv6 = True

    @avocado.fail_on(process.CmdError)
    def test_traceroute(self):
        """
        Verify traceroute,traceroute6 functionality.
        """
        ret = process.run(cmd="traceroute localhost",
                          env={"LANG": "C"})
        no_of_hops = re.search(r"(\d+)\s+\S+\s*\(127.0.0.1\)",
                               ret.stdout).group(1)
        # Only one hop is required to get to localhost.
        if str(no_of_hops) != '1':
            self.fail("traceroute did not show 1 hop for localhost")

        if self.ipv6:
            detected_distro = distro.detect()
            if detected_distro.name in ("SuSE", "Ubuntu"):
                ret = process.run(cmd="traceroute6 ipv6-localhost",
                                  env={"LANG": "C"})
            else:
                ret = process.run(cmd="traceroute6 localhost6",
                                  env={"LANG": "C"})
            no_of_hops = re.search(r"(\d+)\s+\S+\s*\(::1\)",
                                   ret.stdout).group(1)
            if str(no_of_hops) != '1':
                self.fail("traceroute6 did not show 1 hop for "
                          "localhost6/ipv6-localhost")

    @avocado.fail_on(process.CmdError)
    def test_netstat(self):
        """
        Verify the functionality of netstat
        """
        # Verifying different options provided by hostname
        options_to_verify = self.params.get('netstat_opt', default="s")
        for option in options_to_verify:
            ret = process.run("netstat -%s" % option, verbose=False,
                              ignore_status=True)
            if ret.exit_status:
                self.fail("Netstat command reported non-zero status %s "
                          "for option %s" % (ret.exit_status, option))

    @avocado.fail_on(process.CmdError)
    def test_route(self):
        """
        To verify route command utility
        """
        ret = process.run(cmd="route -n", ignore_status=True)
        if ret.exit_status:
            self.fail("route command reported non-zero %s exit status" %
                      ret.exit_status)
        if self.ipv6:
            ret = process.run(cmd="route -A inet6 -n", ignore_status=True)
            if ret.exit_status:
                self.fail("route command reported non-zero %s exit status "
                          "while displaying ipv6 route table"
                          % ret.exit_status)

    @avocado.fail_on(process.CmdError)
    def test_ipmaddr(self):
        """
        To verify ipmaddr functionality
        """
        ret = process.run("ipmaddr show dev lo", ignore_status=True)
        if ret.exit_status:
            self.fail("ipmaddr reported non-zero exit status %s"
                      % ret.exit_status)
        if not ret.stdout:
            self.fail("No output for ipmaddr command")

        if self.ipv6:
            ret = process.run("ipmaddr show ipv6 dev lo", ignore_status=True)
            if ret.exit_status:
                self.fail("ipmaddr reported non-zero exit status %s"
                          % ret.exit_status)
            if not ret.stdout:
                self.fail("No output for ipmaddr command")

    def tearDown(self):
        pass


class Iptunnel(Test):
    """
    iptunnel: create sit1 and check it can be list. Then remove it and
              check it is removed from the list.
    """

    def setUp(self):
        self.tunnel = None
        ret = process.system_output("ps -aef", env={"LANG": "C"})
        if 'dhclient' in ret:
            self.cancel("Test not supported on systems running dhclient")
        install_dependencies()
        pre = process.system_output("iptunnel show")
        if "sit1" in pre:
            self.cancel("'sit1' already configured in iptunnel: %s" % pre)

    @avocado.fail_on(process.CmdError)
    def test_loopback_sit(self):
        """
        Test to add and delete the sit1
        """
        self.tunnel = "sit1"
        process.system("iptunnel add sit1 mode sit local 127.0.0.1 ttl 64",
                       sudo=True)
        ret = process.run("iptunnel show")
        if "sit1" not in ret.stdout:
            self.fail("sit1 not listed in:\n%s" % ret)
        self._remove_tunnel("sit1")
        self.tunnel = None

    @staticmethod
    def _remove_tunnel(name):
        process.system("iptunnel del %s" % name, sudo=True)
        ret = process.run("iptunnel show")
        if name in ret.stdout:
            raise AssertionError("Unable to clear tunnel %s\n %s still in the"
                                 " list:\n%s" % (name, name, ret.stdout))

    def tearDown(self):
        if self.tunnel:
            self._remove_tunnel(self.tunnel)


if __name__ == "__main__":
    main()

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
#       : Naresh Bannoth<nbannoth@in.ibm.com>
#
# Based on code by Hong Bo Peng <penghb@cn.ibm.com>
# copyright: 2003, 2015 IBM Corp

import os
import re
import avocado
from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager.manager import SoftwareManager

release = "%s%s" % (distro.detect().name, distro.detect().version)


def install_dependencies():
    """
    To check and install dependencies for the test
    """
    detected_distro = distro.detect()
    sm = SoftwareManager()
    if detected_distro.name == "SuSE":
        # net-tools-deprecated not available on modern SuSE/SLES (15+)
        # Use iproute instead on modern systems
        version_match = re.search(r'(\d+)', release)
        if version_match and int(version_match.group(1)) >= 15:
            net_tools = ("net-tools", "traceroute", "iproute2")
        else:
            net_tools = ("net-tools", "traceroute",
                         "net-tools-deprecated")
    elif detected_distro.name in ["rhel", "redhat",
                                  "Red Hat Enterprise Linux",
                                  "centos", "fedora"]:
        # RHEL/CentOS 9+ removed net-tools package, must use iproute
        # RHEL 8 has net-tools but deprecated
        # RHEL 7 and earlier use net-tools
        version_match = re.search(r'(\d+)', release)
        if version_match:
            major_version = int(version_match.group(1))
            if major_version >= 9:
                # RHEL 9+: net-tools not available, use iproute
                net_tools = ("traceroute", "iproute", "hostname")
            else:
                # RHEL 8 and earlier: net-tools available
                net_tools = ("net-tools", "hostname", "traceroute")
        else:
            net_tools = ("net-tools", "hostname", "traceroute")
    else:
        net_tools = ("net-tools", "hostname", "traceroute")
    for pkg in net_tools:
        if not sm.check_installed(pkg) and not sm.install(pkg):
            raise AssertionError("%s package is need to test" % pkg)


def is_latest_distro():
    """
    Check if running on latest distro version where net-tools are
    deprecated/removed
    - SuSE/SLES 15+
    - RHEL/CentOS 9+
    """
    detected_distro = distro.detect()
    if detected_distro.name == "SuSE":
        version_match = re.search(r'(\d+)', release)
        if version_match and int(version_match.group(1)) >= 15:
            return True
    elif detected_distro.name in ["rhel", "redhat",
                                  "Red Hat Enterprise Linux",
                                  "centos", "fedora"]:
        version_match = re.search(r'(\d+)', release)
        if version_match and int(version_match.group(1)) >= 9:
            return True
    return False


class Hostname(Test):
    """
    hostname: set/get hostname by cmd. Check it with the expected result.
    Test to verify the functionality of the hostname command
    """

    def setUp(self):
        # Initialize attributes first to prevent AttributeError
        self.restore_hostname = False
        self.hostname = None
        # Install only basic dependencies
        # (hostname is in net-tools, not net-tools-deprecated)
        detected_distro = distro.detect()
        sm = SoftwareManager()
        if detected_distro.name == "SuSE":
            deps = ("net-tools",)
        else:
            deps = ("net-tools", "hostname")
        for pkg in deps:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                raise AssertionError("%s package is need to test" % pkg)
        # Get Hostname
        hostname = process.system_output(
            "hostname").decode("utf-8").strip("\n")
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
                self.fail("Hostname reported non-zero status %s "
                          "for option %s" % (ret.exit_status, option))
            if not ret.stdout:
                self.log.warn("No output for %s option" % (option))

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
        hostname_output = process.system_output(
            "hostname", env={"LANG": "C"}).decode("utf-8")
        if myhostname not in hostname_output:
            self.fail("unexpected response from hostname -F command and "
                      "hostname -F didn't set hostname")

    def tearDown(self):
        # Check if attributes exist (setUp might have failed)
        if hasattr(self, 'restore_hostname') and self.restore_hostname:
            # Restore hostname
            process.system("hostname %s" % self.hostname,
                           sudo=True)
            hostname_output = process.system_output(
                "hostname", env={"LANG": "C"}).decode("utf-8")
            if self.hostname not in hostname_output:
                self.error("Failed to restore Hostname")


class Ifconfig(Test):
    """
    ifconfig - configure a network interface
    Test to verify the ifconfig functionality.
    """

    def setUp(self):
        # Initialize attributes first to prevent AttributeError
        self.nw_interface_up = True
        self.alias = None
        self.ipv6 = False
        self.use_modern_tools = is_latest_distro()
        self.nw_interface = "lo"  # Network interface to test
        self.alias_label = "%s:1" % self.nw_interface
        self.alias_ip = "127.0.0.240"

        if process.system("ping -c 5 -w 5 localhost",
                          ignore_status=True):
            self.cancel("Unable to ping localhost")

        install_dependencies()

        # Check for existing alias using appropriate tool
        if self.use_modern_tools:
            output = process.system_output(
                "ip addr show %s" % self.nw_interface,
                env={"LANG": "C"}).decode("utf-8")
            if self.alias_label in output or self.alias_ip in output:
                self.cancel("alias for network interface is configured")
        else:
            ifconfig_output = process.system_output(
                "ifconfig", env={"LANG": "C"}).decode("utf-8")
            if self.alias_label in ifconfig_output:
                self.cancel("alias for network interface is configured")

        if os.path.exists("/proc/net/if_inet6"):
            self.ipv6 = True

    @avocado.fail_on(process.CmdError)
    def test_ifconfig(self):
        """
        Verify the functionality of ifconfig (old) or ip addr (new)
        """
        if self.use_modern_tools:
            # Use ip command on modern systems
            output = process.run("ip addr show %s" % self.nw_interface,
                                 env={"LANG": "C"})
            stdout_text = output.stdout.decode("utf-8")
            if ("%s:" % self.nw_interface not in stdout_text or
                    "LOOPBACK" not in stdout_text):
                self.fail("unexpected output of ip addr")
            if self.ipv6:
                if "inet6" not in stdout_text:
                    self.fail("Did not see IPV6 info")

            # Setup and verify an alias interface using ip command
            self.alias = self.alias_label
            process.system("ip addr add %s/8 dev %s label %s" %
                           (self.alias_ip, self.nw_interface,
                            self.alias_label), sudo=True)
            output = process.system_output(
                "ip addr show %s" % self.nw_interface,
                env={"LANG": "C"}).decode("utf-8")
            if self.alias_ip not in output:
                self.fail("Failed to configure alias for network "
                          "interface")

            self._remove_alias(self.alias)
            self.alias = None

            # Test to make network interface up and down
            process.system("ip link set %s down" % self.nw_interface,
                           sudo=True)
            self.nw_interface_up = False
            if not process.system("ping -c 5 -w 5 localhost",
                                  ignore_status=True):
                self.fail("Failed to change network interface to down "
                          "state")
        else:
            # Use ifconfig on older systems
            output = process.run("ifconfig", env={"LANG": "C"})
            if "Local Loopback" not in output.stdout.decode("utf-8"):
                self.fail("unexpected output of ifconfig")
            if self.ipv6:
                if "inet6" not in output.stdout.decode("utf-8"):
                    self.fail("Did not see IPV6 info")

            # Setup and verify an alias interface
            self.alias = self.alias_label
            process.system("ifconfig %s %s netmask 255.0.0.0" %
                           (self.alias, self.alias_ip), sudo=True)
            ifconfig_output = process.system_output(
                "ifconfig", env={"LANG": "C"}).decode("utf-8")
            if self.alias_label not in ifconfig_output:
                self.fail("Failed to configure alias for network "
                          "interface")

            self._remove_alias(self.alias)
            self.alias = None

            # Test to make network interface up and down
            process.system("ifconfig %s down" % self.nw_interface,
                           sudo=True)
            self.nw_interface_up = False
            if not process.system("ping -c 5 -w 5 localhost",
                                  ignore_status=True):
                self.fail("Failed to change network interface to down "
                          "state")

    def _remove_alias(self, alias_name):
        if self.use_modern_tools:
            process.system("ip addr del %s/8 dev %s label %s" %
                           (self.alias_ip, self.nw_interface, alias_name),
                           sudo=True)
            output = process.system_output(
                "ip addr show %s" % self.nw_interface,
                env={"LANG": "C"}).decode("utf-8")
            if self.alias_ip in output:
                raise AssertionError("Failed to remove alias for network "
                                     "interface")
        else:
            process.system("ifconfig %s down" % alias_name, sudo=True)
            ifconfig_output = process.system_output(
                "ifconfig", env={"LANG": "C"}).decode("utf-8")
            if self.alias_label in ifconfig_output:
                raise AssertionError("Failed to remove alias for network "
                                     "interface")

    def _restore_nw_interface_state(self):
        if self.use_modern_tools:
            process.system("ip link set %s up" % self.nw_interface,
                           sudo=True)
        else:
            process.system("ifconfig %s up" % self.nw_interface,
                           sudo=True)
        if process.system("ping -c 5 -w 5 localhost",
                          ignore_status=True):
            raise AssertionError("Failed to restore network interface "
                                 "state")

    def tearDown(self):
        errs = []
        # Check if attributes exist (setUp might have failed)
        if hasattr(self, 'alias') and self.alias:
            try:
                self._remove_alias(self.alias)
            except Exception:
                errs.append("remove alias")
        if hasattr(self, 'nw_interface_up') and not self.nw_interface_up:
            try:
                self._restore_nw_interface_state()
            except Exception:
                errs.append("restore network interface state")
        if errs:
            self.error("Failed to: %s" % ", ".join(errs))


class Arp(Test):
    """
    arp: run it with different options. Check the return code.
    """
    def setUp(self):
        # Initialize attributes first
        self.default_router = None
        self.use_modern_tools = is_latest_distro()

        interface_out = process.system_output(
            "ip route show default",
            env={"LANG": "C"}).decode("utf-8")
        if "default via" not in interface_out:
            self.cancel("No active interface with default gateway "
                        "configured")
        install_dependencies()
        search_obj = re.search(r"^default via\s+(\S+)\s+dev\s+(\w+)",
                               interface_out)
        self.default_router = search_obj.group(1)

    @avocado.fail_on(process.CmdError)
    def test_arp(self):
        """
        Test to resolve Mac addr of default gateway router using
        arp (old) or ip neigh (new)
        """
        process.system("ping -c 2 -w 5 %s" % self.default_router)

        if self.use_modern_tools:
            # Use ip neigh on modern systems
            output = process.run(cmd="ip neigh show", ignore_status=True,
                                 env={"LANG": "C"})
            if output.exit_status:
                self.fail("ip neigh reported non zero exit status")
            if self.default_router not in output.stdout.decode("utf-8"):
                self.fail("unexpected response from ip neigh")
        else:
            # Use arp on older systems
            output = process.run(cmd="arp -n", ignore_status=True,
                                 env={"LANG": "C"})
            if output.exit_status:
                self.fail("Arp reported non zero exit status")
            if self.default_router not in output.stdout.decode("utf-8"):
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
        # Initialize attributes first
        self.ipv6 = False
        self.use_modern_tools = is_latest_distro()
        install_dependencies()
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
                               ret.stdout.decode("utf-8")).group(1)
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
                                   ret.stdout.decode("utf-8")).group(1)
            if str(no_of_hops) != '1':
                self.fail("traceroute6 did not show 1 hop for "
                          "localhost6/ipv6-localhost")

    @avocado.fail_on(process.CmdError)
    def test_netstat(self):
        """
        Verify the functionality of netstat (old) or ss (new)
        """
        if self.use_modern_tools:
            # Use ss command on modern systems (replacement for netstat)
            # Note: ss doesn't support all netstat options,
            # especially -g (multicast groups)
            # For unsupported options, use ip maddr instead
            options_to_verify = self.params.get('netstat_opt',
                                                default="s")
            for option in options_to_verify:
                # Remove 'g' from options as ss doesn't support
                # multicast groups
                # Use ip maddr for multicast instead
                if 'g' in option:
                    # netstat -g shows multicast groups,
                    # use ip maddr instead
                    ret = process.run("ip maddr show", verbose=False,
                                      ignore_status=True)
                    if ret.exit_status:
                        self.fail("ip maddr command reported non-zero "
                                  "status %s for multicast groups "
                                  "(netstat -g equivalent)" %
                                  ret.exit_status)
                    continue

                # Build ss command with supported options
                ss_opts = ""
                for char in option:
                    if char in ['s', 't', 'u', 'a', 'n', 'l',
                                'p', 'e', 'o', 'm', 'i']:
                        ss_opts += char

                if ss_opts:
                    ret = process.run("ss -%s" % ss_opts,
                                      verbose=False,
                                      ignore_status=True)
                    if ret.exit_status:
                        self.fail("ss command reported non-zero "
                                  "status %s for option %s" %
                                  (ret.exit_status, ss_opts))
                else:
                    # If no valid ss options, just run ss without options
                    ret = process.run("ss", verbose=False,
                                      ignore_status=True)
                    if ret.exit_status:
                        self.fail("ss command reported non-zero "
                                  "status %s" % ret.exit_status)
        else:
            # Use netstat on older systems
            options_to_verify = self.params.get('netstat_opt',
                                                default="s")
            for option in options_to_verify:
                ret = process.run("netstat -%s" % option,
                                  verbose=False,
                                  ignore_status=True)
                if ret.exit_status:
                    self.fail("Netstat command reported non-zero "
                              "status %s for option %s" %
                              (ret.exit_status, option))

    @avocado.fail_on(process.CmdError)
    def test_route(self):
        """
        To verify route (old) or ip route (new) command utility
        """
        if self.use_modern_tools:
            # Use ip route on modern systems
            ret = process.run(cmd="ip route show", ignore_status=True)
            if ret.exit_status:
                self.fail("ip route command reported non-zero %s "
                          "exit status" % ret.exit_status)
            if self.ipv6:
                ret = process.run(cmd="ip -6 route show",
                                  ignore_status=True)
                if ret.exit_status:
                    self.fail("ip -6 route command reported non-zero "
                              "%s exit status while displaying ipv6 "
                              "route table" % ret.exit_status)
        else:
            # Use route on older systems
            ret = process.run(cmd="route -n", ignore_status=True)
            if ret.exit_status:
                self.fail("route command reported non-zero %s "
                          "exit status" % ret.exit_status)
            if self.ipv6:
                ret = process.run(cmd="route -A inet6 -n",
                                  ignore_status=True)
                if ret.exit_status:
                    self.fail("route command reported non-zero %s "
                              "exit status while displaying ipv6 "
                              "route table" % ret.exit_status)

    @avocado.fail_on(process.CmdError)
    def test_ipmaddr(self):
        """
        To verify ipmaddr (old) or ip maddr (new) functionality
        """
        nw_interface = "lo"  # Network interface for multicast test

        if self.use_modern_tools:
            # Use ip maddr on modern systems
            ret = process.run("ip maddr show dev %s" % nw_interface,
                              ignore_status=True)
            if ret.exit_status:
                self.fail("ip maddr reported non-zero exit status %s"
                          % ret.exit_status)
            if not ret.stdout:
                self.fail("No output for ip maddr command")

            if self.ipv6:
                ret = process.run("ip -6 maddr show dev %s" %
                                  nw_interface, ignore_status=True)
                if ret.exit_status:
                    self.fail("ip -6 maddr reported non-zero exit "
                              "status %s" % ret.exit_status)
                if not ret.stdout.decode("utf-8"):
                    self.fail("No output for ip -6 maddr command")
        else:
            # Use ipmaddr on older systems
            ret = process.run("ipmaddr show dev %s" % nw_interface,
                              ignore_status=True)
            if ret.exit_status:
                self.fail("ipmaddr reported non-zero exit status %s"
                          % ret.exit_status)
            if not ret.stdout:
                self.fail("No output for ipmaddr command")

            if self.ipv6:
                ret = process.run("ipmaddr show ipv6 dev %s" %
                                  nw_interface, ignore_status=True)
                if ret.exit_status:
                    self.fail("ipmaddr reported non-zero exit "
                              "status %s" % ret.exit_status)
                if not ret.stdout.decode("utf-8"):
                    self.fail("No output for ipmaddr command")

    def tearDown(self):
        pass


class Iptunnel(Test):
    """
    iptunnel: create sit1 and check it can be list. Then remove it and
              check it is removed from the list.
    """

    def setUp(self):
        # Initialize attributes first
        self.tunnel = None
        self.use_modern_tools = is_latest_distro()
        self.tunnel_name = "sit1"  # SIT tunnel interface name

        ret = process.system_output(
            "ps -aef", env={"LANG": "C"}).decode("utf-8")
        if 'dhclient' in ret:
            self.cancel("Test not supported on systems running dhclient")
        install_dependencies()

        # Check for existing tunnel using appropriate tool
        if self.use_modern_tools:
            pre = process.system_output("ip tunnel show")
        else:
            pre = process.system_output("iptunnel show")

        if self.tunnel_name in pre.decode("utf-8"):
            self.cancel("'%s' tunnel already configured: %s" %
                        (self.tunnel_name, pre))

    @avocado.fail_on(process.CmdError)
    def test_loopback_sit(self):
        """
        Test to add and delete SIT tunnel using iptunnel (old) or
        ip tunnel (new)
        SIT = Simple Internet Transition (IPv6 over IPv4 tunnel)
        """
        self.tunnel = self.tunnel_name
        local_ip = "127.0.0.1"  # Loopback IP for tunnel endpoint

        if self.use_modern_tools:
            # Use ip tunnel command on modern systems
            process.system("ip tunnel add %s mode sit local %s ttl 64" %
                           (self.tunnel_name, local_ip), sudo=True)
            ret = process.run("ip tunnel show")
            if self.tunnel_name not in ret.stdout.decode("utf-8"):
                self.fail("%s tunnel not listed in:\n%s" %
                          (self.tunnel_name, ret))
        else:
            # Use iptunnel command on older systems
            process.system("iptunnel add %s mode sit local %s ttl 64" %
                           (self.tunnel_name, local_ip), sudo=True)
            ret = process.run("iptunnel show")
            if self.tunnel_name not in ret.stdout.decode("utf-8"):
                self.fail("%s tunnel not listed in:\n%s" %
                          (self.tunnel_name, ret))

        self._remove_tunnel(self.tunnel_name)
        self.tunnel = None

    def _remove_tunnel(self, tunnel_name):
        """Remove tunnel interface"""
        if self.use_modern_tools:
            process.system("ip tunnel del %s" % tunnel_name, sudo=True)
            ret = process.run("ip tunnel show")
        else:
            process.system("iptunnel del %s" % tunnel_name, sudo=True)
            ret = process.run("iptunnel show")

        if tunnel_name in ret.stdout.decode("utf-8"):
            raise AssertionError("Unable to clear tunnel %s\n %s still "
                                 "in the list:\n%s" %
                                 (tunnel_name, tunnel_name, ret.stdout))

    def tearDown(self):
        # Check if attribute exists (setUp might have failed)
        if hasattr(self, 'tunnel') and self.tunnel:
            self._remove_tunnel(self.tunnel)

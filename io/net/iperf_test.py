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
# Copyright: 2018 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
iperf is a tool for active measurements of the maximum achievable
bandwidth on IP networks.
"""

import os
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process
from avocado.utils.genio import read_file
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.ssh import Session
from avocado.utils.process import SubProcess
from avocado.utils import distro


class Iperf(Test):
    """
    Iperf Test
    """

    def setUp(self):
        """
        To check and install dependencies for the test
        """
        localhost = LocalHost()
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.peer_public_ip = self.params.get("peer_public_ip", default="")
        self.peer_password = self.params.get("peer_password", '*',
                                             default=None)
        interfaces = os.listdir('/sys/class/net')
        device = self.params.get("interface", default="")
        if device in interfaces:
            self.iface = device
        elif localhost.validate_mac_addr(device) and device in localhost.get_all_hwaddr():
            self.iface = localhost.get_interface_by_hwaddr(device).name
        else:
            self.iface = None
            self.cancel("%s interface is not available" % device)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.hbond = self.params.get("hbond", default=False)
        if self.hbond:
            self.networkinterface = NetworkInterface(self.iface, localhost,
                                                     if_type='Bond')
        else:
            self.networkinterface = NetworkInterface(self.iface, localhost)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel("failed connecting to peer")
        smm = SoftwareManager()
        for pkg in ["gcc", "autoconf", "perl", "m4", "libtool", "gcc-c++", "flex", "bison"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
            cmd = "%s install %s" % (smm.backend.base_command, pkg)
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.cancel("unable to install the package %s on peer machine "
                            % pkg)

        detected_distro = distro.detect()
        pkg = "nmap"
        if detected_distro.name == 'rhel':
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package Can not install" % pkg)
        if detected_distro.name == "SuSE":
            self.nmap = os.path.join(self.teststmpdir, 'nmap')
            nmap_download = self.params.get("nmap_download", default="https:"
                                            "//nmap.org/dist/"
                                            "nmap-7.93.tar.bz2")
            tarball = self.fetch_asset(nmap_download)
            self.version = os.path.basename(tarball.split('.tar')[0])
            self.n_map = os.path.join(self.nmap, self.version)
            archive.extract(tarball, self.nmap)
            os.chdir(self.n_map)
            process.system('./configure ppc64le', shell=True)
            build.make(self.n_map)
            process.system('./nping/nping -h', shell=True)

        if detected_distro.name == "Ubuntu":
            cmd_fw = "service ufw stop"
        elif detected_distro.name in ['rhel', 'fedora', 'redhat']:
            cmd_fw = "systemctl stop firewalld"
        elif detected_distro.name == "SuSE":
            if detected_distro.version >= 15:
                cmd_fw = "systemctl stop firewalld"
            else:
                cmd_fw = "rcSuSEfirewall2 stop"
        elif detected_distro.name == "centos":
            cmd_fw = "service iptables stop"
        else:
            self.cancel("Distro not supported")
        if process.system(cmd_fw, ignore_status=True, shell=True) != 0:
            self.cancel("Unable to disable firewall on host")
        output = self.session.cmd(cmd_fw)
        if output.exit_status != 0:
            self.cancel("Unable to disable firewall service on peer")

        if self.peer_ip == "":
            self.cancel("%s peer machine is not available" % self.peer_ip)
        self.mtu = self.params.get("mtu", default=1500)
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)
        self.peer_interface = self.remotehost.get_interface_by_ipaddr(
            self.peer_ip).name
        self.peer_networkinterface = NetworkInterface(self.peer_interface,
                                                      self.remotehost)
        self.remotehost_public = RemoteHost(
            self.peer_public_ip, self.peer_user,
            password=self.peer_password)
        self.peer_public_networkinterface = NetworkInterface(
            self.peer_interface, self.remotehost_public)
        if self.peer_networkinterface.set_mtu(self.mtu) is not None:
            self.cancel("Failed to set mtu in peer")
        if self.networkinterface.set_mtu(self.mtu) is not None:
            self.cancel("Failed to set mtu in host")
        self.iperf = os.path.join(self.teststmpdir, 'iperf')
        iperf_download = self.params.get("iperf_download", default="https:"
                                         "//sourceforge.net/projects/iperf2/"
                                         "files/iperf-2.1.9.tar.gz")
        tarball = self.fetch_asset(iperf_download, expire='7d')
        archive.extract(tarball, self.iperf)
        self.version = os.path.basename(tarball.split('.tar')[0])
        self.iperf_dir = os.path.join(self.iperf, self.version)
        destination = "%s:/tmp" % self.peer_ip
        output = self.session.copy_files(self.iperf_dir, destination,
                                         recursive=True)
        if not output:
            self.cancel("unable to copy the iperf into peer machine")
        cmd = "cd /tmp/%s;./configure ppc64le;make" % self.version
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.cancel("Unable to compile Iperf into peer machine")
        self.iperf_run = str(self.params.get("PERF_SERVER_RUN", default=False))
        if self.iperf_run:
            cmd = "/tmp/%s/src/iperf -s" % self.version
            cmd = self.session.get_raw_ssh_command(cmd)
            self.obj = SubProcess(cmd)
            self.obj.start()
        os.chdir(self.iperf_dir)
        process.system('./configure', shell=True)
        build.make(self.iperf_dir)
        self.iperf = os.path.join(self.iperf_dir, 'src')
        self.expected_tp = self.params.get("EXPECTED_THROUGHPUT", default="85")

    def nping(self):
        """
        Run nping test with tcp packets
        """
        detected_distro = distro.detect()
        if detected_distro.name == "SuSE":
            os.chdir(self.n_map)
            cmd = "./nping/nping --tcp %s -c 10" % self.peer_ip
            return process.run(cmd, verbose=False, shell=True)
        else:
            cmd = "nping --tcp %s -c 10" % self.peer_ip
            return process.run(cmd, verbose=False, shell=True)

    def test(self):
        """
        Test run is a One way throughput test. In this test, we have one host
        transmitting (or receiving) data from a client. This transmit large
        messages using multiple threads or processes.
        """
        speed = int(read_file("/sys/class/net/%s/speed" % self.iface))
        if speed == 100000:
            iperf_pthread = 10
        elif speed == 25000:
            iperf_pthread = 4
        os.chdir(self.iperf)
        if self.networkinterface.is_vnic() or self.hbond:
            cmd = "iperf -c %s -P %s -t 20 -i 5" % (self.peer_ip, iperf_pthread)
        else:
            cmd = "./iperf -c %s" % self.peer_ip
        result = process.run(cmd, shell=True, ignore_status=True)
        nping_result = self.nping()
        if result.exit_status:
            self.fail("FAIL: Iperf Run failed")
        if self.networkinterface.is_vnic() or self.hbond:
            for line in result.stdout.decode("utf-8").splitlines():
                if 'SUM' in line and 'Mbits/sec' in line:
                    tput = int(line.split()[5])
                elif 'SUM' in line and 'Gbits/sec' in line:
                    tput = int(float(line.split()[5])) * 1000
                elif 'SUM' in line and 'Kbits/sec' in line:
                    tput = int(float(line.split()[5])) / 1000
        else:
            for line in result.stdout.decode("utf-8").splitlines():
                if 'local {}'.format(self.ipaddr) in line:
                    id = line[3]
            for line in result.stdout.decode("utf-8").splitlines():
                if id in line and 'Mbits/sec' in line:
                    tput = int(line.split()[6])
                elif id in line and 'Gbits/sec' in line:
                    tput = int(float(line.split()[6])) * 1000
                elif id in line and 'Kbits/sec' in line:
                    tput = int(float(line.split()[6])) / 1000
        if tput < (int(self.expected_tp) * speed) / 100:
            self.fail("FAIL: Throughput Actual - %s%%, Expected - %s%%"
                      ", Throughput Actual value - %s "
                      % (round((tput*100)/speed, 4), self.expected_tp,
                         str(tput)+'Mb/sec'))
        for line in nping_result.stdout.decode("utf-8").splitlines():
            if 'Raw packets' in line:
                lost = int(line.split("|")[2].split(" ")[2])*10
                if lost > 60:
                    self.fail("FAIL: Ping fails after iperf test")

    def tearDown(self):
        """
        Killing Iperf process in peer machine
        """
        if self.iface:
            cmd = "pkill iperf; rm -rf /tmp/%s" % self.version
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.fail("Either the ssh to peer machine machine\
                          failed or iperf process was not killed")
            self.obj.stop()
            if self.networkinterface.set_mtu('1500') is not None:
                self.cancel("Failed to set mtu in host")
            try:
                self.peer_networkinterface.set_mtu('1500')
            except Exception:
                self.peer_public_networkinterface.set_mtu('1500')
            self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
            try:
                self.networkinterface.restore_from_backup()
            except Exception:
                self.networkinterface.remove_cfg_file()
                self.log.info("backup file not available, could not restore file.")
            if self.hbond:
                self.networkinterface.restore_slave_cfg_file()
            self.remotehost.remote_session.quit()
            if hasattr(self, 'remotehost_public'):
                self.remotehost_public.remote_session.quit()
            self.session.quit()

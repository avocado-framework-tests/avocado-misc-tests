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
# Author: Pridhiviraj Paidipeddi <ppaidipe@linux.vnet.ibm.com>
# Author: Vaishnavi Bhat <vaishnavi@linux.vnet.ibm.com>
# this script run IO stress on nic devices for give time.

import os
import re
import time
import shutil

from avocado import Test
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.ssh import Session


class HtxNicTest(Test):

    """
    HTX [Hardware Test eXecutive] is a test tool suite. The goal of HTX is to
    stress test the system by exercising all hardware components concurrently
    in order to uncover any hardware design flaws and hardware hardware or
    hardware-software interaction issues.
    :see:https://github.com/open-power/HTX.git
    :param mdt_file: mdt file used to trigger HTX
    :params time_limit: how much time(hours) you want to run this stress.
    :param host_public_ip: Public IP address of host
    :param peer_public_ip: Public IP address of peer
    :param peer_password: password of peer for peer_user user
    :param peer_user: User name of Peer
    :param host_interfaces: Host N/W Interface's to run HTX on
    :param peer_interfaces: Peer N/W Interface's to run HTX on
    :param net_ids: Net id's of N/W Interface's
    """

    def setUp(self):
        """
        Set up
        """
        if 'ppc64' not in process.system_output('uname -a', ignore_status=True,
                                                shell=True,
                                                sudo=True).decode("utf-8"):
            self.cancel("Platform does not support HTX tests")

        self.localhost = LocalHost()
        self.parameters()
        self.host_distro = distro.detect()
        self.host_distro_name = self.host_distro.name
        self.host_distro_version = self.host_distro.version
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel("failed connecting to peer")
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)
        # Disable firewall on the host and peer
        if self.host_distro_name in ['rhel', 'fedora', 'redhat']:
            cmd = "systemctl stop firewalld"
        elif self.host_distro_name == "SuSE":
            if self.host_distro_version >= 15:
                cmd = "systemctl stop firewalld"
            else:
                cmd = "rcSuSEfirewall2 stop"
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.cancel("Unable to disable firewall on host")
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.cancel("Unable to disable firewall on peer")

        if 'start' in str(self.name.name):
            # Flush out the ip addresses on host before starting the test
            for interface in self.host_intfs:
                cmd = 'ip addr flush dev %s' % interface
                process.run(cmd, shell=True, sudo=True, ignore_status=True)
                cmd = 'ip link set dev %s up' % interface
                process.run(cmd, shell=True, sudo=True, ignore_status=True)

            # Flush out the ip addresses on peer before starting the test
            for peer_interface in self.peer_intfs:
                cmd = 'ip addr flush dev %s' % peer_interface
                self.session.cmd(cmd)
                cmd = 'ip link set dev %s up' % peer_interface
                self.session.cmd(cmd)

        self.get_peer_distro()
        self.get_peer_distro_version()
        self.htx_rpm_link = self.params.get('htx_rpm_link', default=None)

    def get_peer_distro_version(self):
        """
        Get the distro version installed on peer lpar
        """
        detected_distro = distro.detect(session=self.session)
        self.peer_distro_version = detected_distro.version

    def get_peer_distro(self):
        """
        Get the distro installed on peer lpar
        """
        detected_distro = distro.detect(session=self.session)
        if detected_distro.name == "Ubuntu":
            self.peer_distro = "Ubuntu"
        elif detected_distro.name == "rhel":
            self.peer_distro = "rhel"
        elif detected_distro.name == "SuSE":
            self.peer_distro = "SuSE"
        else:
            self.fail("Unknown peer distro type")
        self.log.info("Peer distro is %s", self.peer_distro)

    def build_htx(self):
        """
        Build 'HTX'
        """
        packages = ['git', 'gcc', 'make', 'wget']
        detected_distro = distro.detect()
        if detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif detected_distro.name == "Ubuntu":
            packages.extend(['libncurses5', 'g++', 'ncurses-dev',
                             'libncurses-dev', 'tar', 'wget'])
        elif detected_distro.name == 'SuSE':
            packages.extend(['libncurses6', 'gcc-c++',
                            'ncurses-devel', 'tar', 'wget'])
        else:
            self.cancel("Test not supported in  %s" % detected_distro.name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Can not install %s" % pkg)
            cmd = "%s install %s" % (smm.backend.base_command, pkg)
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.cancel(
                    "Unable to install the package %s on peer machine" % pkg)

        # Deleting old htx rpms as sometimes the old rpm packages doesn't
        # support the latest htx changes. Also old  multiple htx rpms must be
        # deleted before starting the htx on multisystems for NIC devices
        ins_htx = process.system_output('rpm -qa | grep htx', shell=True,
                                        sudo=True, ignore_status=True)
        ins_htx = ins_htx.decode("utf-8").splitlines()
        if ins_htx:
            for rpm in ins_htx:
                process.run("rpm -e %s" % rpm, shell=True, sudo=True,
                            ignore_status=True, timeout=30)
                if os.path.exists('/usr/lpp/htx'):
                    shutil.rmtree('/usr/lpp/htx')
            self.log.info("Deleted old htx rpm packages from host")

        peer_ins_htx = self.session.cmd('rpm -qa | grep htx')
        peer_ins_htx = peer_ins_htx.stdout.decode("utf-8").splitlines()
        if peer_ins_htx:
            for rpm in peer_ins_htx:
                self.session.cmd('rpm -e %s' % rpm)
            self.log.info("Deleted old htx rpm package from peer")

        if self.host_distro_name and self.peer_distro == "SuSE":
            self.host_distro_name = self.peer_distro = "sles"

        host_distro_pattern = "%s%s" % (
                                        self.host_distro_name,
                                        self.host_distro_version)
        peer_distro_pattern = "%s%s" % (
                                        self.peer_distro,
                                        self.peer_distro_version)
        patterns = [host_distro_pattern, peer_distro_pattern]
        for pattern in patterns:
            temp_string = process.getoutput(
                          "curl --silent %s" % (self.htx_rpm_link),
                          verbose=False, shell=True, ignore_status=True)
            matching_htx_versions = re.findall(
                r"(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*", str(temp_string))
            distro_specific_htx_versions = [htx_rpm
                                            for htx_rpm
                                            in matching_htx_versions
                                            if pattern in htx_rpm]
            distro_specific_htx_versions.sort(reverse=True)
            self.latest_htx_rpm = distro_specific_htx_versions[0]

            cmd = ('rpm -ivh --nodeps %s%s '
                   '--force' % (self.htx_rpm_link,
                                self.latest_htx_rpm))
            # If host and peer distro is same then perform installation
            # only one time. This check is to avoid multiple times installation
            if host_distro_pattern == peer_distro_pattern:
                if process.system(cmd, shell=True, ignore_status=True):
                    self.cancel("Installation of rpm failed")
                output = self.session.cmd(cmd)
                if not output.exit_status == 0:
                    self.cancel("Unable to install the package %s %s"
                                " on peer machine" % (self.htx_rpm_link,
                                                      self.latest_htx_rpm))
                break
            if pattern == host_distro_pattern:
                if process.system(cmd, shell=True, ignore_status=True):
                    self.cancel("Installation of rpm failed")

            if pattern == peer_distro_pattern:
                output = self.session.cmd(cmd)
                if not output.exit_status == 0:
                    self.cancel("Unable to install the package %s %s"
                                " on peer machine" % (self.htx_rpm_link,
                                                      self.latest_htx_rpm))

    def parameters(self):
        self.host_intfs = []
        self.host_ip = self.params.get("host_public_ip", '*', default=None)
        self.peer_ip = self.params.get("peer_public_ip", '*', default=None)
        self.peer_user = self.params.get("peer_user", '*', default=None)
        self.peer_password = self.params.get("peer_password",
                                             '*', default=None)
        devices = self.params.get("htx_host_interfaces", '*', default=None)
        if devices:
            interfaces = os.listdir('/sys/class/net')
        for device in devices.split(" "):
            if device in interfaces:
                self.host_intfs.append(device)
            elif self.localhost.validate_mac_addr(
                 device) and device in self.localhost.get_all_hwaddr():
                self.host_intfs.append(self.localhost.get_interface_by_hwaddr(
                                       device).name)
            else:
                self.cancel("Please check the network device")
        self.peer_intfs = self.params.get("peer_interfaces",
                                          '*', default=None).split(" ")
        self.mdt_file = self.params.get("mdt_file", '*', default="net.mdt")
        self.time_limit = int(self.params.get("time_limit",
                                              '*', default=2)) * 60
        self.query_cmd = "htxcmdline -query -mdt %s" % self.mdt_file
        self.htx_url = self.params.get("htx_rpm", default="")

    def test_start(self):
        """
        This test will be in two phases
        Phase 1: Configure all necessary pre-setup steps for both the
                 interfaces in both Host & Peer
        Phase 2: Start the HTX setup & execution of test.
        """
        self.build_htx()
        self.htx_configuration()
        self.run_htx()

    def test_check(self):
        self.monitor_htx_run()

    def test_stop(self):
        self.htx_cleanup()

    def htx_configuration(self):
        """
        The function is to setup network topology for htx run
        on both host and peer.
        The build_net multisystem <hostname/IP> command
        configures the network interfaces on both host and peer Lpars with
        some random net_ids and check pingum and also
        starts the htx daemon for net.mdt
        There is no need to explicitly start the htx daemon, create/select
        nd activate for net.mdt
        """
        self.log.info("Setting up the Network configuration on Host and Peer")

        cmd = "build_net multisystem %s" % self.peer_ip
        output = process.system_output(cmd, ignore_status=True, shell=True,
                                       sudo=True)
        output = output.decode("utf-8")
        host_obj = re.search("All networks ping Ok", output)

        # try up to 3 times if the command fails to set the network interfaces
        for i in range(3):
            if host_obj is not None:
                self.log.info("Htx setup was successful on host and peer")
                break
        output = process.system_output('pingum', ignore_status=True,
                                       shell=True, sudo=True)
        output = output.decode("utf-8")
        ping_obj = re.search("All networks ping Ok", output)
        if ping_obj is None:
            self.fail("Failed to set htx configuration on host and peer")

    def run_htx(self):
        self.start_htx_run()

    def start_htx_run(self):
        self.log.info("Running the HTX for %s on Host", self.mdt_file)
        # Find and Kill existing HXE process if running
        hxe_pid = process.getoutput("pgrep -f hxe")
        if hxe_pid:
            self.log.info("HXE is already running with PID: %s. Killing it.", hxe_pid)
            process.run("hcl -shutdown", ignore_status=True)
            time.sleep(20)
        cmd = "htxcmdline -run -mdt %s" % self.mdt_file
        process.run(cmd, shell=True, sudo=True)

        self.log.info("Running the HTX for %s on Peer", self.mdt_file)
        self.session.cmd(cmd)

    def monitor_htx_run(self):
        for time_loop in range(0, self.time_limit, 60):
            self.log.info("Monitoring HTX Error logs in Host")
            cmd = 'htxcmdline -geterrlog'
            process.run(cmd, ignore_status=True,
                        shell=True, sudo=True)
            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("Their are errors while htx run in host")
            self.log.info("Monitoring HTX Error logs in Peer")
            self.session.cmd(cmd)
            output = self.session.cmd('test -s /tmp/htxerr')
            if not output.exit_status == 0:
                rc = False
            else:
                rc = True
            if rc:
                output = self.session.cmd("cat /tmp/htxerr")
                self.log.debug("HTX error log in peer: %s\n",
                               "\n".join(output.stdout.decode("utf-8")))
                self.fail("Their are errors while htx run in peer")
            self.log.info("Status of N/W devices after every 60 sec")
            process.system(self.query_cmd, ignore_status=True,
                           shell=True, sudo=True)

            output = self.session.cmd(self.query_cmd)
            if not output.exit_status == 0:
                self.log.info("query o/p in peer lpar\n %s", "\n".join(output))
            time.sleep(60)

    def shutdown_active_mdt(self):
        self.log.info("Shutdown active mdt in host")
        cmd = "htxcmdline -shutdown"
        process.run(cmd, timeout=120, ignore_status=True,
                    shell=True, sudo=True)
        self.log.info("Shutdown active mdt in peer")
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            pass

    def shutdown_htx_daemon(self):
        status_cmd = '/usr/lpp/htx/etc/scripts/htx.d status'
        shutdown_cmd = '/usr/lpp/htx/etc/scripts/htxd_shutdown'
        daemon_state = process.system_output(status_cmd, ignore_status=True,
                                             shell=True,
                                             sudo=True).decode("utf-8")
        if daemon_state.split(" ")[-1] == 'running':
            process.system(shutdown_cmd, ignore_status=True,
                           shell=True, sudo=True)
        try:
            output = self.session.cmd(status_cmd)
        except Exception:
            self.log.info("Unable to get peer htxd status")
        if not output.exit_status == 0:
            pass
        line = output.stdout.decode("utf-8").splitlines()
        if 'running' in line[0]:
            self.session.cmd(shutdown_cmd)
            if not output.exit_status == 0:
                pass

    def ip_restore_host(self):
        '''
        restoring ip for host
        '''
        for interface in self.host_intfs:
            cmd = "ip addr flush %s" % interface
            process.run(cmd, ignore_status=True, shell=True, sudo=True)
            networkinterface = NetworkInterface(interface, self.localhost)
            networkinterface.bring_up()

    def ip_restore_peer(self):
        '''
        config ip for peer
        '''
        for interface in self.peer_intfs:
            cmd = "ip addr flush %s" % interface
            self.session.cmd(cmd)
            peer_networkinterface = NetworkInterface(
                interface, self.remotehost)
            peer_networkinterface.bring_up()

    def htx_cleanup(self):
        self.shutdown_htx_daemon()
        self.ip_restore_host()
        self.ip_restore_peer()
        self.remotehost.remote_session.quit()

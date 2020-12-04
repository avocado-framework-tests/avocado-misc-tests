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
# this script run IO stress on nic devices for give time.

import os
import re
import time
try:
    import pxssh
except ImportError:
    from pexpect import pxssh

from avocado import Test
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import build
from avocado.utils import archive
from avocado.utils.process import CmdError
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost


class CommandFailed(Exception):
    def __init__(self, command, output, exitcode):
        self.command = command
        self.output = output
        self.exitcode = exitcode

    def __str__(self):
        return "Command '%s' exited with %d.\nOutput:\n%s" \
               % (self.command, self.exitcode, self.output)


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

        self.parameters()
        self.localhost = LocalHost()
        if 'start' in str(self.name.name):
            for ipaddr, interface in zip(self.ipaddr, self.host_intfs):
                networkinterface = NetworkInterface(interface, self.localhost)
                try:
                    networkinterface.add_ipaddr(ipaddr, self.netmask)
                    networkinterface.save(ipaddr, self.netmask)
                except Exception:
                    networkinterface.save(ipaddr, self.netmask)
                networkinterface.bring_up()
        self.host_distro = distro.detect()
        self.login(self.peer_ip, self.peer_user, self.peer_password)
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)
        self.get_peer_distro()

    def build_htx(self):
        """
        Build 'HTX'
        """
        packages = ['git', 'gcc', 'make']
        detected_distro = distro.detect()
        if detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif detected_distro.name == "Ubuntu":
            packages.extend(['libncurses5', 'g++', 'ncurses-dev',
                             'libncurses-dev', 'tar'])
        elif detected_distro.name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            self.cancel("Test not supported in  %s" % detected_distro.name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Can not install %s" % pkg)
            try:
                cmd = "%s install %s" % (smm.backend.base_command, pkg)
                self.run_command(cmd)
            except CommandFailed:
                self.cancel("unable to install the package %s on peer machine"
                            % pkg)
        if self.htx_url:
            htx = self.htx_url.split("/")[-1]
            htx_rpm = self.fetch_asset(self.htx_url)
            process.system("rpm -ivh --force %s" % htx_rpm)
            self.run_command("wget %s -O /tmp/%s" % (self.htx_url, htx))
            self.run_command("cd /tmp")
            self.run_command("rpm -ivh --force %s" % htx)
        else:
            url = "https://github.com/open-power/HTX/archive/master.zip"
            tarball = self.fetch_asset("htx.zip", locations=[url], expire='7d')
            archive.extract(tarball, self.teststmpdir)
            htx_path = os.path.join(self.teststmpdir, "HTX-master")
            os.chdir(htx_path)

            exercisers = ["hxecapi_afu_dir", "hxecapi", "hxeocapi"]
            if not smm.check_installed('dapl-devel'):
                exercisers.append("hxedapl")
            for exerciser in exercisers:
                process.run("sed -i 's/%s//g' %s/bin/Makefile" % (exerciser,
                                                                  htx_path))
            build.make(htx_path, extra_args='all')
            build.make(htx_path, extra_args='tar')
            process.run('tar --touch -xvzf htx_package.tar.gz')
            os.chdir('htx_package')
            if process.system('./installer.sh -f'):
                self.fail("Installation of htx fails:please refer job.log")

            try:
                self.run_command("wget %s -O /tmp/master.zip" % url)
                self.run_command("cd /tmp")
                self.run_command("unzip master.zip")
                self.run_command("cd HTX-master")
                for exerciser in exercisers:
                    self.run_command("sed -i 's/%s//g' bin/Makefile" % exerciser)
                self.run_command("make all")
                self.run_command("make tar")
                self.run_command("tar --touch -xvzf htx_package.tar.gz")
                self.run_command("cd htx_package")
                self.run_command("./installer.sh -f")
            except CommandFailed:
                self.cancel("HTX is not installed on Peer")

    def parameters(self):
        self.host_ip = self.params.get("host_public_ip", '*', default=None)
        self.peer_ip = self.params.get("peer_public_ip", '*', default=None)
        self.peer_user = self.params.get("peer_user", '*', default=None)
        self.peer_password = self.params.get("peer_password",
                                             '*', default=None)
        self.host_intfs = self.params.get("htx_host_interfaces",
                                          '*', default=None).split(" ")
        self.peer_intfs = self.params.get("peer_interfaces",
                                          '*', default=None).split(" ")
        self.net_ids = self.params.get("net_ids", '*', default=None).split(" ")
        self.mdt_file = self.params.get("mdt_file", '*', default="net.mdt")
        self.time_limit = int(self.params.get("time_limit",
                                              '*', default=2)) * 60
        self.query_cmd = "htxcmdline -query -mdt %s" % self.mdt_file
        self.ipaddr = self.params.get("host_ips", default="").split(" ")
        self.netmask = self.params.get("netmask", default="")
        self.peer_ips = self.params.get("peer_ips", default="").split(" ")
        self.htx_url = self.params.get("htx_rpm", default="")

    def login(self, ip, username, password):
        '''
        SSH Login method for remote server
        '''
        pxh = pxssh.pxssh(encoding='utf-8')
        # Work-around for old pxssh not having options= parameter
        pxh.SSH_OPTS = "%s  -o 'StrictHostKeyChecking=no'" % pxh.SSH_OPTS
        pxh.SSH_OPTS = "%s  -o 'UserKnownHostsFile /dev/null' " % pxh.SSH_OPTS
        pxh.force_password = True

        pxh.login(ip, username, password)
        pxh.sendline()
        pxh.prompt(timeout=60)
        pxh.sendline('exec bash --norc --noprofile')
        pxh.prompt(timeout=60)
        # Ubuntu likes to be "helpful" and alias grep to
        # include color, which isn't helpful at all. So let's
        # go back to absolutely no messing around with the shell
        pxh.set_unique_prompt()
        pxh.prompt(timeout=60)
        self.pxssh = pxh

    def run_command(self, command, timeout=300):
        '''
        SSH Run command method for running commands on remote server
        '''
        self.log.info("Running the command on peer lpar: %s", command)
        if not hasattr(self, 'pxssh'):
            self.fail("SSH Console setup is not yet done")
        con = self.pxssh
        con.sendline(command)
        con.expect("\n")  # from us
        con.expect(con.PROMPT, timeout=timeout)
        output = con.before.splitlines()
        con.sendline("echo $?")
        con.prompt(timeout)
        exitcode = int(''.join(con.before.splitlines()[1:]))
        if exitcode != 0 and exitcode != 43:
            raise CommandFailed(command, output, exitcode)
        return output

    def get_peer_distro(self):
        res = self.run_command("cat /etc/os-release")
        output = "\n".join(res)
        if "ubuntu" in output:
            self.peer_distro = "Ubuntu"
        elif "rhel" in output:
            self.peer_distro = "rhel"
        elif "sles" in output:
            self.peer_distro = "SuSE"
        else:
            self.fail("Unknown peer distro type")
        self.log.info("Peer distro is %s", self.peer_distro)

    def test_start(self):
        """
        This test will be in two phases
        Phase 1: Configure all necessary pre-setup steps for both the
                 interfaces in both Host & Peer
        Phase 2: Start the HTX setup & execution of test.
        """
        self.build_htx()
        self.setup_htx_nic()
        self.run_htx()

    def test_check(self):
        self.monitor_htx_run()

    def test_stop(self):
        self.htx_cleanup()

    def setup_htx_nic(self):
        self.update_host_peer_names()
        self.generate_bpt_file()
        self.check_bpt_file_existence()
        self.update_otherids_in_bpt()
        self.update_net_ids_in_bpt()
        self.htx_configure_net()

    def update_host_peer_names(self):
        """
        Update hostname & ip of both Host & Peer in /etc/hosts file of both
        Host & Peer
        """
        host_name = process.system_output("hostname", ignore_status=True,
                                          shell=True, sudo=True).decode("utf-8")
        peer_name = self.run_command("hostname")[-1]
        hosts_file = '/etc/hosts'
        self.log.info("Updating hostname of both Host & Peer in \
                      %s file", hosts_file)
        with open(hosts_file, 'r') as file:
            filedata = file.read().splitlines()
        search_str1 = "%s %s.*" % (self.host_ip, host_name)
        search_str2 = "%s %s.*" % (self.peer_ip, peer_name)
        add_str1 = "%s %s" % (self.host_ip, host_name)
        add_str2 = "%s %s" % (self.peer_ip, peer_name)

        for index, line in enumerate(filedata):
            filedata[index] = line.replace('\t', ' ')

        filedata = "\n".join(filedata)
        obj = re.search(search_str1, filedata)
        if not obj:
            filedata = "%s\n%s" % (add_str1, filedata)

        obj = re.search(search_str2, filedata)
        if not obj:
            filedata = "%s\n%s" % (add_str2, filedata)

        with open(hosts_file, 'w') as file:
            for line in filedata:
                file.write(line)

        filedata = self.run_command("cat %s" % hosts_file)[1:]

        for index, line in enumerate(filedata):
            filedata[index] = line.replace('\t', ' ')

        for line in filedata:
            obj = re.search(search_str1, line)
            if obj:
                break
        else:
            filedata.append(add_str1)

        for line in filedata:
            obj = re.search(search_str2, line)
            if obj:
                break
        else:
            filedata.append(add_str2)
        filedata = "\n".join(filedata)
        self.run_command("echo -e \'%s\' > %s" % (filedata, hosts_file))

    def generate_bpt_file(self):
        """
        Generates bpt file in both Host & Peer
        """
        self.log.info("Generating bpt file in both Host & Peer")
        cmd = "/usr/bin/build_net help n"
        self.run_command(cmd)
        exit_code = process.run(cmd, shell=True, sudo=True, ignore_status=True).exit_status
        if exit_code == 0 or exit_code == 43:
            return True
        else:
            self.fail("Command %s failed with exit status %s " % (cmd, exit_code))

    def check_bpt_file_existence(self):
        """
        Verifies the bpt file existence in both Host & Peer
        """
        self.bpt_file = '/usr/lpp/htx/bpt'
        cmd = "ls %s" % self.bpt_file
        res = self.run_command(cmd)
        if "No such file or directory" in "\n".join(res):
            self.fail("bpt file not generated in peer lpar")
        try:
            process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            msg = "Command %s failed %s, bpt file %s doesn't \
                  exist in host" % (cmd, details, self.bpt_file)
            self.fail(msg)

    def update_otherids_in_bpt(self):
        """
        Update host ip in peer bpt file & peer ip in host bpt file
        """
        # Update other id's in host lpar
        with open(self.bpt_file, 'r') as file:
            filedata = file.read()
        search_str1 = "other_ids=%s:" % self.host_ip
        replace_str1 = "%s%s" % (search_str1, self.peer_ip)

        filedata = re.sub(search_str1, replace_str1, filedata)
        with open(self.bpt_file, 'w') as file:
            for line in filedata:
                file.write(line)

        # Update other id's in peer lpar
        search_str2 = "other_ids=%s:" % self.peer_ip
        replace_str2 = "%s%s" % (search_str2, self.host_ip)
        filedata = self.run_command("cat %s" % self.bpt_file)
        for line in filedata:
            obj = re.search(search_str2, line)
            if obj:
                idx = filedata.index(line)
                filedata[idx] = replace_str2
                break
        else:
            self.fail("Failed to get other_ids string in peer lpar")
        filedata = "\n".join(filedata)
        self.run_command("echo \'%s\' > %s" % (filedata, self.bpt_file))

    def update_net_ids_in_bpt(self):
        """
        Update net id's in both Host & Peer bpt file for both N/W interfaces
        """
        # Update net id in host lpar
        with open(self.bpt_file, 'r') as file:
            filedata = file.read()
        for (host_intf, net_id) in zip(self.host_intfs, self.net_ids):
            search_str = "%s n" % host_intf
            replace_str = "%s %s" % (host_intf, net_id)
            filedata = re.sub(search_str, replace_str, filedata)
        with open(self.bpt_file, 'w') as file:
            for line in filedata:
                file.write(line)

        # Update net id in peer lpar
        filedata = self.run_command("cat %s" % self.bpt_file)

        for (peer_intf, net_id) in zip(self.peer_intfs, self.net_ids):
            search_str = "%s n" % peer_intf
            replace_str = "%s %s" % (peer_intf, net_id)

            for line in filedata:
                obj = re.search(search_str, line)
                if obj:
                    string = re.sub(search_str, replace_str, line)
                    idx = filedata.index(line)
                    filedata[idx] = string
                    break
            else:
                self.fail("Failed to get %s net_id in peer bpt" % peer_intf)

        filedata = "\n".join(filedata)
        self.run_command("echo \'%s\' > %s" % (filedata, self.bpt_file))

    def ip_config(self):
        """
        configuring ip for host and peer interfaces
        """
        for (host_intf, net_id) in zip(self.host_intfs, self.net_ids):
            ip_addr = "%s.1.1.%s" % (net_id, self.host_ip.split('.')[-1])
            networkinterface = NetworkInterface(host_intf, self.localhost)
            try:
                networkinterface.add_ipaddr(ip_addr, self.netmask)
                networkinterface.save(ip_addr, self.netmask)
            except Exception:
                networkinterface.save(ip_addr, self.netmask)
            networkinterface.bring_up()
        for (peer_intf, net_id) in zip(self.peer_intfs, self.net_ids):
            ip_addr = "%s.1.1.%s" % (net_id, self.peer_ip.split('.')[-1])
            peer_networkinterface = NetworkInterface(peer_intf, self.remotehost)
            peer_networkinterface.add_ipaddr(ip_addr, self.netmask)
            peer_networkinterface.bring_up()

    def htx_configure_net(self):
        self.log.info("Starting the N/W ping test for HTX in Host")
        cmd = "build_net %s" % self.bpt_file
        output = process.system_output(cmd, ignore_status=True, shell=True,
                                       sudo=True)
        # Try up to 10 times until pingum test passes
        for count in range(11):
            if count == 0:
                try:
                    output_peer = self.run_command(cmd, timeout=300)
                except CommandFailed as cf:
                    output_peer = cf.output
                    self.log.debug("Command %s failed %s", cf.command,
                                   cf.output)
            if "All networks ping Ok" not in output.decode("utf-8"):
                if self.peer_distro == "rhel":
                    self.run_command("systemctl start NetworkManager", timeout=300)
                else:
                    self.run_command("systemctl restart network", timeout=300)
                if self.host_distro == "rhel":
                    process.system("systemctl start NetworkManager", shell=True,
                                   ignore_status=True)
                else:
                    process.system("systemctl restart network", shell=True,
                                   ignore_status=True)
                output = process.system_output("pingum", ignore_status=True,
                                               shell=True, sudo=True)
            else:
                break
            time.sleep(30)
        else:
            self.log.info("manually configuring ip because of pingum failed.")
            self.ip_config()

        self.log.info("Starting the N/W ping test for HTX in Peer")
        for count in range(11):
            if "All networks ping Ok" not in "\n".join(output_peer):
                try:
                    output_peer = self.run_command("pingum", timeout=300)
                except CommandFailed as cf:
                    output_peer = cf.output
                self.log.info("\n".join(output_peer))
            else:
                break
            time.sleep(30)
        else:
            self.fail("N/W ping test for HTX failed in Peer(pingum)")
        self.log.info("N/W ping test for HTX passed in both Host & Peer")

    def run_htx(self):
        self.start_htx_deamon()
        self.shutdown_active_mdt()
        self.select_net_mdt()
        self.query_net_devices_in_mdt()
        self.suspend_all_net_devices()
        self.activate_mdt()
        self.is_net_devices_active()
        self.start_htx_run()

    def start_htx_deamon(self):
        cmd = '/usr/lpp/htx/etc/scripts/htxd_run'
        self.log.info("Starting the HTX Deamon in Host")
        process.run(cmd, shell=True, sudo=True)

        self.log.info("Starting the HTX Deamon in Peer")
        self.run_command(cmd)

    def select_net_mdt(self):
        self.log.info("Selecting the htx %s file in Host", self.mdt_file)
        cmd = "htxcmdline -select -mdt %s" % self.mdt_file
        process.run(cmd, shell=True, sudo=True)

        self.log.info("Selecting the htx %s file in Peer", self.mdt_file)
        self.run_command(cmd)

    def query_net_devices_in_mdt(self):
        self.is_net_devices_in_host_mdt()
        self.is_net_devices_in_peer_mdt()

    def is_net_devices_in_host_mdt(self):
        '''
        verifies the presence of given net devices in selected mdt file
        '''
        self.log.info("Checking host_interfaces presence in %s",
                      self.mdt_file)
        output = process.system_output(self.query_cmd, shell=True,
                                       sudo=True).decode("utf-8")
        absent_devices = []
        for intf in self.host_intfs:
            if intf not in output:
                absent_devices.append(intf)
        if absent_devices:
            self.log.info("net_devices %s are not avalable in host %s ",
                          absent_devices, self.mdt_file)
            self.fail("HTX fails to list host n/w interfaces")

        self.log.info("Given host net interfaces %s are available in %s",
                      self.host_intfs, self.mdt_file)

    def is_net_devices_in_peer_mdt(self):
        '''
        verifies the presence of given net devices in selected mdt file
        '''
        self.log.info("Checking peer_interfaces presence in %s",
                      self.mdt_file)
        output = self.run_command(self.query_cmd)
        output = " ".join(output)
        absent_devices = []
        for intf in self.peer_intfs:
            if intf not in output:
                absent_devices.append(intf)
        if absent_devices:
            self.log.info("net_devices %s are not avalable in peer %s ",
                          absent_devices, self.mdt_file)
            self.fail("HTX fails to list peer n/w interfaces")

        self.log.info("Given peer net interfaces %s are available in %s",
                      self.peer_intfs, self.mdt_file)

    def activate_mdt(self):
        self.log.info("Activating the N/W devices with mdt %s in Host",
                      self.mdt_file)
        cmd = "htxcmdline -activate all -mdt %s" % self.mdt_file
        try:
            process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            self.log.debug("Activation of N/W devices (%s) failed in Host",
                           self.mdt_file)
            self.fail("Command %s failed %s" % (cmd, details))

        self.log.info("Activating the N/W devices with mdt %s in Peer",
                      self.mdt_file)
        try:
            self.run_command(cmd)
        except CommandFailed as cf:
            self.log.debug("Activation of N/W devices (%s) failed in Peer",
                           self.mdt_file)
            self.fail("Command %s failed %s" % (cmd, str(cf)))

    def is_net_devices_active(self):
        if not self.is_net_device_active_in_host():
            self.fail("Net devices are failed to activate in Host \
                      after HTX activate")
        if not self.is_net_device_active_in_peer():
            self.fail("Net devices are failed to activate in Peer \
                      after HTX activate")

    def start_htx_run(self):
        self.log.info("Running the HTX for %s on Host", self.mdt_file)
        cmd = "htxcmdline -run -mdt %s" % self.mdt_file
        process.run(cmd, shell=True, sudo=True)

        self.log.info("Running the HTX for %s on Peer", self.mdt_file)
        self.run_command(cmd)

    def monitor_htx_run(self):
        for time_loop in range(0, self.time_limit, 60):
            self.log.info("Monitoring HTX Error logs in Host")
            cmd = 'htxcmdline -geterrlog'
            process.run(cmd, ignore_status=True,
                        shell=True, sudo=True)
            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("Their are errors while htx run in host")
            self.log.info("Monitoring HTX Error logs in Peer")
            self.run_command(cmd)
            try:
                self.run_command('test -s /tmp/htxerr')
                rc = True
            except CommandFailed as cf:
                rc = False
            if rc:
                output = self.run_command("cat /tmp/htxerr")
                self.log.debug("HTX error log in peer: %s\n",
                               "\n".join(output))
                self.fail("Their are errors while htx run in peer")
            self.log.info("Status of N/W devices after every 60 sec")
            process.system(self.query_cmd, ignore_status=True,
                           shell=True, sudo=True)
            try:
                output = self.run_command(self.query_cmd)
            except CommandFailed as cf:
                output = cf.output
                pass
            self.log.info("query o/p in peer lpar\n %s", "\n".join(output))
            time.sleep(60)

    def shutdown_active_mdt(self):
        self.log.info("Shutdown active mdt in host")
        cmd = "htxcmdline -shutdown"
        process.run(cmd, timeout=120, ignore_status=True, shell=True, sudo=True)
        self.log.info("Shutdown active mdt in peer")
        try:
            self.run_command(cmd)
        except CommandFailed:
            pass

    def suspend_all_net_devices(self):
        self.suspend_all_net_devices_in_host()
        self.suspend_all_net_devices_in_peer()

    def suspend_all_net_devices_in_host(self):
        '''
        Suspend the Net devices, if active.
        '''
        self.log.info("Suspending net_devices in host if any running")
        self.susp_cmd = "htxcmdline -suspend all  -mdt %s" % self.mdt_file
        process.run(self.susp_cmd, ignore_status=True, shell=True, sudo=True)

    def suspend_all_net_devices_in_peer(self):
        '''
        Suspend the Net devices, if active.
        '''
        self.log.info("Suspending net_devices in peer if any running")
        try:
            self.run_command(self.susp_cmd)
        except CommandFailed:
            pass

    def is_net_device_active_in_host(self):
        '''
        Verifies whether the net devices are active or not in host
        '''
        self.log.info("Checking whether all net_devices are active or \
                      not in host ")
        output = process.system_output(self.query_cmd, ignore_status=True,
                                       shell=True,
                                       sudo=True).decode("utf-8").split('\n')
        active_devices = []
        for line in output:
            for intf in self.host_intfs:
                if intf in line and 'ACTIVE' in line:
                    active_devices.append(intf)
        non_active_device = list(set(self.host_intfs) - set(active_devices))
        if non_active_device:
            return False
        else:
            self.log.info("Active N/W devices in Host %s", active_devices)
            return True

    def is_net_device_active_in_peer(self):
        '''
        Verifies whether the net devices are active or not in peer
        '''
        self.log.info("Checking whether all net_devices are active or \
                      not in peer")
        try:
            output = self.run_command(self.query_cmd)
        except CommandFailed as cf:
            output = cf.output
        active_devices = []
        for line in output:
            for intf in self.peer_intfs:
                if intf in line and 'ACTIVE' in line:
                    active_devices.append(intf)
        non_active_device = list(set(self.peer_intfs) - set(active_devices))
        if non_active_device:
            return False
        else:
            self.log.info("Active N/W devices in Peer %s", active_devices)
            return True

    def shutdown_htx_daemon(self):
        status_cmd = '/etc/init.d/htx.d status'
        shutdown_cmd = '/usr/lpp/htx/etc/scripts/htxd_shutdown'
        daemon_state = process.system_output(status_cmd, ignore_status=True,
                                             shell=True,
                                             sudo=True).decode("utf-8")
        if daemon_state.split(" ")[-1] == 'running':
            process.system(shutdown_cmd, ignore_status=True,
                           shell=True, sudo=True)
        try:
            output = self.run_command(status_cmd)
        except CommandFailed as cf:
            output = cf.output
        if 'running' in output[0]:
            try:
                self.run_command(shutdown_cmd)
            except CommandFailed:
                pass

    def clean_state(self):
        '''
        Reset bpt, suspend and shutdown the active mdt
        '''
        self.log.info("Resetting bpt file in both Host & Peer")
        cmd = "/usr/bin/build_net help n"
        self.run_command(cmd)
        exit_code = process.run(cmd, shell=True, sudo=True, ignore_status=True).exit_status
        if exit_code == 0 or exit_code == 43:
            return True
        else:
            self.fail("Command %s failed with exit status %s " % (cmd, exit_code))

        if self.is_net_device_active_in_host():
            self.suspend_all_net_devices_in_host()
            self.log.info("Shutting down the %s in host", self.mdt_file)
            cmd = 'htxcmdline -shutdown -mdt %s' % self.mdt_file
            process.system(cmd, timeout=120, ignore_status=True,
                           shell=True, sudo=True)
        if self.is_net_device_active_in_peer():
            self.suspend_all_net_devices_in_peer()
            self.log.info("Shutting down the %s in peer", self.mdt_file)
            try:
                self.run_command(cmd)
            except CommandFailed:
                pass

        self.run_command("rm -rf /tmp/HTX-master")

    def ip_restore_host(self):
        '''
        restoring ip for host
        '''
        for ipaddr, interface in zip(self.ipaddr, self.host_intfs):
            cmd = "ip addr flush %s" % interface
            process.run(cmd, ignore_status=True, shell=True, sudo=True)
            networkinterface = NetworkInterface(interface, self.localhost)
            networkinterface.add_ipaddr(ipaddr, self.netmask)
            networkinterface.save(ipaddr, self.netmask)
            networkinterface.bring_up()

    def ip_restore_peer(self):
        '''
        config ip for peer
        '''
        for ip, interface in zip(self.peer_ips, self.peer_intfs):
            if self.peer_distro in ['rhel', 'fedora']:
                path = "/etc/sysconfig/network-scripts"
                file_name = "{}/ifcfg-{}".format(path, interface)
                self.run_command("echo \'%s\' > %s" % ('TYPE=Ethernet', file_name))
                self.run_command("echo \'%s\' >> %s" % ('BOOTPROTO=none', file_name))
                self.run_command("echo \'%s\' >> %s" % ('NAME=%s' % interface, file_name))
                self.run_command("echo \'%s\' >> %s" % (('DEVICE=%s' % interface), file_name))
                self.run_command("echo \'%s\' >> %s" % ('ONBOOT=yes', file_name))
                self.run_command("echo \'%s\' >> %s" % ('IPADDR=%s' % ip, file_name))
                self.run_command("echo \'%s\' >> %s" % ('NETMASK=%s' % self.netmask, file_name))
                self.run_command("echo \'%s\' >> %s" % ('IPV6INIT=yes', file_name))
                self.run_command("echo \'%s\' >> %s" % ('IPV6_AUTOCONF=yes', file_name))
                self.run_command("echo \'%s\' >> %s" % ('IPV6_DEFROUTE=yes', file_name))
            if self.peer_distro == 'SuSE':
                path = "/etc/sysconfig/network"
                file_name = "{}/ifcfg-{}".format(path, interface)
                self.run_command("echo \'%s\' > %s" % ('IPADDR=%s' % ip, file_name))
                self.run_command("echo \'%s\' >> %s" % ('NETMASK=%s' % self.netmask, file_name))
                self.run_command("echo \'%s\' >> %s" % ('IPV6INIT=yes', file_name))
                self.run_command("echo \'%s\' >> %s" % ('IPV6_AUTOCONF=yes', file_name))
                self.run_command("echo \'%s\' >> %s" % ('IPV6_DEFROUTE=yes', file_name))
            cmd = "ifup %s " % interface
            self.run_command(cmd)

    def htx_cleanup(self):
        self.clean_state()
        self.shutdown_htx_daemon()
        self.ip_restore_host()
        self.ip_restore_peer()
        self.remotehost.remote_session.quit()

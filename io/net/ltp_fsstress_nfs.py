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
# Copyright: 2026 IBM
# Author: Vaishnavi Bhat <vaishnavi@linux.vnet.ibm.com>
#
# https://github.com/linux-test-project/ltp

"""
LTP fsstress test on NFS mounted filesystem
:avocado: tags=net,fs,privileged
"""

import os
import time
from avocado import Test
from avocado.utils import build
from avocado.utils import dmesg
from avocado.utils import process, archive
from avocado.utils import distro
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.network.interfaces import NetworkInterface


class LtpFsNfs(Test):
    '''
    Using LTP (Linux Test Project) fsstress to test NFS mounted filesystem
    '''

    def setUp(self):
        '''
        Setup network interfaces, NFS server on peer, and mount NFS on host
        '''
        self.err_mesg = []

        # Get test parameters
        self.host_interface = self.params.get('host_interface', default=None)
        self.host_ip = self.params.get('host_ip', default=None)
        self.peer_interface = self.params.get('peer_interface', default=None)
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.peer_public_ip = self.params.get('peer_public_ip',
                                              default=None)
        self.peer_user = self.params.get('peer_user', default='root')
        self.peer_password = self.params.get('peer_password', default=None)
        self.netmask = self.params.get('netmask', default='255.255.255.0')

        # NFS mount parameters
        self.nfs_mount_point = self.params.get('nfs_mount_point',
                                               default='/mnt/nfs')
        self.nfs_server_path = self.params.get('nfs_server_path',
                                               default='/mnt/nfssrc')

        # fsstress parameters
        self.fsstress_count = self.params.get('fsstress_loop', default='0')
        self.n_val = self.params.get('n_val', default='200')
        self.p_val = self.params.get('p_val', default='200')
        self.fsstress_timeout = self.params.get('fsstress_timeout',
                                                default='60')

        # Validate required parameters
        if not all([self.host_interface, self.host_ip, self.peer_ip,
                    self.peer_public_ip, self.peer_password]):
            self.cancel("Missing required parameters: host_interface, "
                        "host_ip, peer_ip, peer_public_ip, peer_password")

        # Initialize localhost
        self.localhost = LocalHost()

        # Check if host interface exists
        interfaces = os.listdir('/sys/class/net')
        if self.host_interface not in interfaces:
            self.cancel(
                f"Host interface {self.host_interface} not available")

        # Install required packages
        smm = SoftwareManager()
        detected_distro = distro.detect()
        packages = ['gcc', 'make', 'automake', 'autoconf', 'nfs-utils']

        if detected_distro.name == 'Ubuntu':
            packages.extend(['nfs-common', 'openssh-client',
                             'iputils-ping'])
        elif detected_distro.name in ['rhel', 'fedora', 'centos',
                                      'redhat']:
            packages.extend(['openssh-clients', 'iputils'])
        else:
            packages.extend(['openssh', 'iputils'])

        for package in packages:
            if (not smm.check_installed(package) and
                    not smm.install(package)):
                self.cancel(
                    f"{package} is needed for the test to be run")

        # Configure host interface
        self.log.info(f"Configuring host interface {self.host_interface} "
                      f"with IP {self.host_ip}")
        self.host_networkinterface = NetworkInterface(
            self.host_interface, self.localhost)
        try:
            self.host_networkinterface.add_ipaddr(self.host_ip,
                                                  self.netmask)
            self.host_networkinterface.bring_up()
        except Exception as e:
            self.log.info(f"Host interface configuration: {e}")

        # Establish SSH connection to peer using public IP
        self.log.info(f"Connecting to peer at {self.peer_public_ip}")
        self.session = Session(self.peer_public_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel("Failed to connect to peer machine")

        # Initialize remote host with peer private IP for network operations
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)

        # Get peer interface by IP or use specified interface
        peer_iface = None
        if self.peer_interface:
            peer_iface = self.peer_interface
        else:
            # Try to get interface by IP address
            try:
                peer_iface = self.remotehost.get_interface_by_ipaddr(
                    self.peer_ip).name
            except Exception:
                self.cancel("Could not determine peer interface. Please "
                            "specify peer_interface in YAML")

        # Configure peer interface with private IP
        if peer_iface:
            self.log.info(f"Configuring peer interface {peer_iface} "
                          f"with IP {self.peer_ip}")
            self.peer_networkinterface = NetworkInterface(
                peer_iface, self.remotehost)
        else:
            self.cancel("Peer interface not specified and could not be "
                        "determined")
        try:
            self.peer_networkinterface.add_ipaddr(self.peer_ip,
                                                  self.netmask)
            self.peer_networkinterface.bring_up()
        except Exception as e:
            self.log.info(f"Peer interface configuration: {e}")

        # Ping check using Avocado utility
        self.log.info(f"Performing ping check to {self.peer_ip}")
        if (self.host_networkinterface.ping_check(self.peer_ip, count=5)
                is not None):
            self.cancel(f"No connection to peer {self.peer_ip}")

        # Setup NFS server on peer
        self.setup_nfs_server()

        # Mount NFS on host
        self.mount_nfs()

        # Download and build LTP fsstress only
        self.log.info("Downloading LTP and building fsstress")
        url = "https://github.com/linux-test-project/ltp/archive/master.zip"
        tarball = self.fetch_asset("ltp-master.zip", locations=[url],
                                   expire='7d')
        archive.extract(tarball, self.teststmpdir)
        ltp_dir = os.path.join(self.teststmpdir, "ltp-master")
        os.chdir(ltp_dir)

        # Configure LTP (required for config.mk)
        self.log.info("Configuring LTP")
        build.make(ltp_dir, extra_args='autotools')
        process.system('./configure', ignore_status=True)

        # Build only fsstress instead of entire LTP suite
        self.log.info("Building fsstress (faster than full LTP build)")
        fsstress_build_cmd = "make -C testcases/kernel/fs/fsstress"
        if (process.system(fsstress_build_cmd, shell=True,
                           ignore_status=True) != 0):
            self.cancel("Failed to build fsstress")

        self.fsstress_dir = os.path.join(
            ltp_dir, 'testcases/kernel/fs/fsstress')
        os.chdir(self.fsstress_dir)

        # Clear dmesg
        dmesg.clear_dmesg()

    def setup_nfs_server(self):
        """
        Setup NFS server on peer machine:
        - Create NFS export directory
        - Start NFS server
        - Stop firewalld
        - Export the directory
        """
        self.log.info("Setting up NFS server on peer")

        # Create NFS export directory on peer
        cmd = f"mkdir -p {self.nfs_server_path}"
        result = self.session.cmd(cmd)
        if result.exit_status != 0:
            self.cancel("Failed to create NFS export directory on peer: "
                        f"{result.stderr}")

        # Install NFS server packages on peer
        detected_distro = distro.detect()
        if detected_distro.name == 'Ubuntu':
            nfs_pkg_cmd = ("apt-get update && apt-get install -y "
                           "nfs-kernel-server")
        else:
            nfs_pkg_cmd = "yum install -y nfs-utils"

        result = self.session.cmd(nfs_pkg_cmd)
        if result.exit_status != 0:
            self.log.warning("NFS package installation on peer: "
                             f"{result.stderr}")

        # Start NFS server on peer
        self.log.info("Starting NFS server on peer")
        start_nfs_cmds = [
            "systemctl start nfs-server",
            "systemctl enable nfs-server",
            "systemctl start rpcbind",
            "systemctl enable rpcbind"
        ]
        for cmd in start_nfs_cmds:
            result = self.session.cmd(cmd)
            if result.exit_status != 0:
                self.log.warning(f"Command '{cmd}' on peer: "
                                 f"{result.stderr}")

        # Stop firewalld on peer
        self.log.info("Stopping firewalld on peer")
        firewall_cmds = [
            "systemctl stop firewalld",
            "systemctl disable firewalld"
        ]
        for cmd in firewall_cmds:
            result = self.session.cmd(cmd)
            # Ignore errors as firewalld might not be running

        # Export the directory on peer
        self.log.info(f"Exporting {self.nfs_server_path} to "
                      f"{self.host_ip}")
        export_cmd = (f"exportfs -o rw,sync,no_root_squash "
                      f"{self.host_ip}:{self.nfs_server_path}")
        result = self.session.cmd(export_cmd)
        if result.exit_status != 0:
            self.cancel("Failed to export NFS directory on peer: "
                        f"{result.stderr}")

        # Verify export
        result = self.session.cmd("exportfs -v")
        self.log.info(f"NFS exports on peer:\n{result.stdout}")

    def mount_nfs(self):
        """
        Mount NFS filesystem on host
        """
        self.log.info(f"Mounting NFS from {self.peer_ip}:"
                      f"{self.nfs_server_path} to {self.nfs_mount_point}")

        # Create mount point on host
        cmd = f"mkdir -p {self.nfs_mount_point}"
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.cancel(
                f"Failed to create mount point {self.nfs_mount_point}")

        # Mount NFS
        mount_cmd = (f"mount -t nfs {self.peer_ip}:{self.nfs_server_path} "
                     f"{self.nfs_mount_point}")
        if process.system(mount_cmd, shell=True, ignore_status=True) != 0:
            self.cancel(f"Failed to mount NFS from {self.peer_ip}:"
                        f"{self.nfs_server_path}")

        # Verify mount
        verify_cmd = f"mount | grep {self.nfs_mount_point}"
        result = process.system_output(verify_cmd, shell=True,
                                       ignore_status=True)
        self.log.info(f"NFS mount verification:\n"
                      f"{result.decode('utf-8')}")

        # Test write access
        test_file = os.path.join(self.nfs_mount_point, 'test_write')
        cmd = f"touch {test_file} && rm -f {test_file}"
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.cancel(
                f"NFS mount {self.nfs_mount_point} is not writable")

        self.log.info("NFS mount successful and writable")

    def test_fsstress_run(self):
        '''
        Run LTP fsstress test on NFS mounted filesystem
        '''
        self.log.info("Starting fsstress test on NFS mount")
        self.log.info(f"Using fsstress timeout: "
                      f"{self.fsstress_timeout} seconds")
        self.log.info(f"fsstress parameters - loops: "
                      f"{self.fsstress_count}, operations: {self.n_val}, "
                      f"processes: {self.p_val}")

        # Clear dmesg before test
        dmesg.clear_dmesg()

        # Run fsstress with timeout command using YAML parameters
        cmd = (f"timeout {self.fsstress_timeout} ./fsstress "
               f"-d {self.nfs_mount_point} -p {self.p_val} "
               f"-n {self.n_val} -l {self.fsstress_count}")
        self.log.info(f"Running command: {cmd}")

        # Run fsstress with timeout
        result = process.run(cmd, shell=True, ignore_status=True)

        # Check exit status
        # timeout command returns 124 if the process was killed by timeout
        # 0 if the process completed normally
        if result.exit_status == 124:
            self.log.info(f"fsstress ran for {self.fsstress_timeout} "
                          f"seconds and was terminated by timeout "
                          f"(expected)")
        elif result.exit_status == 0:
            self.log.info("fsstress completed before timeout")
        else:
            self.log.warning(f"fsstress exited with status "
                             f"{result.exit_status}")

        # Wait a moment for any cleanup
        time.sleep(2)

        # Verify no fsstress processes are still running
        check_cmd = "pgrep -f fsstress"
        result = process.system(check_cmd, shell=True, ignore_status=True)
        if result == 0:
            self.log.info("fsstress processes still running, "
                          "cleaning up")
            kill_cmd = "pkill fsstress"
            process.system(kill_cmd, shell=True, ignore_status=True)
        else:
            self.log.info("All fsstress processes terminated "
                          "successfully")

        # Check dmesg for errors
        self.log.info("Checking dmesg for errors")
        cmd = "dmesg --level=err,crit,alert,emerg"
        dmesg_output = process.system_output(cmd, shell=True,
                                             ignore_status=True,
                                             sudo=False)
        if dmesg_output:
            dmesg_str = dmesg_output.decode('utf-8')
            if 'nfs' in dmesg_str.lower() or 'rpc' in dmesg_str.lower():
                self.log.warning("NFS-related errors found in dmesg during "
                                 "fsstress test")
            self.fail(f"Errors found in dmesg:\n{dmesg_str}")
        else:
            self.log.info("No errors found in dmesg")

        # Check console logs if available
        console_log = "/var/log/messages"
        if os.path.exists(console_log):
            self.log.info("Checking console logs for NFS errors")
            grep_cmd = f"grep -i 'nfs\\|rpc' {console_log} | tail -50"
            console_output = process.system_output(grep_cmd, shell=True,
                                                   ignore_status=True)
            if console_output:
                self.log.info("Recent NFS/RPC messages in console:\n"
                              f"{console_output.decode('utf-8')}")

    def tearDown(self):
        '''
        Cleanup: unmount NFS, stop NFS server on peer, cleanup network
        configuration
        '''
        self.log.info("Starting cleanup")

        # Kill any remaining fsstress processes
        kill_cmd = "pkill fsstress"
        process.system(kill_cmd, shell=True, ignore_status=True)

        # Unmount NFS on host
        self.log.info(f"Unmounting NFS from {self.nfs_mount_point}")
        umount_cmd = f"umount -f {self.nfs_mount_point}"
        if (process.system(umount_cmd, shell=True, ignore_status=True)
                != 0):
            self.log.warning(f"Failed to unmount {self.nfs_mount_point}")
            self.err_mesg.append(
                f"Failed to unmount {self.nfs_mount_point}")
            # Try lazy unmount
            lazy_umount = f"umount -l {self.nfs_mount_point}"
            process.system(lazy_umount, shell=True, ignore_status=True)

        # Remove mount point
        rm_cmd = f"rmdir {self.nfs_mount_point}"
        process.system(rm_cmd, shell=True, ignore_status=True)

        # Cleanup NFS server on peer
        if hasattr(self, 'session') and self.session:
            self.log.info("Cleaning up NFS server on peer")

            # Unexport the directory
            unexport_cmd = (f"exportfs -u "
                            f"{self.host_ip}:{self.nfs_server_path}")
            result = self.session.cmd(unexport_cmd)
            if result.exit_status != 0:
                self.log.warning("Failed to unexport NFS directory: "
                                 f"{result.stderr}")

            # Remove NFS export directory
            rm_nfs_dir = f"rm -rf {self.nfs_server_path}"
            self.session.cmd(rm_nfs_dir)

            # Close SSH session
            self.session.quit()

        # Close RemoteHost sessions
        if hasattr(self, 'remotehost') and self.remotehost:
            try:
                self.remotehost.remote_session.quit()
            except Exception as e:
                self.log.debug(f"Error closing remotehost session: {e}")

        # Clear dmesg
        dmesg.clear_dmesg()

        # Report any errors
        if self.err_mesg:
            self.log.warning(
                f"Test completed with errors: {self.err_mesg}")

# Made with AI Support

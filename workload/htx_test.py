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
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#         Naresh Bannoth <nbannoth@in.ibm.com>
#         Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>
#         Vaishnavi Bhat <vaishnavi@linux.vnet.ibm.com>
#

"""
HTX Test

Stress-tests IBM Power hardware using the HTX (Hardware Test eXecutive)
framework.  Supports generic MDT-based runs (CPU, memory, pmem, isst) as
well as targeted IO device stress via the respective YAML parameters.
Also supports NIC device stress across a host/peer LPAR pair via the
test_htx_nic_start / test_htx_nic_check / test_htx_nic_stop test methods.

"""

import os
import re
import shutil
import ssl
import time
import urllib.request

from avocado import Test
from avocado.utils import disk
from avocado.utils import distro
from avocado.utils import multipath
from avocado.utils import process
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.software_manager.backends.rpm import RpmBackend
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session

HTX_INSTALL_PATH = '/usr/lpp/htx'


class HtxTest(Test):
    """
    HTX [Hardware Test eXecutive] is a test tool suite.  The goal of HTX is
    to stress test the system by exercising all hardware components
    concurrently in order to uncover any hardware design flaws and
    hardware-hardware or hardware-software interaction issues.

    :see: https://github.com/open-power/HTX.git
    """

    def setUp(self):
        """
        Setup
        """
        self.detected_distro = distro.detect()
        if 'ppc64' not in self.detected_distro.arch:
            self.cancel("Supported only on Power Architecture")

        self.mdt_file = self.params.get('mdt_file', default='mdt.mem')
        self.htx_disks = self.params.get('htx_disks', default=None)

        _time_limit = self.params.get('time_limit', default=None)
        if _time_limit is not None:
            _unit = self.params.get('time_unit', default='m')
            _multiplier = 3600 if str(_unit).strip().lower() == 'h' else 60
            self.time_limit = int(_time_limit) * _multiplier
        else:
            self.time_limit = int(self.params.get('time_interval', default=2)) * 60
        self.run_all = self.params.get('all', default=False)
        self.rpm_link = self.params.get('htx_rpm_link', default=None)
        self.dist_name = None

        self.block_device = ''
        if self.htx_disks and not self.run_all:
            self.block_device = self._resolve_block_devices(self.htx_disks)

        if 'nic' in str(self.name.name):
            # net.mdt is created by build_net multisystem inside
            # test_htx_nic_start — it cannot exist before the test runs.
            # Skip the generic MDT check and setup_htx() entirely.
            self._nic_setup()
            return

        if str(self.name.name).endswith('test_start'):
            self.setup_htx()

        if not os.path.exists(f'{HTX_INSTALL_PATH}/mdt/{self.mdt_file}'):
            self.cancel(f"MDT file {self.mdt_file} not found")

    @staticmethod
    def _resolve_block_devices(raw_devices):
        """
        Resolve raw device names or paths to bare basenames for htxcmdline.
        DM multipath devices are mapped to their ``mpathX`` name.

        :param raw_devices: Whitespace-separated device names or paths.
        :returns: Space-separated string of resolved device basenames.
        :rtype: str
        """
        resolved = []
        for dev in raw_devices.split():
            dev_path = disk.get_absolute_disk_path(dev)
            dev_base = os.path.basename(os.path.realpath(dev_path))
            if 'dm' in dev_base:
                dev_base = multipath.get_mpath_from_dm(dev_base)
            resolved.append(dev_base)
        return ' '.join(resolved)

    def install_latest_htx_rpm(self):
        """
        Search for the latest htx-version for the intended distro and
        install the same.
        """
        if self.rpm_link.endswith('.rpm'):
            latest_htx_rpm = os.path.basename(self.rpm_link)
            cmd = f'curl -kL {self.rpm_link} -o /tmp/{latest_htx_rpm}'
        else:
            distro_pattern = f'{self.dist_name}{self.detected_distro.version}'
            temp_string = process.getoutput(
                f'curl --silent -kL {self.rpm_link}',
                verbose=False, shell=True, ignore_status=True)
            matching_htx_versions = re.findall(
                r'(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*', str(temp_string))
            distro_specific_htx_versions = [
                r for r in matching_htx_versions if distro_pattern in r]
            distro_specific_htx_versions.sort(reverse=True)
            if not distro_specific_htx_versions:
                self.cancel(
                    f"No HTX RPM found for {distro_pattern}"
                    f" at {self.rpm_link}")
            latest_htx_rpm = distro_specific_htx_versions[0]
            cmd = (f'curl -kL {self.rpm_link}/{latest_htx_rpm}'
                   f' -o /tmp/{latest_htx_rpm}')

        if process.system(cmd, shell=True, ignore_status=True):
            self.cancel(f"RPM download failed: {latest_htx_rpm}")

        tmp_rpm = f'/tmp/{latest_htx_rpm}'

        if process.system(
                f'rpm -ivh --nodeps --force {tmp_rpm}',
                shell=True, ignore_status=True):
            self.cancel(f"RPM installation failed: {tmp_rpm}")

        self.log.info("HTX RPM %s installed successfully", latest_htx_rpm)
        process.run(f'rm -rf {tmp_rpm}', ignore_status=True)

    def _get_distro_packages(self):
        """
        Return the list of distro-specific packages required to build HTX.

        :returns: List of package name strings.
        :rtype: list
        :raises: Cancels the test if the distro is unsupported.
        """
        packages = ['gcc', 'make', 'ndctl']
        name = self.detected_distro.name
        if name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif name == 'Ubuntu':
            packages.extend(['libncurses5', 'g++',
                             'ncurses-dev', 'libncurses-dev', 'tar'])
        elif name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            self.cancel(f"Test not supported in {name}")
        return packages

    def _install_htx_rpm_if_needed(self, smm):
        """
        Install the HTX RPM if the correct version is not already present.
        Removes any mismatched existing installation first.

        :param smm: SoftwareManager instance used for RPM checks.
        """
        rpm_check = f'htx{self.dist_name}{self.detected_distro.version}'
        ins_htx = process.system_output(
            'rpm -qa | grep htx', shell=True,
            ignore_status=True).decode().strip()

        if ins_htx:
            if smm.check_installed(rpm_check):
                self.log.info("Using existing HTX RPM: %s", rpm_check)
                return
            self.log.info("Clearing existing HTX RPM: %s", ins_htx)
            process.system(f'rpm -e {ins_htx}',
                           shell=True, ignore_status=True)
            if os.path.exists(HTX_INSTALL_PATH):
                shutil.rmtree(HTX_INSTALL_PATH)

        self.rpm_link = self.params.get('htx_rpm_link', default=None)
        if self.rpm_link:
            self.install_latest_htx_rpm()
        else:
            self.cancel("htx_rpm_link is required for RPM install")

    def setup_htx(self):
        """
        Builds HTX
        """
        smm = SoftwareManager()
        for pkg in self._get_distro_packages():
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(f"Cannot install {pkg}")

        self.dist_name = self.detected_distro.name.lower()
        if self.dist_name == 'suse':
            self.dist_name = 'sles'
        self._install_htx_rpm_if_needed(smm)

        self.log.info("Stopping any existing HXE exerciser process")
        hxe_pid = process.getoutput('pgrep -f hxe', ignore_status=True)
        if hxe_pid.strip():
            self.log.info("HXE running with PID %s; shutting down",
                          hxe_pid.strip())
            process.run('hcl -shutdown', ignore_status=True)
            time.sleep(20)

        self._ensure_daemon_running()

        self.log.info("Creating HTX MDT files")
        process.run('htxcmdline -createmdt', ignore_status=True)
        mdt_path = f'{HTX_INSTALL_PATH}/mdt/{self.mdt_file}'
        if not os.path.exists(mdt_path):
            self.log.info("MDT %s not found; retrying named creation",
                          self.mdt_file)
            process.run(f'htxcmdline -createmdt -mdt {self.mdt_file}',
                        ignore_status=True)
            if not os.path.exists(mdt_path):
                self.cancel(f"MDT file {self.mdt_file} could not be created")

    def _get_daemon_state(self):
        """
        Query and return the current HTX daemon status string.
        """
        return process.system_output(
            f'{HTX_INSTALL_PATH}/etc/scripts/htx.d status',
            ignore_status=True).decode('utf-8').strip()

    def _ensure_daemon_running(self):
        """
        Start the HTX daemon only if it is not already running.
        """
        self.log.info("Checking HTX daemon state")
        if self._get_daemon_state().split()[-1:] != ['running']:
            self.log.info("HTXD is not running; starting it")
            process.run(f'{HTX_INSTALL_PATH}/etc/scripts/htxd_run',
                        ignore_status=True)
            time.sleep(5)
        else:
            self.log.info("HTXD is already running")

    def _stop_daemon(self):
        """
        Shut down the HTX daemon if it is currently running.
        """
        if self._get_daemon_state().split()[-1:] == ['running']:
            self.log.info("Shutting down HTX daemon")
            process.system(
                f'{HTX_INSTALL_PATH}/etc/scripts/htxd_shutdown',
                ignore_status=True)

    def is_block_device_in_mdt(self, block_device=None, mdt_file=None):
        """
        Return True if all specified block devices appear in the MDT.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file
        self.log.info("Checking block devices in MDT %s", mdt_file)
        output = process.system_output(
            f'htxcmdline -query -mdt {mdt_file}',
            ignore_status=True).decode('utf-8')
        missing = [dev for dev in block_device.split() if dev not in output]
        if missing:
            self.log.info("Devices not in MDT %s: %s", mdt_file, missing)
            return False
        self.log.info("All block devices present in MDT %s", mdt_file)
        return True

    def suspend_all_block_device(self, mdt_file=None):
        """
        Suspend all block devices in the MDT.
        """
        if mdt_file is None:
            mdt_file = self.mdt_file
        self.log.info("Suspending all block devices in MDT %s", mdt_file)
        process.system(f'htxcmdline -suspend all -mdt {mdt_file}',
                       ignore_status=True)

    def is_block_device_active(self, block_device=None, mdt_file=None):
        """
        Return True if all specified block devices show ACTIVE.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file
        self.log.info("Checking ACTIVE state for: %s", block_device)
        output = process.system_output(
            f'htxcmdline -query {block_device} -mdt {mdt_file}',
            ignore_status=True).decode('utf-8').split('\n')
        device_list = block_device.split()
        active_devices = [
            dev for line in output for dev in device_list
            if dev in line and 'ACTIVE' in line
        ]
        non_active = list(set(device_list) - set(active_devices))
        if non_active:
            self.log.info("Devices not ACTIVE: %s", non_active)
            return False
        self.log.info("All block devices ACTIVE: %s", block_device)
        return True

    def test_start(self):
        """
        Execute HTX with appropriate parameters.
        """
        self.log.info("Selecting MDT file: %s", self.mdt_file)
        process.system(f'htxcmdline -select -mdt {self.mdt_file}',
                       ignore_status=True)

        if self.htx_disks or self.run_all:
            if not self.run_all:
                if not self.is_block_device_in_mdt():
                    self.fail(
                        f"Block devices {self.block_device} not found"
                        f" in MDT {self.mdt_file}")

            self.suspend_all_block_device()

            self.log.info("Activating block device(s): %s", self.block_device)
            process.system(
                f'htxcmdline -activate {self.block_device}'
                f' -mdt {self.mdt_file}',
                ignore_status=True)

            if not self.run_all:
                if not self.is_block_device_active():
                    self.fail(
                        f"Block devices {self.block_device}"
                        f" failed to reach ACTIVE state")
        else:
            self.log.info("Activating MDT: %s", self.mdt_file)
            process.system(f'htxcmdline -activate -mdt {self.mdt_file}',
                           ignore_status=True)

        self.log.info("Configuring HTX_DR_TEST environment variable")
        process.system('hcl -get_htx_env HTX_DR_TEST', ignore_status=True)
        process.system('hcl -set_htx_env HTX_DR_TEST 1', ignore_status=True)
        process.system('hcl -get_htx_env HTX_DR_TEST', ignore_status=True)

        self.log.info("Starting HTX run on MDT: %s", self.mdt_file)
        process.system(f'htxcmdline -run -mdt {self.mdt_file}',
                       ignore_status=True)

    def test_check(self):
        """
        Checks if HTX is running, and if no errors.
        """
        for _ in range(0, self.time_limit, 60):
            self.log.info("Checking HTX error log")
            process.system('htxcmdline -geterrlog', ignore_status=True)
            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("HTX errors detected; check /tmp/htxerr")

            if self.htx_disks or self.run_all:
                cmd = (f'htxcmdline -query {self.block_device}'
                       f' -mdt {self.mdt_file}')
            else:
                cmd = f'htxcmdline -query -mdt {self.mdt_file}'
            process.system(cmd, ignore_status=True)
            time.sleep(60)

    def test_stop(self):
        """
        Shutdown the MDT and the HTX daemon.
        """
        self.stop_htx()

    def stop_htx(self):
        """
        Stop the HTX Run
        """
        self.suspend_all_block_device()

        self.log.info("Shutting down MDT: %s", self.mdt_file)
        process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                       timeout=120, ignore_status=True)

        process.system('umount /htx_pmem*', shell=True, ignore_status=True)

        self._stop_daemon()

    # ------------------------------------------------------------------
    # NIC-specific helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _nm_active():
        """Return True if NetworkManager is the active network manager."""
        return process.system(
            'systemctl is-active NetworkManager',
            shell=True, ignore_status=True) == 0

    @staticmethod
    def _nm_active_peer(session):
        """Return True if NetworkManager is active on the peer."""
        return session.cmd(
            'systemctl is-active NetworkManager 2>/dev/null'
        ).exit_status == 0

    @staticmethod
    def _snapshot_nm_uuids():
        """Return set of all NM connection UUIDs currently on the host."""
        out = process.system_output(
            'nmcli -t -f UUID con show',
            shell=True, ignore_status=True).decode('utf-8', errors='replace')
        return {line.strip() for line in out.splitlines() if line.strip()}

    @staticmethod
    def _snapshot_ip_addrs():
        """
        Return dict mapping interface → list of 'ip addr add <cidr> dev
        <iface>' restore commands for every non-loopback inet address.
        """
        snapshot = {}
        out = process.system_output(
            'ip -o addr show', shell=True,
            ignore_status=True).decode('utf-8', errors='replace')
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[2] != 'inet' or parts[1] == 'lo':
                continue
            iface, cidr = parts[1], parts[3]
            snapshot.setdefault(iface, []).append(
                'ip addr add %s dev %s' % (cidr, iface))
        return snapshot

    def _nic_setup(self):
        """
        Initialise all NIC-test state: read YAML params, resolve interface
        names, open SSH session to peer, disable firewall on both sides,
        snapshot the current IP/NM state on both host and peer (so all
        interfaces can be fully restored regardless of whether NM is
        present), then flush the declared test interfaces ready for
        build_net.
        """
        self.localhost = LocalHost()

        # --- parameters -----------------------------------------------
        self.host_ip = self.params.get('host_public_ip', default=None)
        self.peer_ip = self.params.get('peer_public_ip', default=None)
        self.peer_user = self.params.get('peer_user', default=None)
        self.peer_password = self.params.get('peer_password', default=None)
        self.mdt_file = self.params.get('mdt_file', default='net.mdt')
        self.time_limit = int(
            self.params.get('time_limit', default=2)) * 60
        self.query_cmd = 'htxcmdline -query -mdt %s' % self.mdt_file
        self.htx_rpm_link = self.params.get('htx_rpm_link', default=None)

        # --- resolve host interfaces ----------------------------------
        self.host_intfs = []
        devices = self.params.get('htx_host_interfaces', default=None)
        if devices:
            available = os.listdir('/sys/class/net')
            for device in devices.split():
                if device in available:
                    self.host_intfs.append(device)
                elif (self.localhost.validate_mac_addr(device) and
                      device in self.localhost.get_all_hwaddr()):
                    self.host_intfs.append(
                        self.localhost.get_interface_by_hwaddr(device).name)
                else:
                    self.cancel('Please check the network device: %s' % device)

        self.peer_intfs = self.params.get(
            'peer_interfaces', default='').split()

        # --- SSH session and RemoteHost --------------------------------
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel('Failed connecting to peer %s' % self.peer_ip)
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)

        # --- disable firewall on host ------------------------------------
        host_distro_name = self.detected_distro.name
        host_distro_version = self.detected_distro.version
        if host_distro_name == 'SuSE' and host_distro_version < 15:
            host_fw_cmd = 'rcSuSEfirewall2 stop'
        else:
            host_fw_cmd = 'systemctl stop firewalld'
        if process.system(host_fw_cmd, ignore_status=True, shell=True) != 0:
            self.cancel('Unable to disable firewall on host')

        # --- snapshot state BEFORE build_net modifies interfaces ------
        # build_net assigns HTX 74.x IPs to ALL UP interfaces it finds,
        # not just the ones under test.  We capture the full state here
        # so _ip_restore_host/peer can bring every interface back exactly.
        # Two paths:
        #   NM active  → snapshot NM connection UUIDs (build_net uses
        #                nmcli con add, so new UUIDs identify its work)
        #   NM absent  → snapshot raw inet addresses (build_net uses
        #                ip addr add directly)
        self.host_nm = False
        self.peer_nm = False
        self.pre_htx_nm_uuids = set()       # NM path — host
        self.pre_htx_ip_addrs = {}          # non-NM path — host

        if 'test_htx_nic_start' in str(self.name.name):
            self.host_nm = self._nm_active()
            self.peer_nm = self._nm_active_peer(self.session)

            if self.host_nm:
                self.pre_htx_nm_uuids = self._snapshot_nm_uuids()
                self.log.info('Host uses NM — snapshotted %d UUIDs',
                              len(self.pre_htx_nm_uuids))
            else:
                self.pre_htx_ip_addrs = self._snapshot_ip_addrs()
                self.log.info('Host has no NM — snapshotted IPs on %s',
                              list(self.pre_htx_ip_addrs.keys()))

            if self.peer_nm:
                self.session.cmd(
                    'nmcli -t -f UUID con show 2>/dev/null '
                    '> /tmp/htx_nm_backup')
                self.log.info('Peer uses NM — UUID snapshot written to '
                              '/tmp/htx_nm_backup')
            else:
                self.session.cmd(
                    "ip -o addr show | awk '$3==\"inet\" && $2!=\"lo\""
                    ' {print "ip addr add " $4 " dev " $2}\''
                    ' > /tmp/htx_ip_backup')
                self.log.info('Peer has no NM — IP snapshot written to '
                              '/tmp/htx_ip_backup')

            # Flush only the declared test interfaces before build_net
            for interface in self.host_intfs:
                process.run('ip addr flush dev %s' % interface,
                            shell=True, sudo=True, ignore_status=True)
                process.run('ip link set dev %s up' % interface,
                            shell=True, sudo=True, ignore_status=True)
            for peer_interface in self.peer_intfs:
                self.session.cmd('ip addr flush dev %s' % peer_interface)
                self.session.cmd('ip link set dev %s up' % peer_interface)

        # --- peer distro detection ------------------------------------
        peer_d = distro.detect(session=self.session)
        if peer_d.name == 'Ubuntu':
            self.peer_distro = 'Ubuntu'
        elif peer_d.name == 'rhel':
            self.peer_distro = 'rhel'
        elif peer_d.name == 'SuSE':
            self.peer_distro = 'SuSE'
        else:
            self.fail('Unknown peer distro: %s' % peer_d.name)
        self.peer_distro_version = peer_d.version
        self.log.info('Peer distro: %s %s',
                      self.peer_distro, self.peer_distro_version)

        # --- disable firewall on peer (uses peer distro, not host) -------
        if self.peer_distro == 'SuSE' and self.peer_distro_version < 15:
            peer_fw_cmd = 'rcSuSEfirewall2 stop'
        else:
            peer_fw_cmd = 'systemctl stop firewalld'
        output = self.session.cmd(peer_fw_cmd)
        if output.exit_status != 0:
            self.cancel('Unable to disable firewall on peer')

    def _build_htx_nic(self):
        """
        Install HTX on both host and peer for NIC testing.

        Removes any stale HTX RPMs from both machines first, then
        downloads the correct distro-specific RPM from ``htx_rpm_link``
        and installs it on host; copies and installs on peer.
        """
        packages = ['git', 'gcc', 'make', 'wget']
        detected_distro = distro.detect()
        if detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif detected_distro.name == 'Ubuntu':
            packages.extend(['libncurses5', 'g++', 'ncurses-dev',
                             'libncurses-dev', 'tar', 'wget'])
        elif detected_distro.name == 'SuSE':
            packages.extend(['libncurses6', 'gcc-c++',
                             'ncurses-devel', 'tar', 'wget'])
        else:
            self.cancel('Test not supported in %s' % detected_distro.name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('Cannot install %s' % pkg)
            output = self.session.cmd(
                '%s install %s' % (smm.backend.base_command, pkg))
            if output.exit_status != 0:
                self.cancel(
                    'Unable to install %s on peer machine' % pkg)

        # Remove old HTX RPMs from host
        ins_htx = process.system_output(
            'rpm -qa | grep htx', shell=True,
            sudo=True, ignore_status=True).decode('utf-8').splitlines()
        if ins_htx:
            for rpm in ins_htx:
                process.run('rpm -e %s' % rpm, shell=True, sudo=True,
                            ignore_status=True, timeout=30)
            if os.path.exists(HTX_INSTALL_PATH):
                shutil.rmtree(HTX_INSTALL_PATH)
            self.log.info('Deleted old HTX RPMs from host')

        # Remove old HTX RPMs from peer
        peer_ins_htx = self.session.cmd(
            'rpm -qa | grep htx').stdout.decode('utf-8').splitlines()
        if peer_ins_htx:
            for rpm in peer_ins_htx:
                self.session.cmd('rpm -e %s' % rpm)
            self.log.info('Deleted old HTX RPMs from peer')

        # Normalise distro names to RPM pattern
        host_distro_name = detected_distro.name.lower()
        if host_distro_name == 'suse' or self.peer_distro == 'SuSE':
            host_distro_name = 'sles'
            self.peer_distro = 'sles'
        elif host_distro_name == 'suse':
            host_distro_name = 'sles'

        host_pattern = '%s%s' % (host_distro_name, detected_distro.version)
        peer_pattern = '%s%s' % (self.peer_distro, self.peer_distro_version)

        for pattern in [host_pattern, peer_pattern]:
            scontext = ssl.SSLContext(ssl.PROTOCOL_TLS)
            scontext.verify_mode = ssl.VerifyMode.CERT_NONE
            response = urllib.request.urlopen(
                self.htx_rpm_link, context=scontext)
            versions = re.findall(
                r'(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*',
                response.read().decode('utf-8', errors='replace'))
            matching = sorted(
                [v for v in versions if pattern in v], reverse=True)
            if not matching:
                self.cancel('No HTX RPM found for pattern %s at %s'
                            % (pattern, self.htx_rpm_link))
            latest_rpm = matching[0]

            # Download RPM to current directory
            rpm_url = '%s%s' % (self.htx_rpm_link, latest_rpm)
            cmd = 'curl -kL %s -o /tmp/%s' % (rpm_url, latest_rpm)
            if process.system(cmd, shell=True, ignore_status=True):
                self.cancel('Failed to download HTX RPM: %s' % rpm_url)

            # Same distro: install once and reuse for peer
            if host_pattern == peer_pattern:
                if not RpmBackend.rpm_install(
                        '/tmp/%s' % latest_rpm,
                        no_dependencies=True, replace=False):
                    self.cancel('RPM install failed on host: %s' % latest_rpm)
                dest = '%s:/tmp' % self.peer_ip
                if not self.session.copy_files(
                        '/tmp/%s' % latest_rpm, dest, recursive=True):
                    self.cancel('Failed to copy RPM to peer: %s' % latest_rpm)
                output = self.session.cmd(
                    'rpm -ivh --nodeps /tmp/%s --force' % latest_rpm)
                if output.exit_status != 0:
                    self.cancel('RPM install failed on peer: %s' % latest_rpm)
                break

            if pattern == host_pattern:
                if not RpmBackend.rpm_install(
                        '/tmp/%s' % latest_rpm,
                        no_dependencies=True, replace=False):
                    self.cancel('RPM install failed on host: %s' % latest_rpm)

            if pattern == peer_pattern:
                dest = '%s:/tmp' % self.peer_ip
                if not self.session.copy_files(
                        '/tmp/%s' % latest_rpm, dest, recursive=True):
                    self.cancel('Failed to copy RPM to peer: %s' % latest_rpm)
                output = self.session.cmd(
                    'rpm -ivh --nodeps /tmp/%s --force' % latest_rpm)
                if output.exit_status != 0:
                    self.cancel('RPM install failed on peer: %s' % latest_rpm)

    def _htx_nic_configuration(self):
        """
        Configure network topology on host and peer for the NIC HTX run.

        Runs ``build_net multisystem <peer_ip>`` which assigns net IDs,
        configures interfaces on both LPARs, and verifies ping connectivity.
        Retries up to three times if the initial attempt does not succeed.
        """
        self.log.info('Setting up network configuration on host and peer')
        cmd = 'build_net multisystem %s' % self.peer_ip
        for attempt in range(3):
            output = process.system_output(
                cmd, ignore_status=True, shell=True,
                sudo=True).decode('utf-8')
            if re.search('All networks ping Ok', output):
                self.log.info('HTX network setup successful (attempt %d)',
                              attempt + 1)
                break
        output = process.system_output(
            'pingum', ignore_status=True,
            shell=True, sudo=True).decode('utf-8')
        if not re.search('All networks ping Ok', output):
            self.fail('Failed to set HTX network configuration on '
                      'host and peer')

    def _start_htx_nic_run(self):
        """
        Start the HTX NIC run on both host and peer.

        Kills any existing HXE process first, then issues
        ``htxcmdline -run`` on both machines.
        """
        self.log.info('Running HTX for %s on host', self.mdt_file)
        hxe_pid = process.getoutput('pgrep -f hxe', ignore_status=True)
        if hxe_pid.strip():
            self.log.info('HXE running with PID %s; shutting down',
                          hxe_pid.strip())
            process.run('hcl -shutdown', ignore_status=True)
            time.sleep(20)
        cmd = 'htxcmdline -run -mdt %s' % self.mdt_file
        process.run(cmd, shell=True, sudo=True)
        self.log.info('Running HTX for %s on peer', self.mdt_file)
        self.session.cmd(cmd)

    def _monitor_htx_nic_run(self):
        """
        Poll HTX error logs on both host and peer every 60 s for
        the configured ``time_limit`` duration.  Fails immediately if
        errors are detected on either side.

        Host status query uses the specific interface names from
        ``htx_host_interfaces`` so HTX reports per-device activity;
        fails if any listed interface is absent from the output.
        Peer status query is a generic MDT-wide ``htxcmdline -query
        -mdt <mdt>`` — output is logged for visibility only.
        """
        host_intfs = ' '.join(self.host_intfs)
        host_status_cmd = ('htxcmdline -query %s -mdt %s'
                           % (host_intfs, self.mdt_file)
                           if host_intfs else self.query_cmd)

        for _ in range(0, self.time_limit, 60):
            self.log.info('Monitoring HTX error logs on host')
            ret = process.system(
                'htxcmdline -geterrlog',
                shell=True, sudo=True, ignore_status=True)
            if ret != 0:
                self.fail('htxcmdline -geterrlog failed on host '
                          '(exit %d); HTX may not be running' % ret)
            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail('HTX errors detected on host; check /tmp/htxerr')

            self.log.info('Monitoring HTX error logs on peer')
            peer_ret = self.session.cmd('htxcmdline -geterrlog',
                                        ignore_status=True)
            if peer_ret.exit_status != 0:
                self.fail('htxcmdline -geterrlog failed on peer '
                          '(exit %d); HTX may not be running'
                          % peer_ret.exit_status)
            peer_err = self.session.cmd('test -s /tmp/htxerr',
                                        ignore_status=True)
            if peer_err.exit_status == 0:
                peer_log = self.session.cmd('cat /tmp/htxerr',
                                            ignore_status=True)
                self.log.debug('HTX error log on peer:\n%s',
                               peer_log.stdout.decode('utf-8'))
                self.fail('HTX errors detected on peer; check /tmp/htxerr')

            self.log.info('NIC device status for host interfaces: %s',
                          host_intfs or 'all')
            host_query_out = process.system_output(
                host_status_cmd, ignore_status=True,
                shell=True, sudo=True).decode('utf-8')
            self.log.debug('Host HTX query output:\n%s', host_query_out)
            if self.host_intfs:
                not_running = [
                    intf for intf in self.host_intfs
                    if intf not in host_query_out
                ]
                if not_running:
                    self.fail(
                        'HTX failed to start for the interface(s): %s'
                        % ', '.join(not_running))

            self.log.info('NIC device status on peer MDT: %s', self.mdt_file)
            peer_query = self.session.cmd(self.query_cmd, ignore_status=True)
            peer_query_out = peer_query.stdout.decode(
                'utf-8', errors='replace')
            self.log.debug('Peer HTX query output:\n%s', peer_query_out)

            time.sleep(60)

    def _shutdown_active_mdt_nic(self):
        """
        Shut down the active MDT on both host and peer.
        """
        self.log.info('Shutting down active MDT on host')
        process.run('htxcmdline -shutdown', timeout=120,
                    ignore_status=True, shell=True, sudo=True)
        self.log.info('Shutting down active MDT on peer')
        self.session.cmd('htxcmdline -shutdown')

    def _shutdown_htx_daemon_nic(self):
        """
        Stop the HTX daemon on both host and peer if running.
        """
        status_cmd = '%s/etc/scripts/htx.d status' % HTX_INSTALL_PATH
        shutdown_cmd = '%s/etc/scripts/htxd_shutdown' % HTX_INSTALL_PATH

        daemon_state = process.system_output(
            status_cmd, ignore_status=True,
            shell=True, sudo=True).decode('utf-8')
        if daemon_state.split()[-1:] == ['running']:
            process.system(shutdown_cmd, ignore_status=True,
                           shell=True, sudo=True)

        try:
            output = self.session.cmd(status_cmd)
            line = output.stdout.decode('utf-8').splitlines()
            if line and 'running' in line[0]:
                self.session.cmd(shutdown_cmd)
        except Exception:
            self.log.info('Unable to get peer HTXD status')

    def _ip_restore_host(self):
        """
        Restore ALL host interfaces to their pre-HTX state.

        NM active:  delete every NM connection UUID that build_net added
                    (any UUID not in the pre-run snapshot), then bring
                    the original connections back up.
        NM absent:  flush every interface that now has a 74.x HTX address
                    and re-add only the original addresses from the
                    pre-run snapshot.
        """
        if not hasattr(self, 'host_nm'):
            self.log.info('No pre-HTX snapshot on host; skipping restore')
            return

        if self.host_nm:
            if not self.pre_htx_nm_uuids:
                self.log.info('No pre-HTX NM UUID snapshot; skipping')
                return
            post_uuids = self._snapshot_nm_uuids()
            htx_uuids = post_uuids - self.pre_htx_nm_uuids
            self.log.info('Deleting %d HTX NM connections on host: %s',
                          len(htx_uuids), htx_uuids)
            for uuid in htx_uuids:
                process.run('nmcli con delete %s' % uuid,
                            shell=True, sudo=True, ignore_status=True)
            for uuid in self.pre_htx_nm_uuids:
                process.run('nmcli con up %s' % uuid,
                            shell=True, sudo=True, ignore_status=True)
            self.log.info('Host NM connections restored')
        else:
            if not self.pre_htx_ip_addrs:
                self.log.info('No pre-HTX IP snapshot; skipping')
                return
            for iface, restore_cmds in self.pre_htx_ip_addrs.items():
                process.run('ip addr flush dev %s' % iface,
                            shell=True, sudo=True, ignore_status=True)
                for cmd in restore_cmds:
                    process.run(cmd, shell=True, sudo=True,
                                ignore_status=True)
                process.run('ip link set dev %s up' % iface,
                            shell=True, sudo=True, ignore_status=True)
                self.log.info('Host interface %s restored', iface)

    def _ip_restore_peer(self):
        """
        Restore ALL peer interfaces to their pre-HTX state.

        NM active:  reads /tmp/htx_nm_backup (pre-run UUID list written
                    by _nic_setup), deletes new UUIDs, brings originals up.
        NM absent:  reads /tmp/htx_ip_backup (pre-run ip addr snapshot),
                    flushes affected interfaces and re-adds original IPs.
        """
        if not hasattr(self, 'peer_nm'):
            self.log.info('No pre-HTX snapshot on peer; skipping restore')
            return

        if self.peer_nm:
            backup = self.session.cmd(
                'cat /tmp/htx_nm_backup 2>/dev/null')
            pre_uuids = {
                line.strip()
                for line in backup.stdout.decode(
                    'utf-8', errors='replace').splitlines()
                if line.strip()
            }
            if not pre_uuids:
                self.log.info('Peer NM backup empty; skipping')
                return
            post_out = self.session.cmd(
                'nmcli -t -f UUID con show 2>/dev/null')
            post_uuids = {
                line.strip()
                for line in post_out.stdout.decode(
                    'utf-8', errors='replace').splitlines()
                if line.strip()
            }
            htx_uuids = post_uuids - pre_uuids
            self.log.info('Deleting %d HTX NM connections on peer: %s',
                          len(htx_uuids), htx_uuids)
            for uuid in htx_uuids:
                self.session.cmd('nmcli con delete %s' % uuid)
            for uuid in pre_uuids:
                self.session.cmd('nmcli con up %s 2>/dev/null' % uuid)
            self.log.info('Peer NM connections restored')
            self.session.cmd('rm -f /tmp/htx_nm_backup')
        else:
            backup = self.session.cmd(
                'cat /tmp/htx_ip_backup 2>/dev/null')
            restore_cmds = backup.stdout.decode(
                'utf-8', errors='replace').splitlines()
            if not restore_cmds:
                self.log.info('Peer IP backup empty; skipping')
                return
            affected = {
                cmd.split()[4]
                for cmd in restore_cmds
                if len(cmd.split()) >= 5
            }
            for iface in affected:
                self.session.cmd('ip addr flush dev %s' % iface)
            for cmd in restore_cmds:
                self.session.cmd(cmd)
            for iface in affected:
                self.session.cmd('ip link set dev %s up' % iface)
            self.log.info('Peer interfaces restored via ip addr')
            self.session.cmd('rm -f /tmp/htx_ip_backup')

    def _htx_nic_cleanup(self):
        """
        Full NIC teardown: shutdown MDT, stop daemons on both sides,
        restore IPs, and close the remote session.
        """
        self._shutdown_active_mdt_nic()
        self._shutdown_htx_daemon_nic()
        self._ip_restore_host()
        self._ip_restore_peer()
        self.remotehost.remote_session.quit()

    # ------------------------------------------------------------------
    # NIC test methods
    # ------------------------------------------------------------------

    def test_htx_nic_start(self):
        """
        Phase 1 — install HTX on host and peer (build_htx_nic).
        Phase 2 — configure network topology (build_net multisystem).
        Phase 3 — start the HTX NIC run on both machines.
        """
        self._build_htx_nic()
        self._htx_nic_configuration()
        self._start_htx_nic_run()

    def test_htx_nic_check(self):
        """
        Poll HTX error logs on both host and peer every 60 s for the
        configured duration (``time_limit`` minutes).
        """
        self._monitor_htx_nic_run()

    def test_htx_nic_stop(self):
        """
        Shut down the HTX NIC run: stop MDT and daemon on both sides,
        restore IP addresses, and close the SSH session.
        """
        self._htx_nic_cleanup()

    def tearDown(self):
        """
        Guaranteed cleanup after every test method (PASS, FAIL, ERROR,
        CANCEL).

        Only closes the SSH session/RemoteHost that _nic_setup() opens for
        NIC tests.  IP restore and HTX shutdown are intentionally NOT done
        here — those are stateful operations that belong exclusively in
        test_htx_nic_stop → _htx_nic_cleanup(), so the HTX-assigned NIC
        addresses remain live through test_htx_nic_check and are only
        torn down when test_htx_nic_stop is explicitly run.
        """
        if hasattr(self, 'remotehost') and self.remotehost:
            try:
                self.remotehost.remote_session.quit()
            except Exception:
                pass

        if hasattr(self, 'session') and self.session:
            try:
                self.session.quit()
            except Exception:
                pass

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
# Author: Naresh Bannoth <nbannoth@in.ibm.com>
# Author: Pridhiviraj Paidipeddi <ppaidipe@linux.vnet.ibm.com>
# Author: Vaishnavi Bhat <vaishnavi@linux.vnet.ibm.com>
# Author: Abdul Haleem  <abdhalee@linux.vnet.ibm.com>

"""
Unified HTX Test Suite

This consolidated test supports three types of HTX testing:
1. Generic HTX - General hardware stress testing with any MDT file
2. Storage HTX - Block device specific stress testing
3. Network HTX - Multi-system network stress testing

The test type is automatically detected based on parameters or can be
explicitly set using the 'test_type' parameter.
"""

import os
import re
import time
import shutil
import urllib.request
import ssl

from avocado import Test
from avocado.utils import build, process, archive, distro
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import disk, multipath
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.ssh import Session
from avocado.utils.download import url_download


class HtxTest(Test):
    """
    Unified HTX Test Class

    HTX [Hardware Test eXecutive] is a test tool suite. The goal of HTX is to
    stress test the system by exercising all hardware components concurrently
    in order to uncover any hardware design flaws and hardware-hardware or
    hardware-software interaction issues.

    Common Parameters:
    :param test_type: Type of HTX test - 'generic', 'storage', or 'network'
                      (auto-detected if not specified)
    :param mdt_file: MDT file used to trigger HTX
    :param time_limit: How long to run the stress test
    :param time_unit: Time unit for time_limit ('m' for minutes, 'h' for hours)
    :param run_type: Installation type - 'git' or 'rpm' (default: 'rpm')
    :param htx_rpm_link: URL to HTX RPM repository

    Storage-specific Parameters:
    :param htx_disks: Space-separated list of block devices
    :param all: Use all disks in MDT file (default: False)

    Network-specific Parameters:
    :param host_public_ip: Public IP address of host
    :param peer_public_ip: Public IP address of peer
    :param peer_user: Username for peer system
    :param peer_password: Password for peer system
    :param htx_host_interfaces: Space-separated list of host network interfaces
    :param peer_interfaces: Space-separated list of peer network interfaces
    """

    def setUp(self):
        """
        Setup and initialization for HTX tests
        """
        # Platform validation
        if 'ppc64' not in distro.detect().arch:
            self.cancel("HTX tests are supported only on Power Architecture")

        # Get common parameters
        self.mdt_file = self.params.get('mdt_file', default='mdt.mem')
        self.time_limit = int(self.params.get('time_limit', default=2))
        self.time_unit = self.params.get('time_unit', default='m')
        self.run_type = self.params.get('run_type', default='rpm')
        self.htx_rpm_link = self.params.get('htx_rpm_link', default=None)

        # Convert time to seconds
        if self.time_unit == 'm':
            self.time_limit = self.time_limit * 60
        elif self.time_unit == 'h':
            self.time_limit = self.time_limit * 3600
        else:
            self.cancel("Time unit must be 'm' (minutes) or 'h' (hours)")

        # Detect or get test type
        self.test_type = self._detect_test_type()
        self.log.info("HTX Test Type: %s", self.test_type)

        # Initialize type-specific parameters
        if self.test_type == 'storage':
            self._setup_storage_params()
        elif self.test_type == 'network':
            self._setup_network_params()

        # Setup HTX only at test_start phase
        if str(self.name.name).endswith('test_start'):
            self.setup_htx()

        # Validate MDT file exists
        if not os.path.exists("/usr/lpp/htx/mdt/%s" % self.mdt_file):
            self.log.info(
                "MDT file %s not found, will create it", self.mdt_file)

    def _detect_test_type(self):
        """
        Auto-detect test type based on parameters
        """
        test_type = self.params.get('test_type', default=None)
        if test_type:
            return test_type.lower()

        # Auto-detection logic
        peer_ip = self.params.get('peer_public_ip', default=None)
        htx_disks = self.params.get('htx_disks', default=None)
        all_disks = self.params.get('all', default=False)

        if peer_ip:
            return 'network'
        elif htx_disks or all_disks:
            return 'storage'
        else:
            return 'generic'

    def _setup_storage_params(self):
        """
        Initialize storage-specific parameters and validate devices
        """
        self.mdt_file = self.params.get('mdt_file', default='mdt.hd')
        self.block_devices = self.params.get('htx_disks', default=None)
        self.all = self.params.get('all', default=False)

        if not self.all and self.block_devices is None:
            self.cancel("Storage test requires 'htx_disks' or 'all=True'")

        # Get root/boot disk to exclude from testing
        self.root_disk = self._get_root_disk()
        self.log.info("Root/boot disk detected: %s", self.root_disk)

        if self.all:
            self.block_device = ""
        else:
            self.block_device = []
            for dev in self.block_devices.split():
                dev_path = disk.get_absolute_disk_path(dev)
                dev_base = os.path.basename(os.path.realpath(dev_path))

                # Check if this is the root disk
                if self._is_root_disk(dev_base):
                    self.log.warning("Skipping root/boot disk: %s", dev_base)
                    continue

                if 'dm' in dev_base:
                    dev_base = multipath.get_mpath_from_dm(dev_base)
                    # Check again after multipath resolution
                    if self._is_root_disk(dev_base):
                        self.log.warning(
                            "Skipping root/boot disk (multipath): %s", dev_base)
                        continue

                self.block_device.append(dev_base)

            if not self.block_device:
                self.cancel(
                    "No valid block devices to test after excluding root disk")

            self.block_device = " ".join(self.block_device)
            self.log.info("Block devices to test: %s", self.block_device)

    def _setup_network_params(self):
        """
        Initialize network-specific parameters
        """
        self.mdt_file = self.params.get('mdt_file', default='net.mdt')
        self.localhost = LocalHost()

        # Network parameters
        self.host_ip = self.params.get('host_public_ip', default=None)
        self.peer_ip = self.params.get('peer_public_ip', default=None)
        self.peer_user = self.params.get('peer_user', default='root')
        self.peer_password = self.params.get('peer_password', default=None)

        # Build_net automation parameters
        self.onesys_test = self.params.get('onesys_test', default='n')
        self.walk_zero = self.params.get('walk_zero', default='n')
        self.force_defaults = self.params.get('force_defaults', default='y')
        self.use_automation = self.params.get('use_automation', default='y')
        self.seed = self.params.get('seed', default='1234')

        # For multi-system tests, peer_ip is required
        if self.onesys_test == 'n' and not self.peer_ip:
            self.cancel(
                "Multi-system network test requires 'peer_public_ip' parameter")

        # Setup host interfaces
        self.host_intfs = []
        devices = self.params.get('htx_host_interfaces', default=None)
        if devices:
            interfaces = os.listdir('/sys/class/net')
            for device in devices.split():
                if device in interfaces:
                    self.host_intfs.append(device)
                elif self.localhost.validate_mac_addr(device) and \
                        device in self.localhost.get_all_hwaddr():
                    self.host_intfs.append(
                        self.localhost.get_interface_by_hwaddr(device).name)
                else:
                    self.cancel("Invalid network device: %s" % device)

        # Setup peer interfaces for multi-system tests
        peer_intfs = self.params.get('peer_interfaces', default=None)
        self.peer_intfs = peer_intfs.split() if peer_intfs else []

        # Setup SSH session for multi-system tests
        if self.onesys_test == 'n':
            self.session = Session(self.peer_ip, user=self.peer_user,
                                   password=self.peer_password)
            if not self.session.connect():
                self.cancel("Failed to connect to peer system")

            self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                         password=self.peer_password)

            # Disable firewall on host and peer
            self._disable_firewall()

            # Flush IP addresses if starting test
            if 'start' in str(self.name.name):
                self._flush_network_config()

    def _disable_firewall(self):
        """
        Disable firewall on both host and peer systems
        """
        detected_distro = distro.detect()
        if detected_distro.name in ['rhel', 'fedora', 'redhat']:
            cmd = "systemctl stop firewalld"
        elif detected_distro.name == "SuSE":
            if detected_distro.version >= 15:
                cmd = "systemctl stop firewalld"
            else:
                cmd = "rcSuSEfirewall2 stop"
        else:
            return

        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.log.warning("Unable to disable firewall on host")

        output = self.session.cmd(cmd)
        if output.exit_status != 0:
            self.log.warning("Unable to disable firewall on peer")

    def _flush_network_config(self):
        """
        Flush IP addresses on host and peer interfaces
        """
        for interface in self.host_intfs:
            cmd = 'ip addr flush dev %s' % interface
            process.run(cmd, shell=True, sudo=True, ignore_status=True)
            cmd = 'ip link set dev %s up' % interface
            process.run(cmd, shell=True, sudo=True, ignore_status=True)

        for peer_interface in self.peer_intfs:
            cmd = 'ip addr flush dev %s' % peer_interface
            self.session.cmd(cmd)
            cmd = 'ip link set dev %s up' % peer_interface
            self.session.cmd(cmd)

    def setup_htx(self):
        """
        Build and install HTX
        """
        self.detected_distro = distro.detect()
        self.dist_name = self.detected_distro.name.lower()
        self.dist_version = self.detected_distro.version

        # Install required packages
        packages = ['git', 'gcc', 'make', 'ndctl']
        if self.dist_name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif self.dist_name == 'ubuntu':
            packages.extend(['libncurses5', 'g++', 'ncurses-dev',
                             'libncurses-dev', 'tar'])
        elif self.dist_name == 'suse':
            packages.extend(['libncurses6', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            self.cancel("Test not supported on %s" % self.dist_name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Cannot install package: %s" % pkg)

        # Install HTX based on run_type
        if self.run_type == 'git':
            self._install_htx_from_git()
        else:
            self._install_htx_from_rpm()

        # Start HTX daemon
        self._start_htx_daemon()

        # Enable on-demand MDT creation
        cmd = "hcl -set_htx_env HTX_ON_DEMAND_MDT_CREATION 1"
        self.log.info("Enabling on-demand HTX MDT support")
        process.run(cmd, ignore_status=True)

        # Create MDT file if needed
        if not os.path.exists("/usr/lpp/htx/mdt/%s" % self.mdt_file):
            self.log.info("Creating MDT file: %s", self.mdt_file)
            cmd = "htxcmdline -createmdt -mdt %s" % self.mdt_file
            process.run(cmd, ignore_status=True)

    def _install_htx_from_git(self):
        """
        Install HTX from GitHub source
        """
        if self.detected_distro.name == 'rhel' and \
                self.detected_distro.version <= "9":
            self.cancel("Git installation not supported on RHEL <= 9")

        url = "https://github.com/open-power/HTX/archive/master.zip"
        tarball = self.fetch_asset("htx.zip", locations=[url], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        htx_path = os.path.join(self.teststmpdir, "HTX-master")
        os.chdir(htx_path)

        # Remove unsupported exercisers
        exercisers = ["hxecapi_afu_dir", "hxedapl", "hxecapi", "hxeocapi"]
        for exerciser in exercisers:
            process.run("sed -i 's/%s//g' %s/bin/Makefile" %
                        (exerciser, htx_path), ignore_status=True)

        build.make(htx_path, extra_args='all')
        build.make(htx_path, extra_args='tar')
        process.run('tar --touch -xvzf htx_package.tar.gz')
        os.chdir('htx_package')
        if process.system('./installer.sh -f'):
            self.fail("HTX installation failed")

    def _install_htx_from_rpm(self):
        """
        Install HTX from RPM package
        """
        if self.dist_name == 'suse':
            self.dist_name = 'sles'

        rpm_check = "htx%s%s" % (self.dist_name, self.dist_version)
        skip_install = False

        # Check existing installation
        ins_htx = process.system_output(
            'rpm -qa | grep htx', shell=True, ignore_status=True).decode()

        if ins_htx:
            if not SoftwareManager().check_installed(rpm_check):
                self.log.info("Clearing existing HTX RPM")
                process.system('rpm -e %s' % ins_htx,
                               shell=True, ignore_status=True)
                if os.path.exists('/usr/lpp/htx'):
                    shutil.rmtree('/usr/lpp/htx')
            else:
                self.log.info("Using existing HTX installation")
                skip_install = True

        if not skip_install:
            if not self.htx_rpm_link:
                self.cancel(
                    "htx_rpm_link parameter required for RPM installation")
            self._install_latest_htx_rpm()

        # For network tests, install on peer as well
        if self.test_type == 'network':
            self._install_htx_on_peer()

    def _install_latest_htx_rpm(self):
        """
        Download and install the latest HTX RPM for the current distro
        """
        distro_pattern = "%s%s" % (self.dist_name, self.dist_version)

        try:
            temp_string = process.getoutput(
                "curl --silent -k %s" % self.htx_rpm_link,
                verbose=False, shell=True, ignore_status=True)

            matching_htx_versions = re.findall(
                r"(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*", str(temp_string))

            distro_specific_htx_versions = [
                htx_rpm for htx_rpm in matching_htx_versions
                if distro_pattern in htx_rpm]

            if not distro_specific_htx_versions:
                self.cancel("No HTX RPM found for %s" % distro_pattern)

            distro_specific_htx_versions.sort(reverse=True)
            self.latest_htx_rpm = distro_specific_htx_versions[0]

            tmp_dir = "/tmp/" + self.latest_htx_rpm
            cmd = "curl -k %s/%s -o %s" % (self.htx_rpm_link,
                                           self.latest_htx_rpm, tmp_dir)

            if process.system(cmd, shell=True, ignore_status=True):
                self.cancel("HTX RPM download failed")

            cmd = "rpm -ivh --nodeps --force %s" % tmp_dir
            if process.system(cmd, shell=True, ignore_status=True):
                self.cancel("HTX RPM installation failed")

            # Cleanup
            process.run("rm -rf %s" % tmp_dir, ignore_status=True)

        except Exception as e:
            self.cancel("HTX RPM installation error: %s" % str(e))

    def _install_htx_on_peer(self):
        """
        Install HTX on peer system for network tests
        """
        # Get peer distro info
        detected_distro = distro.detect(session=self.session)
        peer_distro = detected_distro.name.lower()
        peer_version = detected_distro.version

        if peer_distro == 'suse':
            peer_distro = 'sles'

        # Remove old HTX installations on peer
        peer_ins_htx = self.session.cmd('rpm -qa | grep htx')
        peer_ins_htx = peer_ins_htx.stdout.decode("utf-8").splitlines()
        if peer_ins_htx:
            for rpm in peer_ins_htx:
                self.session.cmd('rpm -e %s' % rpm)
            self.log.info("Removed old HTX from peer")

        # Download and install HTX on peer
        peer_distro_pattern = "%s%s" % (peer_distro, peer_version)

        scontext = ssl.SSLContext(ssl.PROTOCOL_TLS)
        scontext.verify_mode = ssl.VerifyMode.CERT_NONE
        response = urllib.request.urlopen(self.htx_rpm_link, context=scontext)
        temp_string = response.read()

        matching_htx_versions = re.findall(
            r"(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*", str(temp_string))

        distro_specific_htx_versions = [
            htx_rpm for htx_rpm in matching_htx_versions
            if peer_distro_pattern in htx_rpm]

        if not distro_specific_htx_versions:
            self.cancel("No HTX RPM found for peer: %s" % peer_distro_pattern)

        distro_specific_htx_versions.sort(reverse=True)
        peer_htx_rpm = distro_specific_htx_versions[0]

        # Download RPM
        cmd = '%s/%s' % (self.htx_rpm_link, peer_htx_rpm)
        url_download(cmd, peer_htx_rpm)

        # Copy to peer
        destination = "%s:/tmp" % self.peer_ip
        if not self.session.copy_files(peer_htx_rpm, destination, recursive=True):
            self.cancel("Failed to copy HTX RPM to peer")

        # Install on peer
        cmd = 'rpm -ivh --nodeps --force /tmp/%s' % peer_htx_rpm
        output = self.session.cmd(cmd)
        if output.exit_status != 0:
            self.cancel("HTX installation failed on peer")

    def _start_htx_daemon(self):
        """
        Start the HTX daemon
        """
        self.log.info("Starting HTX daemon")

        # Kill existing HTXD process if running
        htxd_pid = process.getoutput("pgrep -f htxd")
        if htxd_pid:
            self.log.info(
                "HTXD already running (PID: %s), killing it", htxd_pid)
            process.run("pkill -f htxd", ignore_status=True)
            time.sleep(10)

        process.run('/usr/lpp/htx/etc/scripts/htxd_run', ignore_status=True)

    def test_start(self):
        """
        Start HTX test based on test type
        """
        if self.test_type == 'generic':
            self._start_generic_test()
        elif self.test_type == 'storage':
            self._start_storage_test()
        elif self.test_type == 'network':
            self._start_network_test()

    def _start_generic_test(self):
        """
        Start generic HTX test
        """
        self.log.info("Starting generic HTX test with MDT: %s", self.mdt_file)

        # Select MDT file
        cmd = "htxcmdline -select -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        # Activate MDT
        self.log.info("Activating %s", self.mdt_file)
        cmd = "htxcmdline -activate -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        # Run HTX
        self.log.info("Running HTX")
        cmd = "htxcmdline -run -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

    def _start_storage_test(self):
        """
        Start storage HTX test
        """
        self.log.info("Starting storage HTX test")

        # Stop existing HXE processes
        hxe_pid = process.getoutput("pgrep -f hxe")
        if hxe_pid:
            self.log.info(
                "HXE already running (PID: %s), shutting down", hxe_pid)
            process.run("hcl -shutdown", ignore_status=True)
            time.sleep(20)

        # Create MDT if needed
        if not os.path.exists("/usr/lpp/htx/mdt/%s" % self.mdt_file):
            process.run("htxcmdline -createmdt -mdt %s" % self.mdt_file,
                        ignore_status=True)
            if not os.path.exists("/usr/lpp/htx/mdt/%s" % self.mdt_file):
                self.fail("MDT file creation failed: %s" % self.mdt_file)

        # Select MDT file
        self.log.info("Selecting MDT file: %s", self.mdt_file)
        cmd = "htxcmdline -select -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

        # Verify devices in MDT
        if not self.all:
            if not self._is_block_device_in_mdt():
                self.fail("Block devices %s not found in %s" %
                          (self.block_device, self.mdt_file))

        # Suspend all devices first
        self._suspend_all_block_devices()

        # Activate specified devices
        self.log.info("Activating devices: %s", self.block_device)
        cmd = "htxcmdline -activate %s -mdt %s" % (self.block_device,
                                                   self.mdt_file)
        process.system(cmd, ignore_status=True)

        # Verify activation
        if not self.all:
            if not self._is_block_device_active():
                self.fail("Failed to activate block devices")

        # Run HTX
        self.log.info("Running HTX on devices: %s", self.block_device)
        cmd = "htxcmdline -run -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

    def _start_network_test(self):
        """
        Start network HTX test
        """
        self.log.info("Starting network HTX test")

        # Configure network topology
        self._configure_network_topology()

        # Start HTX on host
        self.log.info("Running HTX on host with MDT: %s", self.mdt_file)
        hxe_pid = process.getoutput("pgrep -f hxe")
        if hxe_pid:
            self.log.info(
                "HXE already running (PID: %s), shutting down", hxe_pid)
            process.run("hcl -shutdown", ignore_status=True)
            time.sleep(20)

        cmd = "htxcmdline -run -mdt %s" % self.mdt_file
        process.run(cmd, shell=True, sudo=True)

        # Start HTX on peer
        self.log.info("Running HTX on peer with MDT: %s", self.mdt_file)
        self.session.cmd(cmd)

    def _configure_network_topology(self):
        """
        Configure network topology for HTX network test using automated build_net

        The new build_net script with automation automatically detects network
        topology and configures test networks. This is the default flow for
        automated test runs.

        Syntax: build_net help onesys walk_zero patent force_defaults seed use_automation
        """
        self.log.info("Configuring network topology using automated build_net")
        self.log.info(
            "Test mode: %s", "Single-system" if self.onesys_test == 'y' else "Multi-system")

        # Build the build_net command with automation parameters
        # Automation is enabled by default for automated test runs
        cmd = "build_net help %s %s n %s %s %s" % (
            self.onesys_test, self.walk_zero, self.force_defaults,
            self.seed, self.use_automation)

        # Execute build_net with automation on host
        self.log.info("Executing build_net on host: %s", cmd)
        output = process.system_output(cmd, ignore_status=True, shell=True,
                                       sudo=True).decode("utf-8")

        self.log.info("Build_net output:\n%s", output)

        # Check if automation was successful
        if "All networks ping" in output and "ok" in output.lower():
            self.log.info("Build_net completed successfully on host")
        else:
            self.log.warning(
                "Build_net did not report success, will verify with pingum")

        # For multi-system tests, also run build_net on peer
        if self.onesys_test == 'n' and hasattr(self, 'session'):
            self.log.info(
                "Configuring network on peer system: %s", self.peer_ip)
            peer_output = self.session.cmd(cmd)

            if peer_output.exit_status != 0:
                self.log.warning("Peer build_net returned non-zero status: %d",
                                 peer_output.exit_status)

            peer_stdout = peer_output.stdout.decode("utf-8")
            self.log.info("Peer build_net output:\n%s", peer_stdout)

            if "All networks ping" in peer_stdout and "ok" in peer_stdout.lower():
                self.log.info("Build_net completed successfully on peer")

        # Remove default network interface from bpt file for safety
        self._remove_default_devices_from_bpt()

        # Verify network configuration with pingum
        self.log.info("Verifying network configuration with pingum")
        time.sleep(5)  # Allow time for network setup to complete

        for attempt in range(3):
            output = process.system_output('pingum', ignore_status=True,
                                           shell=True, sudo=True).decode("utf-8")
            self.log.info("Pingum attempt %d:\n%s", attempt + 1, output)

            if "All networks ping" in output and "ok" in output.lower():
                self.log.info(
                    "✓ Network configuration verified - all networks ping OK")
                return

            if attempt < 2:
                self.log.warning(
                    "Network verification incomplete, retrying in 10 seconds...")
                time.sleep(10)

        # If verification failed after retries
        self.log.error("Network topology configuration verification failed")
        self.log.error("Troubleshooting steps:")
        self.log.error("1. Verify network cables are properly connected")
        self.log.error("2. Check that network interfaces are up: ip link show")
        self.log.error("3. Verify no IP conflicts exist")
        self.log.error("4. Ensure firewall is disabled on both systems")
        self.log.error("5. Check build_net logs for detailed error messages")

        if self.use_automation == 'n':
            self.log.error(
                "Manual configuration mode - check bpt file and run 'build_net bpt'")

        self.fail(
            "Failed to configure network topology - pingum verification failed")

    def test_check(self):
        """
        Monitor HTX test execution
        """
        if self.test_type == 'generic':
            self._check_generic_test()
        elif self.test_type == 'storage':
            self._check_storage_test()
        elif self.test_type == 'network':
            self._check_network_test()

    def _check_generic_test(self):
        """
        Monitor generic HTX test
        """
        for _ in range(0, self.time_limit, 60):
            self.log.info("Checking HTX error logs")
            process.system('htxcmdline -geterrlog', ignore_status=True)

            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("HTX errors detected - check /tmp/htxerr")

            cmd = 'htxcmdline -query -mdt %s' % self.mdt_file
            process.system(cmd, ignore_status=True)
            time.sleep(60)

    def _check_storage_test(self):
        """
        Monitor storage HTX test
        """
        for _ in range(0, self.time_limit, 60):
            self.log.info("Checking HTX error logs")
            process.run("htxcmdline -geterrlog", ignore_status=True)

            if os.stat("/tmp/htxerr").st_size != 0:
                self.fail("HTX errors detected - check /tmp/htxerr")

            self.log.info("Device status:")
            cmd = "htxcmdline -query %s -mdt %s" % (self.block_device,
                                                    self.mdt_file)
            process.system(cmd, ignore_status=True)
            time.sleep(60)

    def _check_network_test(self):
        """
        Monitor network HTX test
        """
        for _ in range(0, self.time_limit, 60):
            # Check host errors
            self.log.info("Checking HTX error logs on host")
            cmd = 'htxcmdline -geterrlog'
            process.run(cmd, ignore_status=True, shell=True, sudo=True)

            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("HTX errors detected on host - check /tmp/htxerr")

            # Check peer errors
            self.log.info("Checking HTX error logs on peer")
            self.session.cmd(cmd)
            output = self.session.cmd('test -s /tmp/htxerr')

            if output.exit_status == 0:
                output = self.session.cmd("cat /tmp/htxerr")
                self.log.error("HTX errors on peer: %s",
                               output.stdout.decode("utf-8"))
                self.fail("HTX errors detected on peer")

            # Query status
            self.log.info("Network device status")
            query_cmd = "htxcmdline -query -mdt %s" % self.mdt_file
            process.system(query_cmd, ignore_status=True,
                           shell=True, sudo=True)
            self.session.cmd(query_cmd)

            time.sleep(60)

    def test_stop(self):
        """
        Stop HTX test and cleanup
        """
        if self.test_type == 'generic':
            self._stop_generic_test()
        elif self.test_type == 'storage':
            self._stop_storage_test()
        elif self.test_type == 'network':
            self._stop_network_test()

    def _stop_generic_test(self):
        """
        Stop generic HTX test
        """
        self.log.info("Shutting down HTX: %s", self.mdt_file)
        cmd = 'htxcmdline -shutdown -mdt %s' % self.mdt_file
        process.system(cmd, timeout=120, ignore_status=True)

        if self.run_type == 'rpm':
            process.system('/usr/lpp/htx/etc/scripts/htxd_shutdown',
                           ignore_status=True)
            process.system('umount /htx_pmem*', shell=True, ignore_status=True)
        else:
            self._shutdown_htx_daemon()

    def _stop_storage_test(self):
        """
        Stop storage HTX test
        """
        if self._is_block_device_active():
            self.log.info("Suspending active devices")
            self._suspend_all_block_devices()

        self.log.info("Shutting down HTX: %s", self.mdt_file)
        cmd = "htxcmdline -shutdown -mdt %s" % self.mdt_file
        process.system(cmd, timeout=120, ignore_status=True)

        self._shutdown_htx_daemon()

    def _stop_network_test(self):
        """
        Stop network HTX test
        """
        # Shutdown HTX on both systems
        self.log.info("Shutting down HTX on host")
        cmd = "htxcmdline -shutdown"
        process.run(cmd, timeout=120, ignore_status=True,
                    shell=True, sudo=True)

        self.log.info("Shutting down HTX on peer")
        self.session.cmd(cmd)

        # Shutdown daemons
        self._shutdown_htx_daemon()

        # Restore network configuration
        self._restore_network_config()

        # Close remote session
        if hasattr(self, 'remotehost'):
            self.remotehost.remote_session.quit()

    def _shutdown_htx_daemon(self):
        """
        Shutdown HTX daemon if running
        """
        status_cmd = '/usr/lpp/htx/etc/scripts/htx.d status'
        shutdown_cmd = '/usr/lpp/htx/etc/scripts/htxd_shutdown'

        daemon_state = process.system_output(status_cmd, ignore_status=True,
                                             shell=True, sudo=True).decode("utf-8")

        if 'running' in daemon_state:
            process.system(shutdown_cmd, ignore_status=True,
                           shell=True, sudo=True)

        # Shutdown peer daemon for network tests
        if self.test_type == 'network':
            try:
                output = self.session.cmd(status_cmd)
                if 'running' in output.stdout.decode("utf-8"):
                    self.session.cmd(shutdown_cmd)
            except Exception as e:
                self.log.warning(
                    "Unable to shutdown peer HTX daemon: %s", str(e))

    def _restore_network_config(self):
        """
        Restore network configuration after network test
        """
        self.log.info("Restoring network configuration")

        # Restore host interfaces
        for interface in self.host_intfs:
            networkinterface = NetworkInterface(interface, self.localhost)
            detected_distro = distro.detect()

            if detected_distro.name in ['rhel', 'fedora', 'redhat']:
                if detected_distro.version >= "9":
                    networkinterface.nm_flush_ipaddr()
                else:
                    networkinterface.flush_ipaddr()
            elif detected_distro.name == "SuSE":
                if detected_distro.version >= 16:
                    networkinterface.nm_flush_ipaddr()
                else:
                    networkinterface.flush_ipaddr()

            networkinterface.bring_up()

        # Restore peer interfaces
        for interface in self.peer_intfs:
            peer_networkinterface = NetworkInterface(
                interface, self.remotehost)
            detected_distro = distro.detect()

            if detected_distro.name in ['rhel', 'fedora', 'redhat']:
                if detected_distro.version >= "9":
                    peer_networkinterface.nm_flush_ipaddr()
                else:
                    peer_networkinterface.flush_ipaddr()
            elif detected_distro.name == "SuSE":
                if detected_distro.version >= 16:
                    peer_networkinterface.nm_flush_ipaddr()
                else:
                    peer_networkinterface.flush_ipaddr()

            peer_networkinterface.bring_up()

    # Storage-specific helper methods

    def _is_block_device_in_mdt(self):
        """
        Verify if block devices are present in MDT file
        """
        self.log.info("Verifying devices in MDT: %s", self.mdt_file)
        cmd = "htxcmdline -query -mdt %s" % self.mdt_file
        output = process.system_output(cmd).decode("utf-8")

        missing_devices = []
        device_str = self.block_device if isinstance(
            self.block_device, str) else " ".join(self.block_device)
        for dev in device_str.split():
            if dev not in output:
                missing_devices.append(dev)

    # Safety helper methods

    def _get_root_disk(self):
        """
        Get the root/boot disk device name
        """
        try:
            # Get the device containing /boot or / filesystem
            cmd = "df /boot 2>/dev/null || df /"
            output = process.system_output(
                cmd, shell=True, ignore_status=True).decode("utf-8")

            for line in output.split('\n'):
                if line.startswith('/dev/'):
                    device = line.split()[0]
                    # Extract base device name (remove partition number)
                    import re
                    base_device = re.sub(
                        r'[0-9]+$', '', os.path.basename(device))
                    # For nvme devices
                    base_device = re.sub(r'p[0-9]+$', '', base_device)
                    return base_device
        except Exception as e:
            self.log.warning("Could not determine root disk: %s", str(e))

        return None

    def _is_root_disk(self, device):
        """
        Check if the given device is the root/boot disk
        """
        if not self.root_disk:
            return False

        # Remove any partition numbers for comparison
        import re
        device_base = re.sub(r'[0-9]+$', '', device)
        device_base = re.sub(r'p[0-9]+$', '', device_base)

        return device_base == self.root_disk

    def _get_default_network_interface(self):
        """
        Get the default network interface (used for management/SSH)
        """
        try:
            # Get the interface used for default route
            cmd = "ip route show default | awk '/default/ {print $5}' | head -1"
            output = process.system_output(
                cmd, shell=True, ignore_status=True).decode("utf-8").strip()

            if output:
                self.log.info("Default network interface detected: %s", output)
                return output
        except Exception as e:
            self.log.warning(
                "Could not determine default network interface: %s", str(e))

        return None

    def _remove_default_devices_from_bpt(self):
        """
        Remove root disk and default network interface from HTX bpt file
        This prevents HTX from testing critical system devices
        """
        bpt_file = "/tmp/bpt"

        if not os.path.exists(bpt_file):
            self.log.info("BPT file not found, skipping device removal")
            return

        try:
            with open(bpt_file, 'r') as f:
                lines = f.readlines()

            modified_lines = []
            removed_devices = []

            for line in lines:
                skip_line = False

                # Check for root disk in storage tests
                if self.test_type == 'storage' and self.root_disk:
                    if self.root_disk in line or f"/dev/{self.root_disk}" in line:
                        skip_line = True
                        removed_devices.append(f"root disk: {self.root_disk}")

                # Check for default network interface in network tests
                if self.test_type == 'network':
                    default_intf = self._get_default_network_interface()
                    if default_intf and default_intf in line:
                        skip_line = True
                        removed_devices.append(
                            f"default interface: {default_intf}")

                if not skip_line:
                    modified_lines.append(line)

            # Write back modified bpt file
            if removed_devices:
                with open(bpt_file, 'w') as f:
                    f.writelines(modified_lines)
                self.log.info("Removed critical devices from bpt file: %s",
                              ", ".join(removed_devices))
            else:
                self.log.info("No critical devices found in bpt file")

        except Exception as e:
            self.log.warning("Could not modify bpt file: %s", str(e))

    def _suspend_all_block_devices(self):
        """
        Suspend all block devices in MDT
        """
        self.log.info("Suspending all devices")
        cmd = "htxcmdline -suspend all -mdt %s" % self.mdt_file
        process.system(cmd, ignore_status=True)

    def _is_block_device_active(self):
        """
        Check if block devices are active
        """
        self.log.info("Checking device activation status")
        cmd = "htxcmdline -query %s -mdt %s" % (
            self.block_device, self.mdt_file)
        output = process.system_output(cmd).decode("utf-8").split("\n")

        device_str = self.block_device if isinstance(
            self.block_device, str) else " ".join(self.block_device)
        device_list = device_str.split()
        active_devices = []

        for line in output:
            for dev in device_list:
                if dev in line and "ACTIVE" in line:
                    active_devices.append(dev)

        non_active = list(set(device_list) - set(active_devices))
        if non_active:
            self.log.error("Inactive devices: %s", non_active)
            return False

        self.log.info("All devices are active")
        return True

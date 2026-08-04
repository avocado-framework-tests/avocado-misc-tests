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
# Copyright: 2024 IBM
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

"""
Spyre HTX Test

This test runs HTX (Hardware Test eXecutive) stress testing specifically
for Spyre AIU (AI Unit) devices using container-based exercisers.

The test supports multiple Spyre-specific MDT files:
- mdt.container_spyre_test: Basic Spyre exerciser test
- mdt.container_spyre_stress_test: High stress & power consumption mode with EEH testing
- mdt.container_spyre_eeh_test: Dedicated EEH testing
- mdt.container_spyre_bu_test: Spyre with other exercisers (Memory, CPU/FPU)

Test Flow:
1. Setup HTX environment
2. Run hxespyre.config configuration
3. Execute hcl -setup_container spyre to create container image and MDTs
4. Run selected MDT file
5. Monitor for errors
6. Shutdown and cleanup
"""

import os
import time
import shutil
import re

from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import build, process, archive, distro


class SpyreHtxTest(Test):
    """
    HTX stress test for Spyre AIU devices using container-based exercisers.
    
    This test exercises Spyre AI accelerator hardware using HTX container
    exercisers to validate hardware stability, performance, and reliability.
    """

    # Supported Spyre MDT files
    SPYRE_MDT_FILES = {
        'test': 'mdt.container_spyre_test',
        'stress': 'mdt.container_spyre_stress_test',
        'eeh': 'mdt.container_spyre_eeh_test',
        'bu': 'mdt.container_spyre_bu_test',
        'granite': 'mdt.container_spyre_test'  # Uses same MDT as test
    }

    def install_latest_htx_rpm(self):
        """
        Search for the latest HTX version for the intended distro and install it.
        """
        distro_pattern = "%s%s" % (
            self.dist_name, self.detected_distro.version)
        temp_string = process.getoutput(
            "curl --silent -k %s" % (self.rpm_link),
            verbose=False, shell=True, ignore_status=True)
        matching_htx_versions = re.findall(
            r"(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*", str(temp_string))
        distro_specific_htx_versions = [
            htx_rpm for htx_rpm in matching_htx_versions
            if distro_pattern in htx_rpm]
        distro_specific_htx_versions.sort(reverse=True)
        
        if not distro_specific_htx_versions:
            self.cancel("No HTX RPM found for %s" % distro_pattern)
            
        tmp_htx_rpm = distro_specific_htx_versions[0]
        self.latest_htx_rpm = tmp_htx_rpm
        tmp_dir = "/tmp/" + tmp_htx_rpm
        cmd = "curl -k %s/%s -o %s" % (self.rpm_link, self.latest_htx_rpm,
                                       tmp_dir)
        if process.system(cmd, shell=True, ignore_status=True):
            self.cancel("HTX RPM download failed")
        cmd = "rpm -ivh --nodeps %s" % (tmp_dir)
        if process.system(cmd, shell=True, ignore_status=True):
            self.cancel("HTX RPM installation failed")
        cmd = "rm -rf %s" % (tmp_dir)
        process.run(cmd)
        self.log.info("✓ HTX RPM installed: %s", self.latest_htx_rpm)

    def setUp(self):
        """
        Setup HTX environment for Spyre container testing.
        """
        self.log.info("=" * 80)
        self.log.info("Spyre HTX Container Test - Setup")
        self.log.info("=" * 80)

        # Platform validation
        if 'ppc64' not in distro.detect().arch:
            self.cancel("Supported only on Power Architecture")

        # Get test parameters from YAML
        test_type = self.params.get('test_type', default='test')
        if test_type not in self.SPYRE_MDT_FILES:
            self.cancel("Invalid test_type. Must be one of: %s" % 
                       ', '.join(self.SPYRE_MDT_FILES.keys()))
        
        self.mdt_file = self.SPYRE_MDT_FILES[test_type]
        self.test_type = test_type
        
        self.time_limit = int(self.params.get('time_limit', default=2))
        self.time_unit = self.params.get('time_unit', default='h')
        self.run_type = self.params.get('run_type', default='rpm')
        
        # Convert time to seconds
        if self.time_unit == 'm':
            self.time_limit = self.time_limit * 60
        elif self.time_unit == 'h':
            self.time_limit = self.time_limit * 3600
        else:
            self.cancel("Time unit must be 'm' (minutes) or 'h' (hours)")

        self.log.info("Test Type: %s", test_type)
        self.log.info("MDT File: %s", self.mdt_file)
        self.log.info("Test Duration: %d seconds (%d %s)",
                     self.time_limit,
                     int(self.params.get('time_limit', default=2)),
                     self.time_unit)

        # Setup HTX only at the start phase of test
        if str(self.name.name).endswith('test_start'):
            self.setup_htx()
            self.setup_spyre_container()

        self.log.info("✓ Setup completed successfully")

    def setup_htx(self):
        """
        Install and configure HTX.
        """
        self.log.info("=" * 80)
        self.log.info("Setting up HTX")
        self.log.info("=" * 80)

        self.detected_distro = distro.detect()
        
        # Install required packages
        packages = ['git', 'gcc', 'make', 'ndctl', 'podman']
        if self.detected_distro.name in ['centos', 'fedora', 'rhel']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif self.detected_distro.name == "Ubuntu":
            packages.extend(['libncurses5', 'g++',
                           'ncurses-dev', 'libncurses-dev'])
        elif self.detected_distro.name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            self.cancel("Test not supported on %s" % self.detected_distro.name)

        self.log.info("Installing required packages: %s", ", ".join(packages))
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

        self.log.info("✓ HTX setup completed successfully")

    def _install_htx_from_git(self):
        """
        Install HTX from GitHub source.
        """
        self.log.info("Installing HTX from Git source")
        
        if self.detected_distro.name == 'rhel' and \
                self.detected_distro.version <= "9":
            self.cancel("Git installation not supported on %s_%s"
                       % (self.detected_distro.name,
                          self.detected_distro.version))
        
        url = "https://github.com/open-power/HTX/archive/master.zip"
        tarball = self.fetch_asset("htx.zip", locations=[url], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        htx_path = os.path.join(self.teststmpdir, "HTX-master")
        os.chdir(htx_path)

        # Remove unsupported exercisers
        exercisers = ["hxecapi_afu_dir", "hxedapl", "hxecapi", "hxeocapi"]
        for exerciser in exercisers:
            process.run("sed -i 's/%s//g' %s/bin/Makefile" % (exerciser,
                                                              htx_path))

        # Build and install HTX
        build.make(htx_path, extra_args='all')
        build.make(htx_path, extra_args='tar')
        process.run('tar --touch -xvzf htx_package.tar.gz')
        os.chdir('htx_package')
        if process.system('./installer.sh -f'):
            self.fail("HTX installation failed - check job.log")

    def _install_htx_from_rpm(self):
        """
        Install HTX from RPM package.
        """
        self.log.info("Installing HTX from RPM")
        
        self.dist_name = self.detected_distro.name.lower()
        if self.dist_name == 'suse':
            self.dist_name = 'sles'
        
        rpm_check = "htx%s%s" % (
            self.dist_name, self.detected_distro.version)
        skip_install = False
        
        # Check if HTX is already installed
        ins_htx = process.system_output(
            'rpm -qa | grep htx', shell=True, ignore_status=True).decode()

        smm = SoftwareManager()
        if ins_htx:
            if not smm.check_installed(rpm_check):
                self.log.info("Removing existing HTX RPM")
                process.system('rpm -e %s' %
                             ins_htx, shell=True, ignore_status=True)
                if os.path.exists('/usr/lpp/htx'):
                    shutil.rmtree('/usr/lpp/htx')
            else:
                self.log.info("Using existing HTX installation")
                skip_install = True
        
        if not skip_install:
            self.rpm_link = self.params.get('htx_rpm_link', default=None)
            if self.rpm_link:
                self.install_latest_htx_rpm()
            else:
                self.cancel("HTX RPM link is required for RPM installation")

    def _start_htx_daemon(self):
        """
        Start the HTX daemon.
        """
        self.log.info("Starting HTX daemon")
        
        # Kill existing HTXD process if running
        htxd_pid = process.getoutput("pgrep -f htxd")
        if htxd_pid:
            self.log.info(
                "HTXD already running with PID: %s. Killing it.", htxd_pid)
            process.run("pkill -f htxd", ignore_status=True)
            time.sleep(10)
        
        process.run('/usr/lpp/htx/etc/scripts/htxd_run')
        self.log.info("✓ HTX daemon started")

    def _get_spyre_pci_buses(self):
        """
        Get Spyre PCI bus addresses using lsslot command.
        
        Command: lsslot -c pci | grep WZS01YY | cut -d' ' -f16
        
        :return: List of PCI bus addresses
        """
        self.log.info("Detecting Spyre PCI bus addresses...")
        
        try:
            cmd = "lsslot -c pci | grep WZS01YY | cut -d' ' -f16"
            result = process.run(cmd, shell=True, ignore_status=True)
            
            if result.exit_status != 0:
                self.log.warning("Failed to detect Spyre PCI buses")
                return []
            
            pci_buses = [bus.strip() for bus in result.stdout_text.strip().split('\n') if bus.strip()]
            
            if pci_buses:
                self.log.info("✓ Detected %d Spyre PCI bus(es): %s",
                             len(pci_buses), ', '.join(pci_buses))
            else:
                self.log.warning("No Spyre PCI buses detected")
            
            return pci_buses
            
        except Exception as ex:
            self.log.error("Exception detecting PCI buses: %s", ex)
            return []

    def _configure_spyre_power_config(self, pci_buses):
        """
        Add PCI bus addresses to spyre_power_config.txt file.
        
        :param pci_buses: List of PCI bus addresses
        """
        if not pci_buses:
            self.log.warning("No PCI buses to configure")
            return
        
        config_file = "/usr/lpp/htx/setup/spyre_power_config.txt"
        self.log.info("Configuring Spyre power config: %s", config_file)
        
        try:
            # Create or overwrite the config file with PCI buses
            with open(config_file, 'w') as f:
                for pci_bus in pci_buses:
                    f.write("%s\n" % pci_bus)
            
            self.log.info("✓ Spyre power config updated with %d PCI bus(es)", len(pci_buses))
            
            # Display the config
            with open(config_file, 'r') as f:
                content = f.read()
                self.log.info("Config content:\n%s", content)
                
        except Exception as ex:
            self.log.error("Failed to configure spyre_power_config.txt: %s", ex)

    def _download_granite_model(self):
        """
        Download Granite model package from GSA server.
        
        Downloads to /tmp and requires GSA credentials (user ID and password).
        """
        self.log.info("=" * 80)
        self.log.info("Downloading Granite Model Package")
        self.log.info("=" * 80)
        
        gsa_user = self.params.get('gsa_user', default=None)
        gsa_password = self.params.get('gsa_password', default=None)
        model_url = self.params.get('model_url', default=None)
        
        if not gsa_user or not gsa_password:
            self.log.warning("GSA credentials not provided (gsa_user and/or gsa_password missing)")
            self.log.warning("Skipping Granite model download")
            return False
        
        if not model_url:
            self.log.error("model_url not provided in YAML configuration")
            self.log.error("Please add model_url parameter to your YAML file")
            return False
        
        download_path = "/tmp"
        
        self.log.info("Downloading from: %s", model_url)
        self.log.info("Download path: %s", download_path)
        self.log.info("GSA User: %s", gsa_user)
        self.log.warning("This may take several hours depending on network speed")
        
        # Use wget with user and password
        cmd = "wget -P %s %s --user=%s --password='%s'" % (
            download_path, model_url, gsa_user, gsa_password)
        
        try:
            # Don't log the command to avoid exposing password
            self.log.info("Starting download...")
            result = process.run(cmd, shell=True, ignore_status=True, timeout=14400)  # 4 hour timeout
            
            if result.exit_status != 0:
                self.log.error("Failed to download Granite model")
                self.log.error("Exit status: %d", result.exit_status)
                # Don't log stderr as it might contain password
                return False
            
            self.log.info("✓ Granite model downloaded successfully")
            return True
            
        except Exception as ex:
            self.log.error("Exception downloading Granite model: %s", ex)
            return False

    def _configure_eeh_testing(self):
        """
        Configure HTX environment variables for EEH testing.
        
        Sets:
        - HTXEEH: Enable (1) or disable (0) EEH testing
        - HTXEEHRETRIES: Number of error injections (default: 5)
        
        Between two error injects there should be at least 5s gap for card recovery.
        """
        enable_eeh = self.params.get('enable_eeh', default='0')
        eeh_retries = self.params.get('eeh_retries', default='5')
        
        if enable_eeh == '1':
            self.log.info("=" * 80)
            self.log.info("Configuring EEH Testing")
            self.log.info("=" * 80)
            
            # Set HTXEEH
            self.log.info("Enabling EEH testing...")
            cmd = "hcl -set_htx_env HTXEEH 1"
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status != 0:
                self.log.error("Failed to set HTXEEH")
                return False
            
            # Verify HTXEEH
            cmd = "hcl -get_htx_env HTXEEH"
            result = process.run(cmd, shell=True, ignore_status=True)
            self.log.info("HTXEEH value: %s", result.stdout_text.strip())
            
            # Set HTXEEHRETRIES
            self.log.info("Setting EEH retries to %s...", eeh_retries)
            cmd = "hcl -set_htx_env HTXEEHRETRIES %s" % eeh_retries
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status != 0:
                self.log.error("Failed to set HTXEEHRETRIES")
                return False
            
            # Verify HTXEEHRETRIES
            cmd = "hcl -get_htx_env HTXEEHRETRIES"
            result = process.run(cmd, shell=True, ignore_status=True)
            self.log.info("HTXEEHRETRIES value: %s", result.stdout_text.strip())
            
            self.log.info("✓ EEH testing configured successfully")
            self.log.info("Note: 5s gap between error injections for card recovery")
            return True
        else:
            self.log.info("EEH testing disabled (enable_eeh=0)")
            return True

    def _list_created_mdts(self):
        """
        List all created MDT files to verify setup.
        
        Expected MDTs:
        - mdt.container_spyre_test
        - mdt.container_spyre_stress_test
        - mdt.container_spyre_bu_test
        - mdt.container_spyre_eeh_test (if EEH enabled)
        """
        self.log.info("Listing created MDT files...")
        
        cmd = "hcl -listmdt"
        result = process.run(cmd, shell=True, ignore_status=True)
        
        if result.exit_status == 0:
            self.log.info("Available MDT files:\n%s", result.stdout_text)
            
            # Check for expected MDTs
            expected_mdts = [
                'mdt.container_spyre_test',
                'mdt.container_spyre_stress_test',
                'mdt.container_spyre_bu_test'
            ]
            
            for mdt in expected_mdts:
                if mdt in result.stdout_text:
                    self.log.info("✓ Found: %s", mdt)
                else:
                    self.log.warning("✗ Missing: %s", mdt)
        else:
            self.log.error("Failed to list MDT files")

    def _collect_container_logs(self):
        """
        Collect logs from Spyre containers to host.
        
        Copies logs from each container:
        /tmp/htx/hxespyre/spyre0/hxespyre.log -> /tmp/spyre_ctr<N>_hxespyre.log
        """
        self.log.info("=" * 80)
        self.log.info("Collecting Container Logs")
        self.log.info("=" * 80)
        
        # Get list of running containers
        cmd = "podman ps --format '{{.Names}}' | grep spyre_ctr"
        result = process.run(cmd, shell=True, ignore_status=True)
        
        if result.exit_status != 0:
            self.log.warning("No Spyre containers found")
            return
        
        containers = [c.strip() for c in result.stdout_text.strip().split('\n') if c.strip()]
        
        for container in containers:
            try:
                self.log.info("Collecting logs from container: %s", container)
                
                # Extract container number (e.g., spyre_ctr0 -> 0)
                container_num = container.replace('spyre_ctr', '')
                
                source_log = "/tmp/htx/hxespyre/spyre0/hxespyre.log"
                dest_log = "/tmp/%s_hxespyre.log" % container
                
                cmd = "podman cp %s:%s %s" % (container, source_log, dest_log)
                result = process.run(cmd, shell=True, ignore_status=True)
                
                if result.exit_status == 0:
                    self.log.info("✓ Log copied to: %s", dest_log)
                else:
                    self.log.warning("Failed to copy log from %s", container)
                    
            except Exception as ex:
                self.log.error("Exception collecting logs from %s: %s", container, ex)

    def _get_htx_runtime(self):
        """
        Get overall HTX test duration.
        
        :return: Runtime string
        """
        try:
            cmd = "hcl -get_run_time"
            result = process.run(cmd, shell=True, ignore_status=True)
            
            if result.exit_status == 0:
                runtime = result.stdout_text.strip()
                self.log.info("HTX Runtime: %s", runtime)
                return runtime
            else:
                self.log.warning("Failed to get HTX runtime")
                return "Unknown"
                
        except Exception as ex:
            self.log.error("Exception getting HTX runtime: %s", ex)
            return "Unknown"

    def setup_spyre_container(self):
        """
        Setup Spyre container environment and create Spyre MDT files.
        
        This runs:
        1. Detect Spyre PCI buses
        2. Configure spyre_power_config.txt
        3. Download Granite model (if granite test type)
        4. Run hxespyre.config
        5. Configure EEH testing (if enabled)
        6. Setup container and create MDTs
        7. Verify MDT creation
        """
        self.log.info("=" * 80)
        self.log.info("Setting up Spyre Container Environment")
        self.log.info("=" * 80)

        # Step 1: Detect and configure PCI buses
        pci_buses = self._get_spyre_pci_buses()
        if pci_buses:
            self._configure_spyre_power_config(pci_buses)
        else:
            self.log.warning("No PCI buses detected, continuing anyway...")

        # Step 2: Download Granite model if needed
        if self.test_type == 'granite':
            if not self._download_granite_model():
                self.log.warning("Granite model download failed, continuing anyway...")

        # Step 3: Run hxespyre.config
        config_script = "/usr/lpp/htx/setup/hxespyre.config"
        if os.path.exists(config_script):
            if self.test_type == 'granite':
                self.log.info("Running hxespyre.config with granite argument...")
                cmd = "cd /usr/lpp/htx/setup/ && ./hxespyre.config granite"
            else:
                self.log.info("Running hxespyre.config...")
                cmd = config_script
            
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status != 0:
                self.log.warning("hxespyre.config returned non-zero status: %d",
                               result.exit_status)
                self.log.warning("Output: %s", result.stdout_text)
            else:
                self.log.info("✓ hxespyre.config completed successfully")
        else:
            self.log.warning("hxespyre.config not found at %s", config_script)

        # Step 4: Configure EEH testing if enabled
        self._configure_eeh_testing()

        # Step 5: Setup Spyre container and create MDTs
        self.log.info("Creating Spyre container image and MDT files...")
        cmd = "hcl -setup_container spyre"
        result = process.run(cmd, shell=True, ignore_status=True, timeout=600)
        
        if result.exit_status != 0:
            self.log.error("Failed to setup Spyre container")
            self.log.error("Output: %s", result.stdout_text)
            self.log.error("Error: %s", result.stderr_text)
            self.fail("Spyre container setup failed")
        
        self.log.info("✓ Spyre container setup completed successfully")
        
        # Step 6: List and verify created MDTs
        self._list_created_mdts()
        
        # Verify specific MDT file exists
        mdt_path = "/usr/lpp/htx/mdt/%s" % self.mdt_file
        if not os.path.exists(mdt_path):
            self.fail("MDT file not created: %s" % mdt_path)
        
        self.log.info("✓ MDT file verified: %s", self.mdt_file)

    def test_start(self):
        """
        Start HTX Spyre container test.
        """
        self.log.info("=" * 80)
        self.log.info("Starting Spyre HTX Container Test")
        self.log.info("Test Type: %s", self.test_type)
        self.log.info("MDT File: %s", self.mdt_file)
        self.log.info("=" * 80)

        # Run HTX with the selected MDT file
        self.log.info("Running: hcl -run -mdt %s", self.mdt_file)
        cmd = "hcl -run -mdt %s" % self.mdt_file
        result = process.run(cmd, shell=True, ignore_status=True)
        
        if result.exit_status != 0:
            self.log.error("Failed to start HTX test")
            self.log.error("Output: %s", result.stdout_text)
            self.fail("HTX test start failed")

        self.log.info("✓ HTX Spyre test started successfully")

    def test_check(self):
        """
        Monitor HTX execution and check for errors.
        """
        self.log.info("=" * 80)
        self.log.info("Monitoring HTX Spyre Test Execution")
        self.log.info("=" * 80)

        check_interval = 60  # Check every 60 seconds
        iterations = self.time_limit // check_interval
        
        self.log.info("Test duration: %d seconds", self.time_limit)
        self.log.info("Check interval: %d seconds", check_interval)
        self.log.info("Total checks: %d", iterations)

        for iteration in range(iterations):
            elapsed_time = (iteration + 1) * check_interval
            remaining_time = self.time_limit - elapsed_time
            
            self.log.info("")
            self.log.info("-" * 80)
            self.log.info("Check %d/%d - Elapsed: %ds, Remaining: %ds",
                         iteration + 1, iterations, elapsed_time, remaining_time)
            self.log.info("-" * 80)

            # Get HTX error logs
            self.log.info("Checking HTX error logs...")
            process.system('htxcmdline -geterrlog', ignore_status=True)
            
            # Check if error log has any errors
            if os.path.exists('/tmp/htxerr') and os.stat('/tmp/htxerr').st_size != 0:
                self.log.error("HTX errors detected!")
                try:
                    with open('/tmp/htxerr', 'r') as f:
                        error_content = f.read()
                        self.log.error("Error log content:\n%s", error_content)
                except Exception as ex:
                    self.log.error("Failed to read error log: %s", ex)
                self.fail("HTX Spyre test failed - check error logs for details")

            # Query HTX status
            self.log.info("Querying HTX status...")
            cmd = 'htxcmdline -query -mdt %s' % self.mdt_file
            result = process.run(cmd, ignore_status=True)
            self.log.info("HTX Status:\n%s", result.stdout_text)
            
            # Query container status using hcl -query
            self.log.info("Querying container status...")
            cmd = 'hcl -query'
            result = process.run(cmd, shell=True, ignore_status=True)
            self.log.info("Container Status:\n%s", result.stdout_text)
            
            # Query specific container execution cycles (example: spyre_ctr0)
            cmd = 'hcl -query spyre_ctr0'
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status == 0:
                self.log.info("spyre_ctr0 cycles:\n%s", result.stdout_text)

            # Sleep until next check
            if iteration < iterations - 1:
                self.log.info("Sleeping for %d seconds...", check_interval)
                time.sleep(check_interval)

        self.log.info("")
        self.log.info("=" * 80)
        self.log.info("✓ HTX Spyre test completed successfully - No errors detected")
        
        # Get final runtime
        runtime = self._get_htx_runtime()
        self.log.info("Total HTX Runtime: %s", runtime)
        self.log.info("=" * 80)

    def test_stop(self):
        """
        Stop HTX test and shutdown HTX daemon.
        """
        self.stop_htx()

    def stop_htx(self):
        """
        Stop the HTX run and shutdown daemon.
        """
        self.log.info("=" * 80)
        self.log.info("Stopping HTX Spyre Test")
        self.log.info("=" * 80)

        # Collect container logs before shutdown
        self._collect_container_logs()
        
        # Shutdown MDT file
        self.log.info("Shutting down MDT file: %s", self.mdt_file)
        cmd = 'hcl -shutdown'
        process.system(cmd, timeout=120, ignore_status=True)
        
        # Alternative: Use htxcmdline for specific MDT
        # cmd = 'htxcmdline -shutdown -mdt %s' % self.mdt_file
        # process.system(cmd, timeout=120, ignore_status=True)

        # Shutdown HTX daemon
        if self.run_type == 'rpm':
            self.log.info("Shutting down HTX daemon (RPM mode)")
            process.system(
                '/usr/lpp/htx/etc/scripts/htxd_shutdown', ignore_status=True)
            # Unmount any HTX pmem mounts
            process.system('umount /htx_pmem*', shell=True, ignore_status=True)
        else:
            self.log.info("Shutting down HTX daemon (Git mode)")
            cmd = '/usr/lpp/htx/etc/scripts/htx.d status'
            daemon_state = process.system_output(cmd, ignore_status=True)
            if daemon_state and daemon_state.decode().split(" ")[-1] == 'running':
                process.system('/usr/lpp/htx/etc/scripts/htxd_shutdown')
        
        # Reset container mode to go back to HTX normal mode
        self.log.info("Resetting container mode...")
        cmd = 'hcl -setup_container reset'
        process.system(cmd, shell=True, ignore_status=True)

        self.log.info("✓ HTX stopped successfully")

    def tearDown(self):
        """
        Cleanup after test execution.
        """
        self.log.info("=" * 80)
        self.log.info("Spyre HTX Test - Teardown")
        self.log.info("=" * 80)

        # Display final error log if exists
        if os.path.exists('/tmp/htxerr'):
            try:
                with open('/tmp/htxerr', 'r') as f:
                    error_content = f.read()
                    if error_content.strip():
                        self.log.warning("Final HTX error log:\n%s", error_content)
            except Exception as ex:
                self.log.warning("Failed to read final error log: %s", ex)

        self.log.info("✓ Teardown completed")

# Made with Bob

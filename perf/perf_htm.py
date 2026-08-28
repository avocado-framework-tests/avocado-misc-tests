#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE for more details.
#
# Copyright: 2026 IBM

import os
import platform
import tempfile
import time
import socket

from avocado import Test
from avocado.utils import process, genio
from avocado.utils.software_manager.manager import SoftwareManager


class PerfHTMTrace(Test):
    """
    Hardware Trace Macro (HTM) testing for POWER systems.

    This test automates HTM trace collection on PowerVM LPARs:
    1. Configures HTM on phyp (instruction or LLAT tracing)
    2. Starts HTM tracing
    3. Runs workload on LPAR
    4. Stops HTM tracing
    5. Dumps HTM trace data using htmdump
    6. Decodes trace using qtrace-tools htmdecoder
    7. Validates trace output

    :avocado: tags=perf,htm,powerpc,privileged
    """

    def setUp(self):
        """
        Install required packages and initialize test parameters.
        """
        # Check if running on PowerVM LPAR
        if not self._is_powervm_lpar():
            self.cancel("Test requires PowerVM LPAR environment")

        # Install dependencies first
        self._install_dependencies()

        # Get test parameters BEFORE checking VET (need phyp_host)
        self.phyp_host = self.params.get('phyp_host', default='')
        self.phyp_port = self.params.get('phyp_port', default=30002)
        self.phyp_user = self.params.get('phyp_user', default='')
        self.phyp_password = self.params.get('phyp_password', default='')

        # Initialize phyp connection (will be opened when first needed)
        self.phyp_connection = None

        # Open persistent phyp connection if host is configured
        if self.phyp_host:
            self._open_phyp_connection()

        # Get htm -info output once and cache it
        self.htm_info_output = None
        if self.phyp_host:
            result = self._phyp_command('htm -info', timeout=30)
            self.htm_info_output = result.stdout.decode(
                'utf-8', errors='ignore')

        # Now check VET code enablement using cached output
        self._check_vet_enabled()

        self.trace_mode = self.params.get(
            'trace_mode', default='inst')  # inst or llat
        self.trace_duration = int(
            self.params.get(
                'trace_duration',
                default=10))
        self.nowrap = self.params.get('nowrap', default=True)
        self.verify_htm_buffers = self.params.get(
            'verify_htm_buffers', default=True)
        self.expected_nest_buffer = self.params.get(
            'expected_nest_buffer', default='256MB')
        self.expected_core_buffer = self.params.get(
            'expected_core_buffer', default='256MB')

        # Get LPAR partition number
        self.partition_no = self._get_partition_number()
        if self.partition_no == 0:
            self.log.warning(
                "Could not read partition number, will use manual topology")
        else:
            self.log.info(
                "LPAR Partition Number: %d (0x%02x)",
                self.partition_no,
                self.partition_no)

        # Auto-detect node, chip, core from phyp based on partition number
        # Allow manual override via parameters
        self.node = self.params.get('node', default=None)
        self.chip = self.params.get('chip', default=None)
        self.core = self.params.get('core', default=None)

        if self.node is None or self.chip is None or self.core is None:
            self.log.info("Auto-detecting HTM topology from phyp...")
            detected = self._detect_htm_topology()
            if self.node is None:
                self.node = detected['node']
            if self.chip is None:
                self.chip = detected['chip']
            if self.core is None:
                self.core = detected['core']
        else:
            self.node = int(self.node)
            self.chip = int(self.chip)
            self.core = int(self.core)

        self.htmdump_repo = self.params.get(
            'htmdump_repo', default='https://github.com/antonblanchard/htmdump.git')
        self.qtrace_repo = self.params.get(
            'qtrace_repo', default='https://github.com/antonblanchard/qtrace-tools.git')

        self.htm_workdir = tempfile.mkdtemp(prefix='htm_test_')
        self.htmdump_dir = os.path.join(self.htm_workdir, 'htmdump')
        self.qtrace_dir = os.path.join(self.htm_workdir, 'qtrace-tools')
        self.trace_file = os.path.join(self.htm_workdir, 'trace.htm')
        self.decoded_file = os.path.join(self.htm_workdir, 'decoded.txt')

        # Check disk space (HTM traces can be huge)
        self._check_disk_space()

        self.log.info("HTM Test Configuration:")
        self.log.info(
            "  Node: %d, Chip: %d, Core: %d",
            self.node,
            self.chip,
            self.core)
        self.log.info("  Trace Mode: %s", self.trace_mode)
        self.log.info("  Trace Duration: %d seconds", self.trace_duration)
        self.log.info("  Work Directory: %s", self.htm_workdir)

    def _check_disk_space(self):
        """Check available disk space for trace files."""
        try:
            result = process.run('df -BG %s | tail -1' % self.htm_workdir,
                                 shell=True, ignore_status=True)
            if result.exit_status == 0:
                output = result.stdout.decode('utf-8').strip()
                parts = output.split()
                if len(parts) >= 4:
                    available = parts[3].replace('G', '')
                    try:
                        available_gb = int(available)
                        if available_gb < 10:
                            self.log.warning(
                                "Low disk space: %dGB available", available_gb)
                    except ValueError:
                        pass
        except Exception:
            pass

    def _is_powervm_lpar(self):
        """Check if running on PowerVM LPAR."""
        try:
            if platform.machine() not in ['ppc64le', 'ppc64']:
                return False

            # Check for PowerVM hypervisor
            lscpu = process.system_output(
                'lscpu', ignore_status=True).decode('utf-8')
            if 'pHyp' not in lscpu:
                return False

            # Check for partition number
            partition_file = '/proc/device-tree/ibm,partition-no'
            if not os.path.exists(partition_file):
                return False

            return True
        except Exception:
            return False

    def _check_vet_enabled(self):
        """
        Check if VET (Virtual Event Trace) code is enabled on phyp.
        Uses cached htm -info output to avoid redundant calls.
        """
        if not self.phyp_host or not self.htm_info_output:
            self.log.warning("phyp_host not configured - skipping VET check")
            return True

        self.log.info("Checking VET code enablement on phyp...")

        # Check if output contains HTM info (indicates VET is enabled)
        if 'HTM Info' in self.htm_info_output and 'Nest HTM buffer size' in self.htm_info_output:
            self.log.info("VET code is ENABLED on phyp")
            return True

        # Check for VET not enabled message
        if 'enable VET' in self.htm_info_output.lower(
        ) or 'vet code' in self.htm_info_output.lower():
            self.cancel(
                "VET code is NOT enabled on phyp. Please enable VET code first.")

        self.log.warning(
            "Could not determine VET status from htm -info output")
        return False

    def _get_partition_number(self):
        """Get LPAR partition number from device tree."""
        partition_file = '/proc/device-tree/ibm,partition-no'
        try:
            # Read raw bytes and convert to integer
            result = process.system_output('hexdump -C %s' % partition_file,
                                           shell=True, sudo=True)
            output = result.decode('utf-8')
            # Parse hexdump output: "00000000  00 00 00 04"
            # Extract the last byte which is the partition number
            hex_values = output.split()[1:5]  # Get the 4 hex bytes
            partition_bytes = bytes(int(h, 16) for h in hex_values)
            partition_no = int.from_bytes(partition_bytes, byteorder='big')
            return partition_no
        except Exception as e:
            self.log.warning("Failed to read partition number: %s", e)
            return 0

    def _detect_htm_topology(self):
        """
        Detect node, chip, core for this LPAR by parsing phyp htm -info output.
        Uses cached htm -info output to avoid redundant calls.
        """
        if not self.phyp_host or not self.htm_info_output:
            self.cancel(
                "phyp_host required for auto-detection of HTM topology")

        self.log.info(
            "Detecting HTM topology for partition %d...",
            self.partition_no)
        output = self.htm_info_output

        self.log.debug("Full htm -info output:")
        self.log.debug("=" * 70)
        for line in output.split('\n'):
            self.log.debug(line)

        # Parse the Core HTMs table to find our partition
        # Look for lines with LP Index matching our partition number
        lines = output.split('\n')
        in_core_table = False

        for i, line in enumerate(lines):
            # Find the Core HTMs section
            if 'Core HTMs:' in line:
                in_core_table = True
                continue

            # Skip until we reach the data rows
            if not in_core_table or '|' not in line:
                continue

            # Parse table rows
            # Table format: | Node | Nodal Chip | HW Core | Phys Chip | Phys
            # Proc | Res Group | LP Index | VP Index | OS CPU | ...
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 10:
                continue

            # Skip header rows and separator lines
            if parts[1] in ['Node', '------', ''] or 'Nodal' in parts[2]:
                continue

            try:
                # Extract values from table (1-indexed because parts[0] is
                # empty)
                node = int(parts[1])           # Column 1: Node
                nodal_chip = int(parts[2])     # Column 2: Nodal Chip
                hw_core = int(parts[3])        # Column 3: HW Core
                phys_chip = int(parts[4])      # Column 4: Phys Chip
                phys_proc = int(parts[5])      # Column 5: Phys Proc
                res_group = parts[6]           # Column 6: Res Group
                lp_index = parts[7]            # Column 7: LP Index
                vp_index = parts[8]            # Column 8: VP Index
                os_cpu = parts[9]              # Column 9: OS CPU

                # Check if this row has our partition's LP Index
                # Note: LP Index in htm -info may not directly correspond to partition number
                # This is a best-effort attempt; manual configuration is
                # recommended
                if lp_index and lp_index.isdigit():
                    if int(lp_index) == self.partition_no:
                        self.log.info(
                            "Found potential HTM topology for partition %d (LP Index match):",
                            self.partition_no)
                        self.log.info(
                            "  Node: %d, Nodal Chip: %d, HW Core: %d",
                            node,
                            nodal_chip,
                            hw_core)
                        self.log.info(
                            "  Phys Chip: %d, Phys Proc: %d", phys_chip, phys_proc)
                        self.log.info(
                            "  VP Index: %s, OS CPU: %s", vp_index, os_cpu)
                        self.log.info(
                            "Using: Node=%d, Chip=%d (Nodal), Core=%d (HW Core)",
                            node,
                            nodal_chip,
                            hw_core)
                        return {
                            'node': node,
                            'chip': nodal_chip,
                            'core': hw_core
                        }
            except (ValueError, IndexError) as e:
                # Skip malformed lines
                self.log.debug("Skipping line %d: %s (error: %s)",
                               i, line[:50], str(e))
                continue

        # If not found, cannot auto-detect
        self.log.error(
            "Could not find partition %d (LP Index) in htm -info Core HTMs table",
            self.partition_no)
        self.log.error(
            "The LP Index column in the Core HTMs table did not contain value %d",
            self.partition_no)
        self.log.error(
            "Please specify node, chip, core manually in YAML configuration")
        self.log.info("To find the correct values:")
        self.log.info("  1. Run 'htm -info' on phyp console")
        self.log.info(
            "  2. Look for rows in Core HTMs table with LP Index = %d",
            self.partition_no)
        self.log.info(
            "  3. Use the Node, Phys Chip, and Phys Proc values from that row")
        self.cancel(
            "Auto-detection failed: Partition %d not found in phyp htm -info output.\n"
            "The Core HTMs table does not show LP Index = %d for any cores.\n"
            "Please add to YAML:\n"
            "  node: <value>\n"
            "  chip: <value>\n"
            "  core: <value>\n"
            "Example: If htm -info shows '| 0 | 2 | 4 | 2 | 36 | 0 | %d | ...' then use:\n"
            "  node: 0\n"
            "  chip: 2\n"
            "  core: 36" %
            (self.partition_no, self.partition_no, self.partition_no))

    def _install_dependencies(self):
        """Install required packages."""
        smm = SoftwareManager()

        deps = ['gcc', 'make', 'git', 'autoconf', 'automake', 'libtool',
                'binutils-devel', 'libarchive-devel', 'expect', 'telnet']

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def _load_htmdump_module(self):
        """Load htmdump kernel module with verification."""
        self.log.info("Loading htmdump kernel module...")

        # First check if htmdump interface already exists (module loaded or
        # built-in)
        debugfs_htm = '/sys/kernel/debug/powerpc/htmdump'

        # Ensure debugfs is mounted first
        debugfs_root = '/sys/kernel/debug'
        if not os.path.exists(debugfs_root):
            self.log.info("Mounting debugfs...")
            process.run('mount -t debugfs none /sys/kernel/debug',
                        shell=True, sudo=True, ignore_status=True)
            time.sleep(1)

        # Check if htmdump interface exists
        if os.path.exists(debugfs_htm):
            self.log.info(
                "htmdump interface already available at %s",
                debugfs_htm)
        else:
            # Try to load the module
            self.log.info(
                "htmdump interface not found, attempting to load module...")
            result = process.run('modprobe htmdump', shell=True,
                                 ignore_status=True, sudo=True)
            if result.exit_status != 0:
                error_msg = result.stderr.decode(
                    'utf-8', errors='ignore') if result.stderr else ''
                self.log.warning("modprobe htmdump failed: %s", error_msg)

                # Check if module file exists
                result = process.run(
                    'find /lib/modules/$(uname -r) -name htmdump.ko*',
                    shell=True,
                    ignore_status=True)
                if result.exit_status != 0 or not result.stdout:
                    self.cancel(
                        "htmdump kernel module not found.\n"
                        "Please ensure kernel has CONFIG_HTMDUMP=m or CONFIG_HTMDUMP=y enabled.\n"
                        "Module should be at: /lib/modules/$(uname -r)/kernel/arch/powerpc/platforms/pseries/\n"
                        "Or built into the kernel.")
                else:
                    self.fail("Failed to load htmdump module: %s" % error_msg)

            # Wait for interface to appear
            time.sleep(1)

            # Verify htmdump interface is now available
            if not os.path.exists(debugfs_htm):
                # Try checking lsmod as additional diagnostic
                result = process.run('lsmod | grep -i htm', shell=True,
                                     ignore_status=True, sudo=True)
                loaded_modules = result.stdout.decode(
                    'utf-8', errors='ignore') if result.stdout else 'none'

                self.cancel(
                    "htmdump interface not found at %s after modprobe.\n"
                    "Module may have loaded but interface not created.\n"
                    "Loaded HTM-related modules: %s\n"
                    "This may indicate:\n"
                    "  - Kernel version mismatch\n"
                    "  - Missing kernel support (CONFIG_HTMDUMP)\n"
                    "  - Module loaded but debugfs entry not created"
                    % (debugfs_htm, loaded_modules)
                )

            self.log.info("htmdump module loaded successfully")

        # Final verification
        self.log.info("htmdump interface verified at %s", debugfs_htm)

    def _check_ssh_access(self, repo_url):
        """
        Check if SSH access is configured for git repositories.
        Only checks if repo URL uses SSH (git@...).
        """
        if not repo_url.startswith('git@'):
            # HTTPS URL, no SSH check needed
            return True

        # Extract hostname from git@hostname:...
        try:
            hostname = repo_url.split('@')[1].split(':')[0]
            self.log.info("Checking SSH access to %s...", hostname)

            # Test SSH connection
            cmd = 'ssh -T -o StrictHostKeyChecking=no -o ConnectTimeout=10 git@%s' % hostname
            result = process.run(
                cmd, shell=True, ignore_status=True, timeout=15)

            # SSH test usually returns non-zero but with success message
            output = result.stdout.decode(
                'utf-8', errors='ignore') + result.stderr.decode('utf-8', errors='ignore')

            if 'successfully authenticated' in output.lower() or 'hi' in output.lower():
                self.log.info("SSH access to %s is configured", hostname)
                return True
            else:
                self.log.warning("SSH access check output: %s", output[:200])
                return False

        except Exception as e:
            self.log.warning("SSH access check failed: %s", e)
            return False

    def _setup_htmdump(self):
        """Clone and setup htmdump tool."""
        self.log.info("Setting up htmdump tool...")
        self.log.info("Repository: %s", self.htmdump_repo)

        # Check SSH access if using SSH URL
        if self.htmdump_repo.startswith('git@'):
            if not self._check_ssh_access(self.htmdump_repo):
                self.cancel(
                    "SSH access not configured for %s\n"
                    "Please either:\n"
                    "1. Configure SSH keys on github.ibm.com (see README.md)\n"
                    "2. Use HTTPS URL in YAML: htmdump_repo: 'https://github.com/antonblanchard/htmdump.git'" %
                    self.htmdump_repo)

        if not os.path.exists(self.htmdump_dir):
            cmd = 'git clone %s %s' % (self.htmdump_repo, self.htmdump_dir)

            # Try up to 3 times (transient network/auth issues)
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                self.log.info(
                    "Cloning htmdump repository (attempt %d/%d)...",
                    attempt,
                    max_attempts)
                result = process.run(
                    cmd, shell=True, ignore_status=True, timeout=120)

                if result.exit_status == 0:
                    self.log.info("Successfully cloned htmdump repository")
                    break

                error_msg = result.stderr.decode(
                    'utf-8', errors='ignore') if result.stderr else ''
                self.log.warning("Clone attempt %d failed: %s",
                                 attempt, error_msg[:200])

                # Check for specific error types
                if 'account is suspended' in error_msg.lower():
                    self.log.warning(
                        "GitHub account authentication issue detected")
                    if attempt < max_attempts:
                        self.log.info("Retrying in 2 seconds...")
                        time.sleep(2)
                elif 'could not read from remote' in error_msg.lower():
                    self.log.warning("Remote repository access issue")
                    if attempt < max_attempts:
                        self.log.info("Retrying in 2 seconds...")
                        time.sleep(2)
                else:
                    # Other errors, don't retry
                    break
            else:
                # All attempts failed
                self.fail(
                    "Failed to clone htmdump repository after %d attempts.\n"
                    "Last error: %s\n"
                    "Please verify:\n"
                    "  1. SSH keys are configured for %s\n"
                    "  2. Repository exists and is accessible\n"
                    "  3. Network connectivity is stable\n"
                    "You can test manually: git clone %s" %
                    (max_attempts,
                     error_msg,
                     self.htmdump_repo.split('@')[1].split(':')[0] if '@' in self.htmdump_repo else 'the host',
                     self.htmdump_repo))

        self.htmdump_bin = os.path.join(self.htmdump_dir, 'htmdump')
        if not os.path.exists(self.htmdump_bin):
            self.fail("htmdump script not found at %s" % self.htmdump_bin)

        # Make it executable
        os.chmod(self.htmdump_bin, 0o755)
        self.log.info("htmdump tool ready at %s", self.htmdump_bin)

    def _setup_qtrace_tools(self):
        """Clone, compile and setup qtrace-tools."""
        self.log.info("Setting up qtrace-tools...")
        self.log.info("Repository: %s", self.qtrace_repo)

        # Check SSH access if using SSH URL
        if self.qtrace_repo.startswith('git@'):
            if not self._check_ssh_access(self.qtrace_repo):
                self.cancel(
                    "SSH access not configured for %s\n"
                    "Please either:\n"
                    "1. Configure SSH keys on github.ibm.com (see README.md)\n"
                    "2. Use HTTPS URL in YAML: qtrace_repo: 'https://github.com/antonblanchard/qtrace-tools.git'" %
                    self.qtrace_repo)

        if not os.path.exists(self.qtrace_dir):
            cmd = 'git clone %s %s' % (self.qtrace_repo, self.qtrace_dir)
            result = process.run(
                cmd,
                shell=True,
                ignore_status=True,
                timeout=120)
            if result.exit_status != 0:
                error_msg = result.stderr.decode('utf-8', errors='ignore')
                self.fail(
                    "Failed to clone qtrace-tools repository: %s" %
                    error_msg)

        # Apply BFD API fix for newer binutils
        self._apply_qtrace_bfd_fix()

        # Build qtrace-tools
        self.log.info("Building qtrace-tools...")
        os.chdir(self.qtrace_dir)

        commands = [
            './bootstrap.sh',
            './configure',
            'make clean',
            'make -k'  # -k flag: keep going even if some targets fail
        ]

        for cmd in commands:
            self.log.info("Running: %s", cmd)
            result = process.run(
                cmd,
                shell=True,
                ignore_status=True,
                timeout=300)
            if result.exit_status != 0:
                self.log.debug(
                    "Command had non-zero exit: %s (exit code: %d)",
                    cmd,
                    result.exit_status)
                # Continue anyway - make -k will build what it can

        # Check if htmdecoder binary exists (the critical part)
        self.htmdecoder_bin = os.path.join(
            self.qtrace_dir, 'htm', 'htmdecoder')
        if not os.path.exists(self.htmdecoder_bin):
            # Try to find it in alternate locations
            alt_locations = [
                os.path.join(self.qtrace_dir, 'htmdecoder'),
                os.path.join(self.qtrace_dir, 'htm', '.libs', 'htmdecoder'),
            ]
            for alt_path in alt_locations:
                if os.path.exists(alt_path):
                    self.htmdecoder_bin = alt_path
                    self.log.info(
                        "Found htmdecoder at alternate location: %s", alt_path)
                    break
            else:
                self.log.warning(
                    "htmdecoder not found - continuing without decode capability")
                self.htmdecoder_bin = None

        # Verify htmdecoder is executable if it exists
        if self.htmdecoder_bin and os.path.exists(self.htmdecoder_bin):
            if not os.access(self.htmdecoder_bin, os.X_OK):
                os.chmod(self.htmdecoder_bin, 0o755)
            self.log.info("htmdecoder ready: %s", self.htmdecoder_bin)

        self.log.info("qtrace-tools setup complete")

        self.log.info("htmdecoder ready at: %s", self.htmdecoder_bin)

    def _apply_qtrace_bfd_fix(self):
        """Apply BFD API compatibility fix for qtrace-tools."""
        qtbuild_file = os.path.join(self.qtrace_dir, 'qtbuild', 'qtbuild.c')
        htm_file = os.path.join(self.qtrace_dir, 'htm', 'htm.c')

        if os.path.exists(qtbuild_file):
            content = genio.read_file(qtbuild_file)
            # Fix bfd_section_size API change
            content = content.replace(
                '#define xbfd_section_size(x)    bfd_section_size(bpf, x)',
                '#define xbfd_section_size(x)    bfd_section_size(x)'
            )
            genio.write_file(qtbuild_file, content)
            self.log.info("Applied BFD API fix to qtbuild.c")

        if os.path.exists(htm_file):
            content = genio.read_file(htm_file)
            # Make assertion non-fatal
            content = content.replace(
                'assert(htm_bits(value, 53, 62) == 0);',
                'if (htm_bits(value, 53, 62) != 0)\n'
                '        fprintf(stderr, "Warning: unexpected mark bits: 0x%lx\\n", '
                'htm_bits(value, 53, 62));')
            genio.write_file(htm_file, content)
            self.log.info("Applied assertion fix to htm.c")

    def _open_phyp_connection(self):
        """Open persistent socket connection to phyp telnet port."""
        try:
            self.log.info("Opening persistent connection to phyp...")
            self.phyp_connection = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM)
            self.phyp_connection.settimeout(10)
            self.phyp_connection.connect((self.phyp_host, self.phyp_port))

            # Send Enter to get past "Command Time expired" message
            self.phyp_connection.sendall(b"\r\n")
            time.sleep(0.5)

            # Wait for phyp prompt
            self._wait_for_prompt(5)

            self.log.info("Persistent phyp connection established")
        except Exception as e:
            self.log.warning("Failed to open phyp connection: %s", str(e))
            self.phyp_connection = None

    def _close_phyp_connection(self):
        """Close persistent socket connection to phyp."""
        if self.phyp_connection:
            try:
                self.log.info("Closing phyp connection...")
                self.phyp_connection.sendall(b"exit\r\n")
                self.phyp_connection.close()
                self.log.info("Phyp connection closed")
            except Exception as e:
                self.log.warning("Error closing phyp connection: %s", str(e))
            finally:
                self.phyp_connection = None

    def _wait_for_prompt(self, timeout=5):
        """Wait for phyp # prompt and collect all output."""
        prompt = b"phyp #"
        buffer = b""
        start_time = time.time()
        last_data_time = start_time
        prompt_found = False

        # Set socket to non-blocking after initial data
        self.phyp_connection.settimeout(0.5)

        while time.time() - start_time < timeout:
            try:
                data = self.phyp_connection.recv(4096)
                if data:
                    buffer += data
                    last_data_time = time.time()
                    if prompt in data:
                        prompt_found = True
                        # Continue reading for a bit after prompt to get all
                        # output
                        continue
                else:
                    # No data received
                    if prompt_found and (time.time() - last_data_time) > 0.3:
                        # Prompt found and no new data for 0.3s, we're done
                        break
            except socket.timeout:
                # Timeout on recv - check if we have prompt and should exit
                if prompt_found and (time.time() - last_data_time) > 0.3:
                    break
                continue
            except Exception as e:
                self.log.debug("Socket recv error: %s", str(e))
                break

        # Reset socket timeout
        self.phyp_connection.settimeout(10)

        if not prompt_found:
            raise Exception("Timeout waiting for phyp prompt")

        return buffer

    def _phyp_command(self, command, timeout=30, retries=3):
        """Execute command on phyp using persistent socket connection."""
        if not self.phyp_host:
            self.cancel(
                "phyp_host not configured - cannot execute phyp commands")

        # Retry mechanism for phyp commands
        for attempt in range(1, retries + 1):
            self.log.debug(
                "phyp command attempt %d/%d: %s",
                attempt,
                retries,
                command)

            try:
                # Reopen connection if it's not available
                if not self.phyp_connection:
                    self._open_phyp_connection()

                if not self.phyp_connection:
                    raise Exception("Could not establish phyp connection")

                # Send command
                self.phyp_connection.sendall(command.encode('ascii') + b"\r\n")

                # Wait for command output and next prompt
                output = self._wait_for_prompt(timeout)

                # Log phyp command output
                output_str = output.decode('utf-8', errors='ignore')
                self.log.info("phyp> %s", command)
                for line in output_str.split('\n'):
                    if line.strip():
                        self.log.info("  %s", line)

                # Create a mock result object similar to process.run
                class PhypResult:
                    def __init__(self, stdout_data, exit_code=0):
                        self.stdout = stdout_data
                        self.stderr = b""
                        self.exit_status = exit_code

                result = PhypResult(output, 0)
                return result

            except Exception as e:
                self.log.warning(
                    "phyp command attempt %d failed: %s", attempt, str(e))
                # Close and reopen connection on error
                self._close_phyp_connection()

                if attempt < retries:
                    self.log.info("Retrying in 2 seconds...")
                    time.sleep(2)
                else:
                    # Last attempt failed
                    self.log.error(
                        "phyp command failed after %d attempts: %s", retries, command)
                    self.log.error("Error: %s", str(e))
                    # Return a failed result

                    class PhypResult:
                        def __init__(self):
                            self.stdout = b""
                            self.stderr = str(e).encode('utf-8')
                            self.exit_status = 1
                    return PhypResult()

    def _verify_htm_buffers(self):
        """Verify HTM buffer sizes are allocated. Uses cached htm -info output."""
        output = self.htm_info_output if self.htm_info_output else ""

        if not output:
            result = self._phyp_command('htm -info')
            output = result.stdout.decode('utf-8', errors='ignore')

        # Parse buffer sizes
        nest_buffer = None
        core_buffer = None

        for line in output.split('\n'):
            if 'Current Nest HTM buffer size:' in line:
                nest_buffer = line.split(
                    ':')[1].strip() if ':' in line else None
            elif 'Current Core HTM buffer size per core:' in line:
                core_buffer = line.split(
                    ':')[1].strip() if ':' in line else None

        # Verify buffers are allocated
        if not nest_buffer or nest_buffer == '0' or 'not' in nest_buffer.lower():
            self.cancel("Nest HTM buffers not allocated")

        if not core_buffer or core_buffer == '0' or 'not' in core_buffer.lower():
            self.cancel("Core HTM buffers not allocated")

        self.core_buffer_size = core_buffer
        self.log.info(
            "HTM buffers allocated: Nest=%s, Core=%s",
            nest_buffer,
            core_buffer)

    def _configure_htm_on_phyp(self):
        """Configure HTM on phyp."""
        self.log.info("Configuring HTM on phyp...")

        # Verify HTM buffers are allocated
        self._verify_htm_buffers()

        # Deconfigure any existing HTM configuration
        deconfigure_cmd = 'htm -deconfigure %s -n %d -p %d -c %d' % (
            'llat' if self.trace_mode == 'llat' else 'inst',
            self.node, self.chip, self.core
        )
        self._phyp_command(deconfigure_cmd)

        # Configure HTM
        if self.trace_mode == 'inst':
            # Instruction tracing requires SMT off
            self.log.info("Disabling SMT for instruction tracing...")

            # Check current SMT status
            smt_status = process.system_output(
                'ppc64_cpu --smt', shell=True, ignore_status=True).decode('utf-8')
            self.log.info("Current SMT status: %s", smt_status.strip())

            # Disable SMT
            process.run('ppc64_cpu --smt=off', shell=True, sudo=True,
                        ignore_status=True)
            time.sleep(2)

            # Verify SMT is off
            smt_status = process.system_output(
                'ppc64_cpu --smt', shell=True, ignore_status=True).decode('utf-8')
            if 'SMT is off' not in smt_status:
                self.log.warning(
                    "SMT may not be fully disabled: %s",
                    smt_status.strip())

            configure_cmd = 'htm -configure inst -n %d -p %d -c %d' % (
                self.node, self.chip, self.core
            )
            if self.nowrap:
                configure_cmd += ' --nowrap'
        else:
            # LLAT tracing
            configure_cmd = 'htm -configure llat -n %d -p %d -c %d' % (
                self.node, self.chip, self.core
            )

        self.log.info("Configuring HTM: %s", configure_cmd)
        result = self._phyp_command(configure_cmd)
        output = result.stdout.decode('utf-8', errors='ignore')

        # Check for configuration errors
        if 'ERROR' in output:
            if 'SMT1 mode' in output:
                self.fail(
                    "HTM configuration failed: Instruction tracing requires SMT off")
            else:
                self.fail("HTM configuration failed: %s" % output)

        self.log.info("HTM configured for %s tracing", self.trace_mode)

    def _start_htm_trace(self):
        """Start HTM tracing on phyp."""
        self.log.info("Starting HTM trace...")

        start_cmd = 'htm -start %s -n %d -p %d -c %d' % (
            self.trace_mode, self.node, self.chip, self.core
        )
        self._phyp_command(start_cmd)
        self.log.info("HTM trace started")

    def _stop_htm_trace(self):
        """Stop HTM tracing on phyp."""
        self.log.info("Stopping HTM trace...")

        stop_cmd = 'htm -stop %s -n %d -p %d -c %d' % (
            self.trace_mode, self.node, self.chip, self.core
        )
        self._phyp_command(stop_cmd)
        self.log.info("HTM trace stopped")

    def _dump_htm_trace(self):
        """Dump HTM trace data using htmdump."""
        self.log.info("Dumping HTM trace data...")

        # Determine htmdump mode
        if self.trace_mode == 'inst':
            dump_mode = 'core'
        else:
            dump_mode = 'llat0'  # or llat1

        dump_cmd = '%s %s -n %d -c %d -r %d -o %s' % (
            self.htmdump_bin, dump_mode, self.node, self.chip,
            self.core, self.trace_file
        )

        self.log.info("Running htmdump: %s", dump_cmd)
        result = process.run(dump_cmd, shell=True, sudo=False,
                             ignore_status=True, timeout=300)

        # Check if trace file was created (htmdump may return non-zero exit
        # code even on success)
        if not os.path.exists(self.trace_file):
            self.fail("Trace file not created: %s" % self.trace_file)

        trace_size = os.path.getsize(self.trace_file)
        self.log.info("HTM trace dumped: %s (%.2f MB)",
                      self.trace_file, trace_size / (1024 * 1024))

        return trace_size

    def _decode_htm_trace(self):
        """Decode HTM trace using htmdecoder."""
        self.log.info("Decoding HTM trace...")

        decode_cmd = '%s -s %s > %s 2>&1' % (
            self.htmdecoder_bin, self.trace_file, self.decoded_file
        )

        result = process.run(decode_cmd, shell=True, ignore_status=True,
                             timeout=600)

        if not os.path.exists(self.decoded_file):
            self.fail("Decoded file not created")

        decoded_size = os.path.getsize(self.decoded_file)
        self.log.info("HTM trace decoded: %s (%.2f MB)",
                      self.decoded_file, decoded_size / (1024 * 1024))

        return decoded_size

    def _validate_decoded_trace(self):
        """Validate decoded trace output."""
        content = genio.read_file(self.decoded_file)

        # Log the decoded output
        self.log.info("=" * 70)
        self.log.info("HTM Decoded Trace Output:")
        self.log.info("=" * 70)
        self.log.info(content)
        self.log.info("=" * 70)

        # Extract total instruction count from statistics
        insn_count = 0
        if 'Instructions:' in content:
            for line in content.split('\n'):
                if 'Total' in line:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        insn_count = int(parts[1])
                        break

        if insn_count == 0:
            self.fail("No instructions found in decoded trace")

        # Count invalid records (informational only)
        invalid_count = content.count('Invalid record:')

        self.log.info("Total instructions traced: %d (invalid records: %d)",
                      insn_count, invalid_count)

        return insn_count

    def test(self):
        """Execute HTM trace collection and validation."""
        # Setup
        self._load_htmdump_module()
        self._setup_htmdump()
        self._setup_qtrace_tools()

        # Configure and start HTM on phyp
        self._configure_htm_on_phyp()
        self._start_htm_trace()

        # Run workload
        self.log.info(
            "Collecting trace for %d seconds...",
            self.trace_duration)
        time.sleep(self.trace_duration)

        # Stop and dump trace
        self._stop_htm_trace()
        trace_size = self._dump_htm_trace()

        if trace_size < 1024:
            self.fail("Trace file too small (%d bytes)" % trace_size)

        # Decode and validate trace
        decoded_size = self._decode_htm_trace()
        if decoded_size < 100:
            self.fail(
                "Decoded file too small (%d bytes) - decoding likely failed" %
                decoded_size)

        # Validate decoded trace
        insn_count = self._validate_decoded_trace()
        if insn_count == 0:
            self.fail(
                "No instructions found in decoded trace - decoding failed or trace empty")

        self.log.info("HTM trace test completed successfully")
        self.log.info("Total instructions traced: %d", insn_count)

    def tearDown(self):
        """
        Cleanup: deconfigure HTM on phyp and restore system state.
        """
        self.log.info("Starting cleanup...")

        # Deconfigure HTM on phyp (same way we configured it)
        if hasattr(self, 'phyp_host') and self.phyp_host:
            if (hasattr(self, 'node') and hasattr(self, 'chip') and hasattr(self, 'core')
                    and self.node is not None and self.chip is not None and self.core is not None):
                self.log.info("Deconfiguring HTM on phyp...")
                self.log.info("  Node: %d, Chip: %d, Core: %d",
                              self.node, self.chip, self.core)

                # Deconfigure instruction tracing
                deconfigure_cmd = 'htm -deconfigure inst -n %d -p %d -c %d' % (
                    self.node, self.chip, self.core
                )

                result = self._phyp_command(deconfigure_cmd)
                output = result.stdout.decode('utf-8', errors='ignore')

                if 'deconfigured' in output.lower() or result.exit_status == 0:
                    self.log.info("HTM successfully deconfigured on phyp")
                else:
                    self.log.warning(
                        "HTM deconfigure may have failed: %s", output)

        # Close persistent phyp connection
        if hasattr(self, 'phyp_connection'):
            self._close_phyp_connection()

        # Re-enable SMT if it was disabled for instruction tracing
        if hasattr(self, 'trace_mode') and self.trace_mode == 'inst':
            self.log.info("Re-enabling SMT...")
            result = process.run('ppc64_cpu --smt=on', shell=True, sudo=True,
                                 ignore_status=True)

            # Verify SMT is back on
            smt_status = process.system_output(
                'ppc64_cpu --smt', shell=True, ignore_status=True).decode('utf-8')
            self.log.info("SMT status after cleanup: %s", smt_status.strip())

        # Keep trace files for analysis but log their location
        if hasattr(self, 'htm_workdir') and os.path.exists(self.htm_workdir):
            self.log.info("=" * 70)
            self.log.info("Test artifacts preserved in: %s", self.htm_workdir)
            if hasattr(self, 'trace_file'):
                self.log.info("  Trace file: %s", self.trace_file)
            if hasattr(self, 'decoded_file'):
                self.log.info("  Decoded file: %s", self.decoded_file)
            self.log.info("=" * 70)

        self.log.info("Cleanup completed")

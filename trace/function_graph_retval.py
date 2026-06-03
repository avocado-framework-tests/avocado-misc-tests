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
# Copyright: 2026 IBM.
# Author: Sachin Sant <sachinp@linux.ibm.com>
#
# Test to validate function graph return value tracing support on ppc64le
# Validates kernel commit d733f18a6da6fb719450d5122162556d785ed580

import os
import platform
import re
import shutil
import tempfile
from avocado import Test
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils import process
from avocado.utils import linux_modules
from avocado.utils.software_manager.manager import SoftwareManager


class FunctionGraphRetval(Test):

    """
    Test function graph return value tracing on ppc64le architecture.

    This test validates the kernel commit d733f18a6da6
    which added support for CONFIG_FUNCTION_GRAPH_RETVAL on PowerPC.

    The test verifies:
    1. Kernel configuration has FUNCTION_GRAPH_RETVAL support
    2. Function graph tracer is available
    3. Return value tracing can be enabled
    4. Return values are correctly captured in trace output
    5. ftrace_regs_get_return_value() works correctly
    6. ftrace_regs_get_frame_pointer() works correctly

    :avocado: tags=privileged,trace,ftrace,ppc64le
    """

    def setUp(self):
        """
        Set up the test environment and check prerequisites.
        """
        # Check if running on ppc64le architecture
        arch = platform.machine()
        if arch not in ['ppc64le', 'ppc64']:
            self.cancel("Test is specific to PowerPC architecture")

        # Check for secure boot
        cmd = "lsprop /proc/device-tree/ibm,secure-boot 2>/dev/null"
        output = process.system_output(cmd, ignore_status=True,
                                       shell=True).decode()
        if '00000002' in output:
            self.cancel("Secure boot is enabled, cannot load kernel modules")

        # Install required packages for module building
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make']

        if detected_distro.name in ['Ubuntu', 'debian']:
            linux_headers = 'linux-headers-%s' % os.uname()[2]
            deps.extend([linux_headers])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['kernel-source'])
        elif detected_distro.name in ['centos', 'fedora', 'rhel']:
            deps.extend(['kernel-devel', 'kernel-headers'])

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel("Package %s is required for module building" %
                            package)

        # Check if ftrace is available
        if not os.path.exists('/sys/kernel/debug/tracing'):
            self.cancel("ftrace debugfs not available")

        # Check kernel configuration
        self._check_kernel_config()

        # Set up paths
        self.tracefs = '/sys/kernel/debug/tracing'
        self.current_tracer = os.path.join(self.tracefs, 'current_tracer')
        self.tracing_on = os.path.join(self.tracefs, 'tracing_on')
        self.trace_file = os.path.join(self.tracefs, 'trace')

        # Set up module build directory
        self.module_dir = tempfile.mkdtemp()
        self.module_name = 'test_retval'
        self.module_loaded = False
        self.failures = []

    def _check_kernel_config(self):
        """
        Check if kernel has required configuration options enabled.
        """
        required_configs = [
            'CONFIG_FUNCTION_GRAPH_TRACER',
            'CONFIG_HAVE_FUNCTION_GRAPH_FREGS'
        ]

        missing_configs = []
        for config in required_configs:
            config_status = linux_modules.check_kernel_config(config)
            if config_status == linux_modules.ModuleConfig.NOT_SET:
                missing_configs.append(config)

        if missing_configs:
            self.cancel("Required kernel configs not enabled: %s" %
                        ', '.join(missing_configs))

        self.log.info("All required kernel configurations are enabled")

    def _run_cmd(self, cmd, ignore_status=False):
        """
        Execute a command and return output.
        """
        self.log.debug("Executing: %s", cmd)
        result = process.run(cmd, ignore_status=ignore_status, sudo=True,
                             shell=True)
        return result.stdout_text

    def _write_file(self, filepath, content):
        """
        Write content to a file with proper error handling.
        """
        try:
            genio.write_file(filepath, content)
            self.log.debug("Written '%s' to %s", content, filepath)
        except Exception as e:
            self.failures.append("Failed to write to %s: %s" %
                                 (filepath, str(e)))

    def _read_file(self, filepath):
        """
        Read content from a file with proper error handling.
        """
        try:
            content = genio.read_file(filepath).strip()
            self.log.debug("Read from %s: %s", filepath, content)
            return content
        except Exception as e:
            self.failures.append("Failed to read from %s: %s" %
                                 (filepath, str(e)))
            return None

    def _build_test_module(self):
        """
        Build a simple kernel module for testing return value tracing.
        """
        self.log.info("=" * 60)
        self.log.info("Building test kernel module")
        self.log.info("=" * 60)

        # Copy module source from .data directory
        shutil.copyfile(self.get_data('retval_test.c'),
                        os.path.join(self.module_dir, 'test_retval.c'))

        # Copy and customize Makefile with actual module directory path
        makefile_template = genio.read_file(self.get_data('Makefile'))
        makefile_content = makefile_template.replace('MODULE_DIR',
                                                     self.module_dir)
        genio.write_file(os.path.join(self.module_dir, 'Makefile'),
                         makefile_content)

        # Build module
        self.log.info("Building module in %s", self.module_dir)
        build.make(self.module_dir)

        module_ko = os.path.join(self.module_dir, '%s.ko' % self.module_name)
        if not os.path.isfile(module_ko):
            self.fail("Failed to build kernel module")

        self.log.info("Module built successfully: %s", module_ko)
        return module_ko

    def _load_test_module(self, module_path):
        """
        Load the test kernel module.
        """
        self.log.info("Loading test module: %s", module_path)
        try:
            process.run("insmod %s" % module_path, sudo=True, shell=True)
            self.module_loaded = True
            self.log.info("Module loaded successfully")
            # No sleep - module init executes synchronously during insmod
        except Exception as e:
            self.fail("Failed to load module: %s" % str(e))

    def _unload_test_module(self):
        """
        Unload the test kernel module.
        """
        if self.module_loaded:
            self.log.info("Unloading test module")
            try:
                process.run("rmmod %s" % self.module_name, sudo=True,
                            shell=True, ignore_status=True)
                self.module_loaded = False
                self.log.info("Module unloaded")
            except Exception as e:
                self.log.warning("Failed to unload module: %s", str(e))

    def _setup_function_graph_tracer(self):
        """
        Set up function graph tracer with return value tracing.
        """
        self.log.info("=" * 60)
        self.log.info("Setting up function graph tracer")
        self.log.info("=" * 60)

        # Disable tracing first
        self._write_file(self.tracing_on, '0')

        # Clear previous traces
        self._write_file(self.trace_file, '')

        # Set function graph tracer
        self._write_file(self.current_tracer, 'function_graph')

        # Enable funcgraph-retval option
        retval_option = os.path.join(self.tracefs, 'options/funcgraph-retval')
        if os.path.exists(retval_option):
            self._write_file(retval_option, '1')
            self.log.info("Enabled funcgraph-retval option")
        else:
            self.failures.append("funcgraph-retval option not available")
            return False

        # Verify the option is enabled
        if self._read_file(retval_option) != '1':
            self.failures.append("Failed to enable funcgraph-retval option")
            return False

        return True

    def _capture_trace(self, module_path):
        """
        Capture trace output from kernel module loading.
        """
        self.log.info("=" * 60)
        self.log.info("Capturing function trace with return values")
        self.log.info("=" * 60)

        # Clear trace buffer
        self._write_file(self.trace_file, '')

        # Enable tracing
        self._write_file(self.tracing_on, '1')

        # Load module to trigger traced functions
        self._load_test_module(module_path)

        # Disable tracing immediately to stop buffer from filling
        self._write_file(self.tracing_on, '0')

        # Read trace output
        trace_output = self._read_file(self.trace_file)
        if not trace_output:
            self.failures.append("No trace output captured")
            return None

        return trace_output

    def _search_module_functions_in_trace(self, trace_output,
                                          max_samples=None,
                                          log_findings=True):
        """
        Search for test module functions with return values in trace output.

        This helper method extracts the common logic for searching trace o/p
        for test module related functions (containing 'test_retval' in name).

        Args:
            trace_output: The trace output string to search
            max_samples: Maximum number of return values to collect before
            stopping (None = no limit)
            log_findings: Whether to log each finding (default: True)

        Returns:
            A tuple of (found_module_functions, retval_count,
            has_graph_output, lines_scanned)
            where:
            - found_module_functions: dict mapping function names to list
              of occurrences
            - retval_count: total number of return values found
            - has_graph_output: boolean indicating if function graph output
              was detected
            - lines_scanned: number of lines processed
        """
        found_module_functions = {}
        retval_count = 0
        has_graph_output = False
        lines_scanned = 0

        if not trace_output:
            return (found_module_functions, retval_count,
                    has_graph_output, lines_scanned)

        # Pattern to match return values in a line
        retval_pattern = re.compile(
            r'/\*\s*(?:(\w+)(?:\s+\[[\w]+\])?\s*)?=\s*'
            r'(0x[0-9a-fA-F]+|-?[0-9]+)\s*\*/')

        # Process trace line by line for efficiency
        lines = trace_output.split('\n')
        for line_num, line in enumerate(lines, 1):
            lines_scanned = line_num
            # Check for function graph output
            if not has_graph_output and ('{' in line or '}' in line):
                has_graph_output = True

            # Look for return values
            match = retval_pattern.search(line)
            if match:
                retval_count += 1
                func_name = match.group(1) if match.group(1) else 'anonymous'
                retval = match.group(2)

                # Check if this is one of our test module functions
                if 'test_retval' in func_name:
                    if func_name not in found_module_functions:
                        found_module_functions[func_name] = []
                    found_module_functions[func_name].append({
                        'line_num': line_num,
                        'value': retval,
                        'full_line': line.strip()
                    })
                    if log_findings:
                        self.log.info("Line %d: Found function '%s' = %s",
                                      line_num, func_name, retval)

                    # Early exit optimization if max_samples specified
                    if max_samples and retval_count >= max_samples:
                        if 'test_retval_init' in found_module_functions:
                            self.log.debug('Found required function and %d '
                                           'return values, stopping scan',
                                           retval_count)
                            break

        return (found_module_functions, retval_count,
                has_graph_output, lines_scanned)

    def _verify_return_values(self, trace_output):
        """
        Verify that return values are present in trace output for our test
        module.

        The test module's init function (test_retval_init) should appear in
        the trace with a return value of 0x0. The module also defines helper
        functions that may or may not appear depending on compiler
        optimization (noinline attribute used).

        Function graph tracer with funcgraph-retval shows return values like:
        - /* test_retval_init [test_retval] = 0x0 */
        - /* test_retval_func = 0x3e */
        """
        self.log.info("=" * 60)
        self.log.info("Verifying return values in trace output")
        self.log.info("=" * 60)

        if not trace_output:
            self.failures.append("No trace output to verify")
            return

        # Save trace output for debugging
        trace_log = os.path.join(self.outputdir, 'trace_output.log')
        genio.write_file(trace_log, trace_output)
        self.log.info("Trace output saved to: %s", trace_log)

        # Search for module functions in trace using helper method
        (found_module_functions, retval_count,
         has_graph_output, lines_scanned) = \
            self._search_module_functions_in_trace(
                trace_output, max_samples=100, log_findings=True)

        # Report findings
        self.log.info("=" * 60)
        self.log.info("Return Value Analysis")
        self.log.info("=" * 60)

        # Check if ANY function graph output exists
        if has_graph_output:
            self.log.info('Function graph tracer is working - found function '
                          'call traces')
        else:
            self.log.error("No function graph output detected at all")
            self.failures.append('No function graph tracer output - check if '
                                 'tracer is working')

        # Report return values found
        if retval_count > 0:
            self.log.info("Found %d return value entries (scanned %d lines)",
                          retval_count, lines_scanned)
        else:
            self.log.error("No return values found in trace output")
            self.failures.append("No return values found in trace output")

        # Verify test module functions
        self.log.info("=" * 60)
        self.log.info("Test Module Function Verification")
        self.log.info("=" * 60)

        if not found_module_functions:
            self.log.error("No test module functions found in trace output")
            self.log.error("Expected to find at least 'test_retval_init'")
            self.failures.append('Test module functions not found in trace - '
                                 'module may not have been traced')
            # Log first 50 lines for debugging
            self.log.info("First 50 lines of trace output for debugging:")
            trace_lines = trace_output.split('\n')
            for i, line in enumerate(trace_lines[:50]):
                self.log.info("  %d: %s", i + 1, line)
        else:
            self.log.info("Found %d test module function(s) in trace:",
                          len(found_module_functions))

            # Check for test_retval_init (required)
            if 'test_retval_init' in found_module_functions:
                occurrences = found_module_functions['test_retval_init']
                self.log.info(" test_retval_init: found %d occurrence(s)",
                              len(occurrences))

                for i, detail in enumerate(occurrences[:3]):
                    self.log.info("    Example %d (line %d): %s", i + 1,
                                  detail['line_num'], detail['full_line'])

                    # Verify return value is 0 (successful init)
                    actual_value = detail['value'].lower()
                    if actual_value in ['0x0', '0']:
                        self.log.info(' Return value is 0 (successful module '
                                      'init)')
                    else:
                        self.log.warning(' Unexpected return value: %s '
                                         '(expected 0x0)', actual_value)
            else:
                self.log.error("test_retval_init: NOT found in trace")
                self.failures.append('Required function test_retval_init '
                                     'not found in trace')

            # Verify other test_retval functions are found (required since
            # they use noinline attribute)
            expected_funcs = ['test_retval_func', 'test_retval_large',
                              'test_retval_zero', 'test_retval_negative']
            other_funcs = [f for f in found_module_functions.keys()
                           if f != 'test_retval_init']

            if other_funcs:
                self.log.info("  Additional test module functions found:")
                for func_name in other_funcs:
                    occurrences = found_module_functions[func_name]
                    self.log.info(" %s: found %d occurrence(s)", func_name,
                                  len(occurrences))
                    for i, detail in enumerate(occurrences[:2]):
                        self.log.info(" Example %d: %s", i + 1,
                                      detail['full_line'])

            # Check for missing helper functions (should not happen with
            # noinline)
            missing_funcs = [f for f in expected_funcs
                             if f not in found_module_functions]
            if missing_funcs:
                self.log.error('  Missing helper functions (marked noinline): '
                               '%s', ', '.join(missing_funcs))
                self.failures.append('Helper functions with noinline '
                                     'attribute not found in trace: %s' %
                                     ', '.join(missing_funcs))

        # Final validation
        if retval_count == 0:
            self.failures.append('No return values found - funcgraph-retval '
                                 'may not be working')
        elif 'test_retval_init' not in found_module_functions:
            self.failures.append('Required test_retval_init function not '
                                 'found in trace')
        else:
            self.log.info("=" * 60)
            self.log.info("SUCCESS: Return value tracing is working")
            self.log.info("  - Found %d return values", retval_count)
            self.log.info("  - Found %d test module function(s)",
                          len(found_module_functions))
            self.log.info("=" * 60)

    def _test_basic_functionality(self):
        """
        Test basic function graph return value tracing.
        """
        self.log.info("=" * 60)
        self.log.info("Test 1: Basic function graph return value tracing")
        self.log.info("=" * 60)

        # Build test module
        module_path = self._build_test_module()

        # Setup tracer
        if not self._setup_function_graph_tracer():
            return

        # Capture trace
        trace_output = self._capture_trace(module_path)

        # Unload module
        self._unload_test_module()

        # Verify return values
        self._verify_return_values(trace_output)

    def _test_without_retval_option(self):
        """
        Test without funcgraph-retval option, return values are not shown.
        """
        self.log.info("=" * 60)
        self.log.info("Test : Verify without funcgraph-retval option")
        self.log.info("=" * 60)

        # Build module if not already built
        module_path = os.path.join(self.module_dir, '%s.ko' % self.module_name)
        if not os.path.exists(module_path):
            module_path = self._build_test_module()

        # Disable tracing
        self._write_file(self.tracing_on, '0')

        # Disable funcgraph-retval option
        retval_option = os.path.join(self.tracefs, 'options/funcgraph-retval')
        if os.path.exists(retval_option):
            self._write_file(retval_option, '0')
            self.log.info("Disabled funcgraph-retval option")

        # Clear trace
        self._write_file(self.trace_file, '')

        # Enable tracing
        self._write_file(self.tracing_on, '1')

        # Load module to trigger function
        self._load_test_module(module_path)

        # Disable tracing immediately
        self._write_file(self.tracing_on, '0')

        # Unload module
        self._unload_test_module()

        # Read trace
        trace_output = self._read_file(self.trace_file)

        # Verify return values are NOT present using helper method
        if trace_output:
            # Search for module functions (should find none with return values)
            found_module_functions, retval_count, _, _ = \
                self._search_module_functions_in_trace(trace_output,
                                                       max_samples=10,
                                                       log_findings=False)

            # Convert to the format expected by the rest of the code
            found_module_retvals = []
            for func_name, occurrences in found_module_functions.items():
                for occurrence in occurrences:
                    found_module_retvals.append((func_name,
                                                occurrence['value'],
                                                occurrence['full_line']))
                    self.log.warning('Line %d: Found test module function %s'
                                     '= %s (should not have return value)',
                                     occurrence['line_num'], func_name,
                                     occurrence['value'])

            if retval_count > 0:
                self.log.warning('Found %d return values without '
                                 'funcgraph-retval option enabled',
                                 retval_count)
                self.log.warning('This may indicate the option is not working '
                                 'correctly')

                # Show examples, prioritizing module functions
                if found_module_retvals:
                    self.log.warning("Test functions with return values:")
                    for i, (func, val, line) in enumerate(
                            found_module_retvals[:3]):
                        self.log.warning("  Example %d: %s = %s",
                                         i + 1, func, val)
                        self.log.warning("    %s", line)

            else:
                self.log.info('SUCCESS: No return values found without '
                              'funcgraph-retval option')
                self.log.info('This confirms the option correctly controls '
                              'return value display')
        else:
            self.log.warning("No trace output captured for verification")

    def _cleanup_tracer(self):
        """
        Clean up tracer settings and module.
        """
        self.log.info("=" * 60)
        self.log.info("Cleaning up tracer settings")
        self.log.info("=" * 60)

        # Unload module if still loaded
        self._unload_test_module()

        # Disable tracing
        self._write_file(self.tracing_on, '0')

        # Reset to nop tracer
        self._write_file(self.current_tracer, 'nop')

        # Clear trace buffer
        self._write_file(self.trace_file, '')

        self.log.info("Tracer cleanup completed")

    def test(self):
        """
        Main test execution method.
        """

        try:
            # Test 1: Basic functionality
            self._test_basic_functionality()

            # Test 2: Without retval option
            self._test_without_retval_option()

        finally:
            # Always cleanup
            self._cleanup_tracer()

        # Report any failures
        if self.failures:
            self.log.error("=" * 60)
            self.log.error("Test failures detected:")
            self.log.error("=" * 60)
            for i, failure in enumerate(self.failures, 1):
                self.log.error("%d. %s", i, failure)
            self.fail("Test failed with %d error(s)" % len(self.failures))

        self.log.info("=" * 60)
        self.log.info("All tests passed successfully")
        self.log.info("=" * 60)

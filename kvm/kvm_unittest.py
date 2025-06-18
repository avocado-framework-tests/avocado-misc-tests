#!/usr/bin/env python
#
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
# Copyright: 2025 Advanced Micro Devices, Inc.
# Author: Narasimhan V <narasimhan.v@amd.com>
# Author: Dheeraj Kumar Srivastava <dheerajkumar.srivastava@amd.com>
# Author: Amandeep Kaur Longia <amandeepkaur.longia@amd.com>

import os
import shutil

from avocado import Test
from avocado.utils import git, build, process, genio
from avocado.utils import cpu, linux_modules


# pylint: disable=too-many-instance-attributes
class KVMUnitTest(Test):
    """
    Avocado test suite to validate KVM functionality using kvm-unit-tests.
    """

    def setUp(self):
        """
        Set up the test environment:
        - Clone and build the kvm-unit-tests repository if not already present.
        - Detect and configure the vendor specific KVM module (eg: kvm_amd or kvm_intel).
        - Set environment variables to run the test.
        """
        self.init_parameters()

        if self.mode not in ("accelerated", "non-accelerated", None):
            self.cancel(
                f"Invalid mode '{self.mode}', expected 'accelerated', 'non-accelerated', or empty"
            )

        # Set custom QEMU binary in test environment if it exists, otherwise skip the test.
        if self.qemu_binary:
            if os.path.exists(self.qemu_binary):
                self.test_env["QEMU"] = self.qemu_binary
            else:
                self.cancel(f"Custom QEMU binary not found: {self.qemu_binary}")

        # Set accelerator in test environment if specified in parameters.
        if self.accelerator:
            self.test_env["ACCEL"] = self.accelerator

        # Detect, capture state, and configure the KVM module for the test environment.
        self.detect_kvm_module()
        self.capture_kvm_module_state()
        self.check_and_configure_kvm_module()

        # Clone the KVM unit tests repository
        if not os.path.isdir(self.kvm_tests_dir):
            git.get_repo(self.kvm_tests_repo, destination_dir=self.kvm_tests_dir)

        # Build the KVM unit tests repository
        os.chdir(self.kvm_tests_dir)
        self.build_status = os.path.join(self.kvm_tests_dir, ".kvm_build_status")
        rebuild_required = True

        if os.path.exists(self.build_status):
            with open(self.build_status, "r", encoding="utf-8") as f:
                if f.read().strip() == "success":
                    rebuild_required = False
                    self.log.info("KVM unit test repository already built. Skipping rebuild.")
                else:
                    self.log.info("KVM unit test repository build failed. Rebuilding.")

        if rebuild_required:
            try:
                configure_cmd = f"./configure {self.configure_args}"
                process.system(configure_cmd, ignore_status=False, shell=True)
                build.make(self.kvm_tests_dir, extra_args=f"-j {os.cpu_count()}")
                with open(self.build_status, "w", encoding="utf-8") as f:
                    f.write("success")
            except Exception as err:
                with open(self.build_status, "w", encoding="utf-8") as f:
                    f.write("failed")
                self.log.error("Failed to build kvm-unit-tests: %s", err)
                raise

        # If no tests specified, list all available tests
        if self.tests == "":
            self.tests = " ".join(
                process.run(
                    "./run_tests.sh -l", shell=True, verbose=True
                ).stdout_text.split()
            )

    def init_parameters(self):
        """
        Initialize test configuration parameters and runtime environment.
        """
        self.kvm_tests_repo = self.params.get(
            "kvm_tests_repo",
            default="https://gitlab.com/kvm-unit-tests/kvm-unit-tests",
        )
        self.kvm_tests_dir = os.path.join(self.teststmpdir, "kvm-unit-tests")
        self.configure_args = self.params.get("configure_args", default="")
        self.tests = self.params.get("test", default="")
        self.mode = self.params.get("mode", default=None)
        self.qemu_binary = self.params.get("qemu_binary")
        self.accelerator = self.params.get("accelerator")
        self.kvm_module = None
        self.kvm_module_param = self.params.get("kvm_module_param", default="avic")
        self.test_env = os.environ.copy()
        self.initial_kvm_params = {}
        self.initial_dmesg = "dmesg_initial.txt"
        self.final_dmesg = "dmesg_final.txt"

    def detect_kvm_module(self):
        """
        Detects the CPU vendor and returns the appropriate KVM module and parameter.
        Defaults to 'kvm_amd' for AMD CPUs and 'kvm_intel' for Intel CPUs.
        """
        vendor = cpu.get_vendor()
        if "amd" in vendor:
            self.kvm_module = "kvm_amd"
        elif "intel" in vendor:
            self.kvm_module = "kvm_intel"
        else:
            self.cancel(f"Unsupported CPU vendor: {vendor}")

    def capture_kvm_module_state(self):
        """
        Stores the initial state and readable parameters of the KVM module.
        - If the module is not loaded, save the state as 'unloaded'.
        - If the module is loaded, save the state as 'loaded'; read and store sysfs parameters.
        """
        if not linux_modules.module_is_loaded(self.kvm_module):
            self.initial_kvm_params["__state__"] = "unloaded"
            return

        kvm_sysfs_param_dir = f"/sys/module/{self.kvm_module}/parameters"
        if not os.path.exists(kvm_sysfs_param_dir):
            self.cancel(
                f"Unable to read parameters: sysfs path not found at {kvm_sysfs_param_dir}"
            )

        self.initial_kvm_params["__state__"] = "loaded"
        self.log.info(
            "Storing initial values for KVM module '%s' parameters.", self.kvm_module
        )
        for param_name in os.listdir(kvm_sysfs_param_dir):
            param_path = os.path.join(kvm_sysfs_param_dir, param_name)
            if os.path.isfile(param_path) and os.access(param_path, os.R_OK):
                try:
                    value = genio.read_file(param_path).rstrip("\n")
                    self.initial_kvm_params[param_name] = value
                except (OSError, IOError) as e:
                    self.log.warn("Failed to read parameter '%s': %s", param_name, e)

    def check_and_configure_kvm_module(self):
        """
        Check if the specified kernel config "config_option" is builtin, module or not set.
        - config_option: Kernel config to check (e.g., CONFIG_KVM_AMD or CONFIG_KVM_INTEL)
        """
        config_option = f"CONFIG_{self.kvm_module.upper()}"
        config_status = linux_modules.check_kernel_config(config_option)

        if config_status == linux_modules.ModuleConfig.NOT_SET:
            self.cancel(f"{config_option} is not set in the kernel configuration.")

        if config_status == linux_modules.ModuleConfig.MODULE:
            self.log.info("%s is a loadable kernel module.", config_option)
            self.configure_kvm_module()
            return

        if (
            config_status == linux_modules.ModuleConfig.BUILTIN
            and self.mode is not None
        ):
            self.log.info("%s is built-in kernel module.", config_option)
            expected_value = ("1", "Y") if self.mode == "accelerated" else ("0", "N")

            if not self.verify_sysfs_param(expected_value):
                self.cancel(
                    f"Cannot modify kvm module parameters since {config_option} is built-in."
                )

    def configure_kvm_module(self):
        """
        Configure the kvm module with appropriate parameter based on test mode
        Modes:
        - 'accelerated': Enables hardware acceleration by setting the module parameter to 1.
        - 'non-accelerated': Disables hardware acceleration by setting the module parameter to 0.
        - None: Loads the module without modifying the parameter.
        """
        if self.mode is None:
            if not linux_modules.module_is_loaded(self.kvm_module):
                linux_modules.load_module(self.kvm_module)
                return
            return

        if linux_modules.module_is_loaded(self.kvm_module):
            linux_modules.unload_module(self.kvm_module)

        if self.mode == "accelerated":
            process.run(f"dmesg -T > {self.initial_dmesg}", shell=True, ignore_status=True)
            linux_modules.load_module(f"{self.kvm_module} {self.kvm_module_param}=1")
            process.run(f"dmesg -T > {self.final_dmesg}", shell=True, ignore_status=True)

            if not self.verify_sysfs_param(("1", "Y")):
                self.cancel(
                    f"Failed to set '{self.kvm_module_param}=1' for module '{self.kvm_module}'."
                )
            self.verify_kvm_dmesg()

        elif self.mode == "non-accelerated":
            linux_modules.load_module(f"{self.kvm_module} {self.kvm_module_param}=0")

            if not self.verify_sysfs_param(("0", "N")):
                self.cancel(
                    f"Failed to set '{self.kvm_module_param}=0' for module '{self.kvm_module}'."
                )

    def verify_sysfs_param(self, expected_value):
        """
        Check and validate kvm module against expected_value
        expected_value: List of expected values for kvm module parameter
        """
        param_path = f"/sys/module/{self.kvm_module}/parameters/{self.kvm_module_param}"
        if not os.path.exists(param_path):
            self.cancel(f"Parameter sysfs path not found: {param_path}")

        current_value = genio.read_file(param_path).rstrip("\n")
        return current_value in expected_value

    def verify_kvm_dmesg(self):
        """
        Validates AVIC and x2AVIC enablement via dmesg logs.
        """
        diff = process.run(
            f"diff {self.initial_dmesg} {self.final_dmesg}",
            ignore_status=True,
            shell=True,
        ).stdout_text

        # Check for "AVIC enabled" in the dmesg diff (required for accelerated mode)
        if "AVIC enabled" not in diff:
            self.cancel("AVIC not enabled; cancelling accelerated mode tests.")

        # Check for "x2AVIC enabled" only if the test mode is 'x2apic'
        if "x2apic" in self.tests.split(" ") and "x2AVIC enabled" not in diff:
            self.tests = " ".join(test for test in self.tests.split(" ") if test != "x2apic")
            if self.tests == "":
                self.cancel("x2AVIC not enabled. Cancelling the 'x2apic' test in accelerated mode.")
            self.log.warn("x2AVIC not enabled. Removing 'x2apic' from test list.")

    def test(self):
        """
        Run KVM unit tests listed in `self.tests` using `run_tests.sh` and log results.
        Fails the test suite if any test fails or if execution encounters an error.
        """
        os.chdir(self.kvm_tests_dir)
        failed_tests, skipped_tests, passed_tests = [], [], []

        try:
            for test in self.tests.split(" "):
                result = process.run(
                    f"./run_tests.sh {test}",
                    shell=True,
                    ignore_status=False,
                    verbose=True,
                    env=self.test_env,
                ).stdout_text

                if "FAIL" in result:
                    failed_tests.append(test)
                elif "SKIP" in result:
                    skipped_tests.append(test)
                elif "PASS" in result:
                    passed_tests.append(test)

                log_path = f"logs/{test}.log"
                if os.path.exists(log_path):
                    shutil.copy(log_path, self.outputdir)
                    with open(log_path, "r", encoding="utf-8") as f:
                        result = f.read()
                        self.log.info("%s", result)

            for t, label in [
                (failed_tests, "failed"),
                (skipped_tests, "skipped"),
                (passed_tests, "passed"),
            ]:
                if t:
                    self.log.info("%d test(s) %s: %s.", len(t), label, t)

            if failed_tests:
                self.fail(
                    f"{len(failed_tests)} test(s) failed: {(failed_tests)}. Check logs for details."
                )

        except process.CmdError as err:
            self.fail(f"Test '{self.tests}' failed to execute: {err}")

    def tearDown(self):
        """
        Restore the KVM module state by unloading or reloading with original parameters.
        """
        if not hasattr(self, "initial_kvm_params"):
            return

        self.log.info("Restoring the initial setup")
        if self.initial_kvm_params.get("__state__") == "unloaded":
            linux_modules.unload_module(self.kvm_module)
        elif self.initial_kvm_params.get("__state__") == "loaded":
            param_args = " ".join(
                f"{k}={v}"
                for k, v in self.initial_kvm_params.items()
                if k != "__state__"
            )
            if param_args:
                linux_modules.unload_module(self.kvm_module)
                linux_modules.load_module(f"{self.kvm_module} {param_args}")

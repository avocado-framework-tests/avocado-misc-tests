#!/usr/bin/python

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
# Copyright: 2024 IBM

"""
LockdownMixin — reusable kernel lockdown helpers.

Drop this mixin into any Test class that needs to read or set
/sys/kernel/security/lockdown.  No dependency on PCI, network, or
any other subsystem — only avocado.utils.process and self.log.

Usage:
    from generic.lockdown_mixin import LockdownMixin

    class MyTest(Test, LockdownMixin):
        def setUp(self):
            self.lockdown_path = "/sys/kernel/security/lockdown"
            ...
"""

import os
from avocado.utils import process


class LockdownMixin:
    """
    Mixin that provides kernel lockdown check/get/set helpers.

    The consuming class must expose:
      - self.log        (provided by avocado.Test)
      - self.lockdown_path  (set in setUp before calling any method)
    """

    def check_lockdown_support(self):
        """
        Check if kernel lockdown is supported on this system.

        Returns True if /sys/kernel/security/lockdown exists, else False.
        """
        if not os.path.exists(self.lockdown_path):
            self.log.warn("Kernel lockdown not supported on this system")
            return False
        return True

    def get_lockdown_state(self):
        """
        Read and return the current lockdown state.

        Parses the kernel output format: "none [integrity] confidentiality"
        Returns one of: 'none', 'integrity', 'confidentiality', or None on error.
        """
        try:
            output = process.system_output(
                f'cat {self.lockdown_path}',
                shell=True, sudo=True
            ).decode("utf-8")
            if '[none]' in output:
                return 'none'
            elif '[integrity]' in output:
                return 'integrity'
            elif '[confidentiality]' in output:
                return 'confidentiality'
        except Exception as exc:
            self.log.error(f"Failed to get lockdown state: {exc}")
        return None

    def set_lockdown_mode(self, mode):
        """
        Set kernel lockdown to *mode* ('none', 'integrity', or 'confidentiality').

        Returns True on success, False otherwise.
        Skips silently if lockdown is not supported.
        """
        if not self.check_lockdown_support():
            return False

        current_state = self.get_lockdown_state()
        self.log.info(f"Current lockdown state: {current_state}")

        if mode == current_state:
            self.log.info(f"Lockdown already set to {mode}")
            return True

        try:
            process.run(
                f'echo "{mode}" > {self.lockdown_path}',
                shell=True, sudo=True
            )
            new_state = self.get_lockdown_state()
            if new_state == mode:
                self.log.info(f"Successfully set lockdown to {mode}")
                return True
            self.log.error(
                f"Failed to set lockdown to {mode}, current: {new_state}"
            )
            return False
        except Exception as exc:
            self.log.error(f"Error setting lockdown mode to {mode}: {exc}")
            return False

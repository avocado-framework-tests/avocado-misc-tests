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
# Copyright: 2016 IBM
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import time
import os
from avocado import Test
from avocado import main
from virttest import remote
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class KDUMP(Test):

    def run_cmd_out(self, cmd):
        return process.system_output(cmd, shell=True, ignore_status=True, sudo=True).strip()

    def setUp(self):
        sm = SoftwareManager()
        if not sm.check_installed("openssh*") and not sm.install("openssh*"):
            self.error("Fail to install openssh required for this test.")

    def test(self):
        ip = self.params.get('ip', default='')
        user_name = self.params.get('user_name', default='root')
        password = self.params.get('password', default='passw0rd')
        prompt = self.params.get('prompt', default='')
        log_file = os.path.join(self.srcdir, "file")
        session0 = remote.RemoteRunner("ssh", ip, 22, user_name, password, prompt, "\n", log_file, 100, 10, None)
        session0.run("cat /etc/os-release", 600, "True")
        if self.run_cmd_out("cat %s | grep ID | head -1 | cut -d'\"' -f2" % log_file) != "rhel":
            self.skip("Currently Test is supported only on RHEL")
        session0.run("kdumpctl status", 600, "True")
        if self.run_cmd_out("cat %s | grep -Eai 'Kdump is not operational'" % log_file):
            self.fail("Kdump is not operational")
        else:
            self.log.info("Kdump status is operational")
        session1 = remote.remote_login("ssh", ip, 22, user_name, password, prompt, "\n", None, 100, None, None, False)
        session1.sendline('echo "c" > /proc/sysrq-trigger;')
        time.sleep(600)
        self.log.info("Connecting after reboot")
        session2 = remote.RemoteRunner("ssh", ip, 22, user_name, password, prompt, "\n", log_file, 100, 10, None)
        session2.run("ls -lrt /var/crash", 100, "True")
        crash_dir = self.run_cmd_out("cat %s | grep drwxr | tail -1 | cut -d' ' -f11" % log_file)
        path_crash_dir = os.path.join("/var/crash", crash_dir)
        print path_crash_dir
        session2.run("ls -lrt %s" % path_crash_dir, 100, "True")
        if not self.run_cmd_out("cat %s | grep -Eai 'vmcore-dmesg.txt'" % log_file):
            self.fail("vmcore-dmesg.txt is not saved")
        if not self.run_cmd_out("cat %s | grep -Eai 'vmcore' | grep -Eai '\-rw-------'" % log_file):
            self.fail("vmcore is not saved")


if __name__ == "__main__":
    main()

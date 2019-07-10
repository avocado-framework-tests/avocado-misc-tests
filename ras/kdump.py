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
# Copyright: 2017 IBM
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import time
import os
import socket
from avocado import Test
from avocado import main
try:
    from virttest import remote
except ImportError:
    raise ImportError('Could not import virttest')
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class KDUMP(Test):
    '''
    Verifies if kernel dump mechanism has been enabled. Uses `linux-crashdump`.

    :avocado: tags=remote
    '''

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True, sudo=True).strip()

    def setUp(self):
        sm = SoftwareManager()
        if not sm.check_installed("openssh*") and not sm.install("openssh*"):
            self.cancel("Fail to install openssh required for this test.")
        self.ip = self.params.get('ip', default='')
        try:
            socket.inet_aton(self.ip)
        except socket.error:
            self.cancel("not ipv4 address")
        self.user_name = self.params.get('user_name')
        self.password = self.params.get('password')
        self.prompt = self.params.get('prompt', default='')

    def test(self):
        log_file = os.path.join(self.workdir, "file")
        session_int = remote.RemoteRunner("ssh", self.ip, 22, self.user_name, self.password,
                                          self.prompt, "\n", log_file, 100, 10, None)
        session_int.run("cat /etc/os-release", 600, "True")
        if "Ubuntu" in open(log_file).read():
            file_list = ['dmesg', 'dump']
            f_val = 12
            session_int.run("DEBIAN_FRONTEND=noninteractive apt-get install -y  linux-crashdump;", 600, "True")
            crashkernel_value = 'GRUB_CMDLINE_LINUX_DEFAULT=\"$GRUB_CMDLINE_LINUX_DEFAULT\
                                 crashkernel=2G-4G:320M,4G-32G:512M,32G-64G:1024M,64G-128G:2048M,128G-:4096M\"'
            cmd = "echo \'%s\' > /etc/default/grub.d/kexec-tools.cfg;" % crashkernel_value
            session_int.run(cmd, 600, "True")
            session_int.run("sudo update-grub;", 600, "True")
            session_reboot = remote.remote_login("ssh", self.ip, 22, self.user_name, self.password,
                                                 self.prompt, "\n", None, 100, None, None, False)
            session_reboot.sendline('reboot;')
            time.sleep(600)
            self.log.info("Connecting after reboot")
            session_status = remote.RemoteRunner("ssh", self.ip, 22, self.user_name, self.password,
                                                 self.prompt, "\n", log_file, 100, 10, None)
            session_status.run("kdump-config show", 600, "True")
            if self.run_cmd_out("cat %s | grep -Eai 'Not ready to'" % log_file):
                self.fail("Kdump is not operational")
            else:
                self.log.info("Kdump status is operational")
        if "rhel" in open(log_file).read():
            file_list = ['vmcore-dmesg.txt', 'vmcore']
            f_val = 11
            session_int.run("kdumpctl status", 600, "True")
            if self.run_cmd_out("cat %s | grep -Eai 'Kdump is not operational'" % log_file):
                self.fail("Kdump is not operational")
            else:
                self.log.info("Kdump status is operational")
        session_crash = remote.remote_login("ssh", self.ip, 22, self.user_name, self.password,
                                            self.prompt, "\n", None, 100, None, None, False)
        session_crash.sendline('echo 1 > /proc/sys/kernel/sysrq;')
        session_crash.sendline('echo "c" > /proc/sysrq-trigger;')
        time.sleep(600)
        self.log.info("Connecting after reboot")
        session_check = remote.RemoteRunner("ssh", self.ip, 22, self.user_name, self.password,
                                            self.prompt, "\n", log_file, 100, 10, None)
        session_check.run("ls -lrt /var/crash", 100, "True")
        crash_dir = self.run_cmd_out("cat %s | grep drwxr | tail -1 | cut -d' ' -f%s" % (log_file, f_val))
        path_crash_dir = os.path.join("/var/crash", crash_dir)
        self.log.info(path_crash_dir)
        session_check.run("ls -lrt %s" % path_crash_dir, 100, "True")
        for files in file_list:
            if files not in open(log_file).read():
                self.fail("%s is not saved" % files)


if __name__ == "__main__":
    main()

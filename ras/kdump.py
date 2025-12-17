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

import os
import socket
import logging
from avocado import Test
try:
    from virttest import remote
except ImportError:
    raise ImportError('Could not import virttest')
from avocado.utils import genio, process, wait
from avocado.utils.software_manager.manager import SoftwareManager


def remote_session_logger(log_file, message):
    """
    :param log_file: Specify the file path to write the session output logs.
    :type log_file: str
    :param message: Message received from the remote session.
    :type message: str

    :raises: Logs an error if writing to the file fails.

    :return: None
    :rtype: NoneType
    """
    try:
        genio.append_file(log_file, message + "\n")
    except Exception as e:
        logging.error(f"Failed to log message: {e}")


class KDUMP(Test):
    '''
    Verifies if kernel dump mechanism has been enabled. Uses `linux-crashdump`.

    :avocado: tags=remote
    '''

    @staticmethod
    def run_cmd_out(cmd):
        return (
            process.system_output(cmd, shell=True, ignore_status=True, sudo=True)
            .decode("utf-8")
            .strip()
        )

    def wait_for_reboot(self, log_file, timeout, interval=10):
        """
        :param log_file: Path to the session log file.
        :type log_file: str
        :param timeout: Maximum wait time for reboot in seconds.
        :type timeout: int
        :param interval: Retry interval in seconds. Defaults to 10.
        :type interval: int

        :raises: RuntimeError if the host is unreachable within the timeout.

        :return: SSH session object upon successful login.
        :rtype: remote.RemoteRunner
        """
        def check_reboot():
            try:
                session = remote.RemoteRunner(
                    "ssh", self.ip, 22, self.user_name, self.password,
                    self.prompt, "\n", log_file, 30, 5, None,
                    "password", remote_session_logger
                )
                return session
            except Exception as e:
                self.log.debug(f"Still waiting for host: {e}")
                return None

        session = wait.wait_for(check_reboot, first=interval, timeout=timeout, step=interval)
        if session is None:
            raise RuntimeError("Timeout Expired or system is unreachable.")
        return session

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
        self.timeout = self.params.get('reboot_timeout', default=600)
        self.sessions = []

    def test(self):
        log_file = os.path.join(self.workdir, "file")
        session_int = remote.RemoteRunner(
            "ssh", self.ip, 22, self.user_name, self.password, self.prompt, "\n",
            log_file, 100, 10, None, "password", remote_session_logger
        )
        self.sessions.append(session_int)
        session_int.run("cat /etc/os-release", 600, "True")
        if "Ubuntu" in open(log_file).read():
            file_list = ['dmesg', 'dump']
            session_int.run("DEBIAN_FRONTEND=noninteractive apt-get install -y  linux-crashdump;", 600, "True")
            crashkernel_value = 'GRUB_CMDLINE_LINUX_DEFAULT=\"$GRUB_CMDLINE_LINUX_DEFAULT\
                crashkernel=2G-4G:320M,4G-32G:512M,32G-64G:1024M,64G-128G:2048M,128G-:4096M\"'
            cmd = "echo \'%s\' > /etc/default/grub.d/kexec-tools.cfg;" % crashkernel_value
            session_int.run(cmd, 600, "True")
            session_int.run("sudo update-grub;", 600, "True")
            session_reboot = remote.remote_login(
                "ssh", self.ip, 22, self.user_name, self.password, self.prompt, "\n", log_file, remote_session_logger
            )
            self.sessions.append(session_reboot)
            session_reboot.sendline('reboot;')
            try:
                session_status = self.wait_for_reboot(log_file, self.timeout)
                self.sessions.append(session_status)
            except RuntimeError as e:
                self.fail(f"Reboot after kdump setup failed: {e}")
            self.log.info("Connecting after reboot")
            session_status = remote.RemoteRunner(
                "ssh", self.ip, 22, self.user_name, self.password, self.prompt, "\n",
                log_file, 100, 10, None, "password", remote_session_logger
            )
            self.sessions.append(session_status)
            session_status.run("kdump-config show", 600, "True")
            if self.run_cmd_out("cat %s | grep -Eai 'Not ready to'" % log_file):
                self.fail("Kdump is not operational")
            else:
                self.log.info("Kdump status is operational")
        if "rhel" in open(log_file).read():
            file_list = ['vmcore-dmesg.txt', 'vmcore']
            session_int.run("kdumpctl status", 600, "True")
            if self.run_cmd_out("cat %s | grep -Eai 'Kdump is not operational'" % log_file):
                self.fail("Kdump is not operational")
            else:
                self.log.info("Kdump status is operational")
        session_crash = remote.remote_login(
            "ssh", self.ip, 22, self.user_name, self.password,
            self.prompt, "\n", log_file, remote_session_logger)
        self.sessions.append(session_crash)
        session_crash.sendline('echo 1 > /proc/sys/kernel/sysrq;')
        session_crash.sendline('echo "c" > /proc/sysrq-trigger;')
        try:
            session_check = self.wait_for_reboot(log_file, self.timeout)
            self.sessions.append(session_check)
        except RuntimeError as e:
            self.fail(f"Reboot after crash trigger failed: {e}")
        self.log.info("Connecting after reboot")
        session_check = remote.RemoteRunner(
            "ssh", self.ip, 22, self.user_name, self.password, self.prompt, "\n",
            log_file, 100, 10, None, "password", remote_session_logger
        )
        self.sessions.append(session_check)
        session_check.run("ls -lrt /var/crash", 100, "True")
        crash_dir = genio.read_line_with_matching_pattern(log_file, r'drwxr')[-1].strip() \
            .split()[-1]
        path_crash_dir = os.path.join("/var/crash", crash_dir)
        self.log.info(path_crash_dir)
        session_check.run("ls -lrt %s" % path_crash_dir, 100, "True")
        for files in file_list:
            if files not in open(log_file).read():
                self.fail("%s is not saved" % files)

    def tearDown(self):
        """
        Close all active remote sessions after test execution.
        """
        for runner in self.sessions:
            try:
                (getattr(runner, "session", runner)).close()
            except Exception as e:
                self.log.error(f"Failed to close session {runner}: {e}")
        self.sessions.clear()

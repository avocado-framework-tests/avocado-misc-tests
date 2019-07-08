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
# Copyright: 2018 IBM
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
        self.ip = self.params.get('ip')
        try:
            socket.inet_aton(self.ip)
        except socket.error:
            self.cancel("not ipv4 address")
        self.ip_server = self.params.get('ip_server')
        try:
            socket.inet_aton(self.ip_server)
        except socket.error:
            self.cancel("not ipv4 address")
        self.user_name = self.params.get('user_name', default='root')
        self.password = self.params.get('password', default="passw0rd")
        self.prompt = self.params.get('prompt', default='~]#')
        self.user_name_server = self.params.get('user_name_server', default='root')
        self.password_server = self.params.get('password_server', default="passw0rd")
        self.prompt_server = self.params.get('prompt_server', default='~]#')
        self.nfs_path = self.params.get('nfs_path', default='/home/mnt/testarea/nfs')

    def configure_kdump(self):
        log_file_init = os.path.join(self.workdir, "file1")
        session_int = remote.RemoteRunner("ssh", self.ip, 22, self.user_name, self.password,
                                          self.prompt, "\n", log_file_init, 100, 10, None)
        session_int.run("cat /etc/os-release", 20, "True")

        if "Ubuntu" in open(log_file_init).read():
            self.distro = "Ubuntu"
            self.file_list = ['dmesg', 'dump']
            session_int.run("DEBIAN_FRONTEND=noninteractive apt-get install -y  linux-crashdump;", 600, "True")
            crashkernel_value = 'GRUB_CMDLINE_LINUX_DEFAULT=\"$GRUB_CMDLINE_LINUX_DEFAULT\
                                 crashkernel=2G-4G:320M,4G-32G:512M,32G-64G:1024M,64G-128G:2048M,128G-:4096M\"'
            cmd = "echo \'%s\' > /etc/default/grub.d/kexec-tools.cfg;" % crashkernel_value
            session_int.run(cmd, 60, "True")
            session_int.run("sudo update-grub;", 600, "True")
            session_reboot = remote.remote_login("ssh", self.ip, 22, self.user_name, self.password,
                                                 self.prompt, "\n", None, 100, None, None, False)
            session_reboot.sendline('reboot;')
            time.sleep(600)
            self.log.info("Connecting after reboot")
            session_status = remote.RemoteRunner("ssh", self.ip, 22, self.user_name, self.password,
                                                 self.prompt, "\n", log_file_init, 100, 10, None)
            session_status.run("kdump-config show", 60, "True")
            if self.run_cmd_out("cat %s | grep -Eai 'Not ready to'" % log_file_init):
                self.fail("Kdump is not operational")
            else:
                self.log.info("Kdump status is operational")
            session_status.session.kill()
        if "rhel" in open(log_file_init).read():
            self.distro = "rhel"
            self.file_list = ['vmcore-dmesg.txt', 'vmcore']
            session_int.run("kdumpctl status", 60, "True")
            if self.run_cmd_out("cat %s | grep -Eai 'Kdump is not operational'" % log_file_init):
                self.fail("Kdump is not operational")
            else:
                self.log.info("Kdump status is operational")

    def configure_nfs(self):
        log_file_nfs = os.path.join(self.workdir, "file2")
        session_nfs = remote.RemoteRunner("ssh", self.ip, 22, self.user_name, self.password,
                                          self.prompt, "\n", log_file_nfs, 100, 10, None)
        session_nfs.run("cat /etc/os-release", 20, "True")
        if self.distro == "Ubuntu":
            session_nfs.run("apt-get install -y nfs-common;", 60, "True")
            session_nfs.run("apt-get install -y nfs-kernel-server;", 60, "True")
            session_nfs.run("service nfs-server start;", 60, "True")
            session_nfs.run("echo 'NFS=\"%s:%s\"' >> /etc/default/kdump-tools;" % (self.ip_server, self.nfs_path), 60, "True")
            session_nfs.run("mount -t nfs %s:%s /var/crash;" % (self.ip_server, self.nfs_path), 60, "True")
            session_nfs.run("kdump-config unload;", 60, "True")
            session_nfs.run("kdump-config load;", 60, "True")
            session_nfs.run("sed -i '$d' /etc/default/kdump-tools;", 60, "True")
            session_nfs.run("kdump-config show", 60, "True")
            if self.run_cmd_out("cat %s | grep -Eai 'Not ready to'" % log_file_nfs):
                self.fail("Kdump is not operational after configuring nfs")
            else:
                self.log.info("Kdump status is operational after configuring nfs")
        if self.distro == "rhel":
            session_nfs.run("yum -y install nfs-utils;", 60, "True")
            session_nfs.run("service nfs start;", 60, "True")
            session_nfs.run("cp -f /etc/kdump.conf /etc/kdump.conf.tmp;", 60, "True")
            session_nfs.run("echo 'nfs %s:%s' >> /etc/kdump.conf;" % (self.ip_server, self.nfs_path), 60, "True")
            session_nfs.run("sed -i 's/-l --message-level/-l -F --message-level/' /etc/kdump.conf;", 60, "True")
            session_nfs.run("mount -t nfs %s:%s /var/crash;" % (self.ip_server, self.nfs_path), 60, "True")
            session_nfs.run("kdumpctl restart;", 60, "True")
            session_nfs.run("mv -f /etc/kdump.conf.tmp /etc/kdump.conf;", 60, "True")
            session_nfs.run("kdumpctl status", 60, "True")
            if self.run_cmd_out("cat %s | grep -Eai 'Kdump is not operational'" % log_file_nfs):
                self.fail("Kdump is not operational after configuring nfs")
            else:
                self.log.info("Kdump status is operational after configuring nfs")

    def test(self):
        log_file_server = os.path.join(self.workdir, "file_server")
        self.configure_kdump()
        self.configure_nfs()
        session_check = remote.RemoteRunner("ssh", self.ip_server, 22, self.user_name_server, self.password_server,
                                            self.prompt_server, "\n", log_file_server, 100, 10, None)
        session_check.run("date +%s", 100, "True")
        time_init = self.run_cmd_out("cat %s | tail -3 | head -1 | cut -d' ' -f3" % log_file_server).strip()
        session_crash = remote.remote_login("ssh", self.ip, 22, self.user_name, self.password,
                                            self.prompt, "\n", None, 100, None, None, False)
        session_crash.sendline('echo 1 > /proc/sys/kernel/sysrq;')
        session_crash.sendline('echo "c" > /proc/sysrq-trigger;')
        time.sleep(300)
        self.log.info("Connecting to nfs server")
        session_check = remote.RemoteRunner("ssh", self.ip_server, 22, self.user_name_server, self.password_server,
                                            self.prompt_server, "\n", log_file_server, 100, 10, None)
        if self.distro == "rhel":
            nfs_dir_path = os.path.join(self.nfs_path, "var", "crash")
        self.log.info(nfs_dir_path)
        session_check.run("ls -lrt %s;" % nfs_dir_path, 100, "True")
        crash_dir = self.run_cmd_out("cat %s | grep drwxr | awk '{print $NF}' | tail -1" % log_file_server)
        path_crash_dir = os.path.join(nfs_dir_path, crash_dir)
        session_check.run("stat -c%%Z %s" % path_crash_dir, 100, "True")
        time_created = self.run_cmd_out("cat %s | tail -3 | head -1 | cut -d' ' -f3" % log_file_server).strip()
        if time_created < time_init:
            self.fail("Dump is not saved in ssh server")
        session_check.run("ls -lrt %s" % path_crash_dir, 100, "True")
        for files in self.file_list:
            if files not in open(log_file_server).read():
                self.fail("%s is not saved" % files)


if __name__ == "__main__":
    main()

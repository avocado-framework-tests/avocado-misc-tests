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
import re
import tempfile
import shutil
from threading import Thread

from avocado import Test
from avocado import skipIf
from avocado.utils import process, cpu, genio
from avocado.utils import distro
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()


class Sosreport(Test):

    def run_cmd(self, cmd, verbose=True):
        self.log.info("executing ============== %s =================", cmd)
        if process.system(cmd, verbose=verbose, ignore_status=True, sudo=True):
            self.log.info("%s command failed", cmd)
            self.is_fail += 1
        return

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def run_cmd_search(self, cmd, search_str):
        self.output = self.run_cmd_out(cmd)
        for line in reversed(self.output.splitlines()):
            if search_str in line:
                return line.strip()

    def setUp(self):
        dist = distro.detect()
        sm = SoftwareManager()
        sos_pkg = ""
        self.sos_cmd = ""
        if dist.name in ['Ubuntu', 'debian']:
            sos_pkg = 'sosreport'
            self.sos_cmd = "sosreport"
        elif dist.name in ['rhel', 'centos', 'fedora']:
            sos_pkg = 'sos'
            self.sos_cmd = "sos report"
            if dist.name == "rhel" and int(dist.version) <= 7 and int(dist.release) <= 4:
                self.sos_cmd = "sosreport"
        else:
            self.cancel("sosreport is not supported on %s" % dist.name)
        for package in (sos_pkg, 'java'):
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel(
                    "Package %s is missing and could not be installed" % (package))

    def test_short(self):
        """
        execute basic tests:
        - help
        - list available plugins
        - capture enable plugins data
        - case-id
        """
        self.log.info(
            "===========Executing sosreport tool test (short)===========")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        self.run_cmd("%s -h" % self.sos_cmd, False)
        self.run_cmd("%s -l" % self.sos_cmd, False)
        self.run_cmd("%s --batch --tmp-dir=%s --verify" %
                     (self.sos_cmd, directory_name))
        case_id = self.params.get('case_id', default='testid')
        output = self.run_cmd_out("%s --batch --case-id=%s"
                                  % (self.sos_cmd, case_id))
        for line in output.splitlines():
            # Expecting case_id in the line
            if 'tar.xz' in line and case_id not in line:
                self.is_fail += 1
                self.log.info("--case-id option failed")

        output = self.run_cmd_out("%s --batch --tmp-dir=%s --label=testname"
                                  % (self.sos_cmd, directory_name))
        for line in output.splitlines():
            # Expecting 'testname' in the line
            if 'tar.xz' in line and 'testname' not in line:
                self.is_fail += 1
                self.log.info("--label option failed")

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test_user(self):
        """
        execute more tests:
        - capture user provided information
        """
        self.log.info(
            "============Executing sosreport tool test (User)============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        list = self.params.get('list', default=['--all-logs'])
        for list_item in list:
            cmd = "%s --batch --tmp-dir=%s %s" % (
                self.sos_cmd, directory_name, list_item)
            self.run_cmd(cmd)

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test_plugins(self):
        """
        execute different plugin options:
        - skip plugin
        - enable plugin
        - only plugin
        """
        self.log.info(
            "===============Executing sosreport tool test (plugins)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0

        output = self.run_cmd_search("%s --batch --tmp-dir=%s -n libraries"
                                     % (self.sos_cmd, directory_name),
                                     'libraries')
        # Not expecting 'libraries' in the output
        if output:
            self.is_fail += 1
            self.log.info("--skip-plugins option failed")

        self.run_cmd("%s --batch --tmp-dir=%s -e ntp,numa,snmp" %
                     (self.sos_cmd, directory_name))
        output = self.run_cmd_search("%s --batch --tmp-dir=%s -e sendmail"
                                     % (self.sos_cmd, directory_name),
                                     'sendmail')
        # Expecting 'sendmail' in the output
        if not output:
            self.is_fail += 1
            self.log.info("--enable-plugins option failed")

        output = self.run_cmd_search("%s --batch --tmp-dir=%s -o cups"
                                     % (self.sos_cmd, directory_name),
                                     'cups')
        # Expecting 'cups' in the output
        if not output:
            self.is_fail += 1
            self.log.info("--only-plugins option failed")

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test_others(self):
        """
        execute options:
        - list profiles
        - capture profile
        - build (doesn't archives copied data)
        - quiet
        - debug
        - tmp dir
        - no-report
        - sysroot
        """
        self.log.info(
            "===============Executing sosreport tool test (others)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        self.run_cmd("%s --list-profiles" % self.sos_cmd, None)
        self.run_cmd("%s --batch --tmp-dir=%s -p boot,memory" %
                     (self.sos_cmd, directory_name))

        output = self.run_cmd_search("%s --batch --tmp-dir=%s -p webserver"
                                     % (self.sos_cmd, directory_name), 'java')
        # Expecting 'java' in the output
        if not output:
            self.is_fail += 1
            self.log.info("--profile option failed")

        dir_name = self.run_cmd_search(
            "%s --batch --tmp-dir=%s --build" % (self.sos_cmd, directory_name), directory_name)
        if not os.path.isdir(dir_name):
            self.is_fail += 1
            self.log.info("--build option failed")

        if "version" not in self.run_cmd_out("%s --batch --tmp-dir=%s --quiet "
                                             "--no-report -e ntp,numa1"
                                             % (self.sos_cmd, directory_name)):
            self.is_fail += 1
            self.log.info("--quiet --no-report option failed")
        self.run_cmd("%s --batch --tmp-dir=%s --debug" %
                     (self.sos_cmd, directory_name), None)

        file_name = self.run_cmd_search(
            "%s --batch --tmp-dir=%s" % (self.sos_cmd, directory_name), directory_name)
        if not os.path.exists(file_name):
            self.is_fail += 1
            self.log.info("--tmp-dir option failed")

        dir_name = self.run_cmd_search(
            "%s --no-report --batch --build" % self.sos_cmd, '/var/tmp/sosreport')
        if os.listdir(dir_name) == []:
            self.is_fail += 1
            self.log.info("--no-report option failed")
        if 'powerpc' in cpu.get_arch():
            file_list = self.params.get('file_list', default=['proc/device-tree/'])
            for files in file_list:
                file_path = os.path.join(dir_name, files)
                if not os.path.exists(file_path):
                    self.is_fail += 1
                    self.log.info("%s file/directory not created" % file_path)

        self.run_cmd("%s --batch --tmp-dir=%s -s /" %
                     (self.sos_cmd, directory_name))

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test_archive(self):
        """
        execute archive options:
        - gzip
        - xz
        - auto
        - md5 check
        """
        self.log.info(
            "===============Executing sosreport tool test (Archive)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        f_name = {'gzip': 'file_name_gz',
                  'xz': 'file_name_xz', 'auto': 'file_name_xz2'}
        archive = {'gzip': 'tar.gz',
                   'xz': 'tar.xz', 'auto': 'tar.xz'}
        for key, value in f_name.items():
            file_name = str(f_name[key])
            output = self.run_cmd_out("%s --batch --tmp-dir=%s -z %s"
                                      % (self.sos_cmd, directory_name, str(key)))
            for line in output.splitlines():
                if str(archive[key]) in line:
                    file_name = line.strip()
                    break
            if not os.path.exists(file_name):
                self.is_fail += 1
                self.log.info("-z %s option failed" % str(key))
            elif file_name is not "file_name_xz2":
                os.remove(file_name)

        if os.path.exists(file_name):
            md5_sum1 = self.run_cmd_out("cat %s.md5" % file_name).strip()
            md5_sum2 = self.run_cmd_out("md5sum %s" % file_name).strip().split()[0]
            if md5_sum1 != md5_sum2:
                self.is_fail += 1
                self.log.info("md5sum check failed")
            os.remove(file_name)

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    @skipIf("ppc" not in os.uname()[4], "Skip, Powerpc specific tests")
    def test_PPC(self):
        self.log.info(
            "===============Executing sosreport tool test (PPC)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        self.run_cmd("%s --batch --tmp-dir=%s -o "
                     "pci,powerpc,process,processor,kdump" % (self.sos_cmd, directory_name))
        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    @skipIf("ppc" not in os.uname()[4], "Skip, Powerpc specific tests")
    def test_smtchanges(self):
        """
        Test the sosreport with different smt levels
        """
        self.is_fail = 0
        directory_name = tempfile.mkdtemp()
        for i in [2, 4, 8, "off"]:
            self.run_cmd("ppc64_cpu --smt=%s" % i)
            smt_initial = re.split(
                r'=| is ', self.run_cmd_out("ppc64_cpu --smt"))[1]
            if smt_initial == str(i):
                self.run_cmd("%s --batch --tmp-dir=%s --all-logs" %
                             (self.sos_cmd, directory_name))
            else:
                self.is_fail += 1
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    @skipIf("ppc" not in os.uname()[4], "Skip, Powerpc specific tests")
    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_dlpar_cpu_hotplug(self):
        """
        Test the sos report after cpu hotplug
        """
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        self.run_cmd("ppc64_cpu --smt=on")
        if "cpu_dlpar=yes" in process.system_output("drmgr -C",
                                                    ignore_status=True,
                                                    shell=True).decode("utf-8"):
            output = self.run_cmd_search("lparstat -i", 'Online Virtual CPUs')
            lcpu_count = output.split(":")[1].strip()
            if lcpu_count:
                lcpu_count = int(lcpu_count)
                if lcpu_count >= 2:
                    self.run_cmd("drmgr -c cpu -r -q 1")
                    self.run_cmd("drmgr -c cpu -a -q 1")
                    self.run_cmd("%s --batch --tmp-dir=%s --all-logs" %
                                 (self.sos_cmd, directory_name))
                else:
                    self.is_fail += 1
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    @skipIf("ppc" not in os.uname()[4], "Skip, Powerpc specific tests")
    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_dlpar_mem_hotplug(self):
        """
        Test the sos report after mem hotplug
        """
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        if "mem_dlpar=yes" in process.system_output("drmgr -C",
                                                    ignore_status=True,
                                                    shell=True).decode("utf-8"):
            output = self.run_cmd_search("lparstat -i", 'Online Memory')
            mem_count = output.split(":")[1].split()[0].strip()
            if mem_count:
                mem_count = int(mem_count)
                if mem_count > 512000:
                    self.run_cmd("drmgr -c mem -r -q 2")
                    self.run_cmd("drmgr -c mem -a -q 2")
                    self.run_cmd("%s --batch --tmp-dir=%s --all-logs" %
                                 (self.sos_cmd, directory_name))
                else:
                    self.is_fail += 1
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test(self):
        workload_thread = Thread(target=self.run_workload)
        workload_thread.start()
        sos_thread = Thread(target=self.test_user)
        sos_thread.start()
        workload_thread.join()
        sos_thread.join()

    def run_workload(self):
        online_cpus = cpu.online_list()[1:]
        for i in online_cpus:
            cpu_file = "/sys/bus/cpu/devices/cpu%s/online" % i
            genio.write_one_line(cpu_file, "0")
            genio.write_one_line(cpu_file, "1")

    def test_fs(self):
        is_fail = 0
        loop_dev = process.system_output('losetup -f').decode("utf-8").strip()
        fstype = self.params.get('fs', default='ext4')
        mnt = self.params.get('dir', default=None)
        if not mnt:
            mnt = self.workdir
        if 'blockfile' not in self.run_cmd_out("ls /tmp"):
            blk_dev = process.run("dd if=/dev/zero of=/tmp/blockfile bs=1M count=5120")
            process.run("losetup %s /tmp/blockfile" % loop_dev)
        if fstype == "ext4":
            cmd = "mkfs.%s %s" % (fstype, loop_dev)
        else:
            cmd = "mkfs.%s -f %s" % (fstype, loop_dev)
        process.run(cmd)
        process.run("mount %s %s" % (loop_dev, mnt))
        self.run_cmd("%s --batch --tmp-dir=%s --all-logs" %
                     (self.sos_cmd, mnt))
        process.run("umount %s" % loop_dev)
        if 'blockfile' in self.run_cmd_out("ls /tmp"):
            process.run("losetup -d %s" % loop_dev)
            if os.path.exists("/tmp/blockfile"):
                os.remove("/tmp/blockfile")
        if is_fail:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % is_fail)

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
# Author: Basheer Khadarsabgari <basheer@linux.vnet.ibm.com>

import os
import re
import shutil
from threading import Thread

from avocado import Test
from avocado import skipIf
from avocado.utils import process, cpu, genio
from avocado.utils import distro
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()


class Supportconfig(Test):
    """
    The supportconfig script gathers system troubleshooting information on
    SUSE Linux Enterprise Server systems.It captures the current system
    environment and generates a tar-archive.

    The script file collects complementary information to the dbginfo.sh
    script. The supportconfig script is part of the Supportutils package.
    """

    def setUp(self):
        """
        Install all the dependency packages required for Test.
        """
        sm = SoftwareManager()

        if "SuSE" not in distro.detect().name:
            self.cancel("supportconfig is supported on the SuSE Distro only.")

        pkgs = ["supportutils", "psmisc"]

        for pkg in pkgs:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.cancel(
                    "Package %s is missing/could not be installed" % pkg)

    def test_supportconfig_options(self):
        """
        Test the supportconfig options:
        Use the minimal option (-m):supportconfig -m
        Limiting the Information to a Specific Topic: supportconfig -i LVM
        List of feature keywords: supportconfig -F
        Collecting already Rotated Log Files: supportconfig -l
        """
        # verify the normal functionality of the supportconfig
        ret = process.run("supportconfig",
                          sudo=True,
                          ignore_status=True)
        logfile = re.search(r"Log file tar ball: (\S+)\n",
                            ret.stdout.decode("utf-8")).group(1)
        if not os.path.exists(logfile) or ret.exit_status:
            self.fail("supportconfig failed to create log file")

        options_to_verify = self.params.get('supportconfig_opt', default="m")
        feature = self.params.get('feature', default="AUTOFS")
        for option in options_to_verify:
            if option == "i":
                self.log.info("Limiting the Information to a Specific feature")
                ret = process.run("supportconfig -%s %s" % (option, feature),
                                  sudo=True,
                                  ignore_status=True)
                if not re.search(r"%s...\s*Done" % feature, ret.stdout.decode("utf-8")) \
                   or ret.exit_status:
                    self.fail(
                        "Failed to verify the %s feature using supportconfig" %
                        feature)
            elif option == "R":
                self.log.info(
                    "Changing default directory path for supportconfig" +
                    " output files")
                ret = process.run("supportconfig -%s %s" %
                                  (option, self.workdir),
                                  sudo=True,
                                  ignore_status=True)
                if self.workdir not in ret.stdout.decode("utf-8") or ret.exit_status:
                    self.fail(
                        "Failed to change the supportconfig output" +
                        " files directory")
            else:
                self.log.info("verifying %s option of supportconfig" % option)
                ret = process.system("supportconfig -%s" % option,
                                     sudo=True,
                                     ignore_status=True)
                if ret:
                    self.fail(
                        "supportconfig %s option failed with %s exit option" %
                        (option, ret))

    def test_enable_disable_plugins(self):
        """
        1.create the /usr/lib/supportconfig/plugins
        2.copy your script file there
        3.output will be in the plugin-plugin_name.txt file
        """
        plugin_dir = "/usr/lib/supportconfig/plugins"
        plugin_dir_exists = 1
        if not os.path.exists(plugin_dir):
            plugin_dir_exists = 0
            os.mkdir(plugin_dir)
        # copy the plugin file
        plugin_name = '/usr/bin/pstree'
        shutil.copy(plugin_name, plugin_dir)
        ret = process.run("supportconfig",
                          sudo=True,
                          ignore_status=True)
        logfile = re.search(r"Log file tar ball: (\S+)\n",
                            ret.stdout.decode("utf-8")).group(1)
        res = process.system("tar -tvf %s | grep 'plugin-pstree.txt'"
                             % logfile,
                             ignore_status=True,
                             shell=True)
        if ret.exit_status or res:
            self.fail("support failed to execute plugin")
        # disable a plugin
        ret = process.run("supportconfig -p",
                          sudo=True,
                          ignore_status=True)
        logfile = re.search(r"Log file tar ball: (\S+)\n",
                            ret.stdout.decode("utf-8")).group(1)
        res = process.system("tar -tvf %s | grep 'plugin-pstree.txt'"
                             % logfile,
                             ignore_status=True,
                             shell=True)
        if ret.exit_status or not res:
            self.fail("support failed to disable plugin")

        # cleanup the plugin dir
        if not plugin_dir_exists:
            process.system("rm -rf %s" % plugin_dir)

    def test_smtchanges(self):
        """
        Test the supportconfig with different smt levels
        """
        self.is_fail = 0
        for i in [2, 4, 8, "off"]:
            process.run("ppc64_cpu --smt=%s" % i)
            smt_initial = re.split(r'=| is ', process.system_output("ppc64_cpu --smt")
                                   .decode('utf-8'))[1]
            if smt_initial == str(i):
                process.run("supportconfig", sudo=True, ignore_status=True)
            else:
                self.is_fail += 1
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_dlpar_cpu_hotplug(self):
        """
        Test the supportconfig after cpu hotplug
        """
        self.is_fail = 0
        process.run("ppc64_cpu --smt=on")
        if "cpu_dlpar=yes" in process.system_output("drmgr -C",
                                                    ignore_status=True,
                                                    shell=True).decode("utf-8"):
            lcpu_count = process.system_output("lparstat -i | "
                                               "grep \"Online Virtual CPUs\" | "
                                               "cut -d':' -f2",
                                               ignore_status=True,
                                               shell=True).decode("utf-8")
            if lcpu_count:
                lcpu_count = int(lcpu_count)
                if lcpu_count >= 2:
                    process.run("drmgr -c cpu -r 1")
                    process.run("drmgr -c cpu -a 1")
                    process.run("supportconfig", sudo=True, ignore_status=True)
                else:
                    self.is_fail += 1
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_dlpar_mem_hotplug(self):
        """
        Test the supportconfig after mem hotplug
        """
        self.is_fail = 0
        if "mem_dlpar=yes" in process.system_output("drmgr -C",
                                                    ignore_status=True,
                                                    shell=True).decode("utf-8"):
            mem_value = process.system_output("lparstat -i | "
                                              "grep \"Online Memory\" | "
                                              "cut -d':' -f2",
                                              ignore_status=True,
                                              shell=True).decode("utf-8")
            mem_count = re.split(r'\s', mem_value)[1]
            if mem_count:
                mem_count = int(mem_count)
                if mem_count > 512000:
                    process.run("drmgr -c mem -r 2")
                    process.run("drmgr -c mem -a 2")
                    process.run("supportconfig", sudo=True, ignore_status=True)
                else:
                    self.is_fail += 1
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test(self):
        workload_thread = Thread(target=self.run_workload)
        workload_thread.start()
        support_thread = Thread(target=self.run_supportconfig)
        support_thread.start()
        workload_thread.join()
        support_thread.join()

    def run_workload(self):
        online_cpus = cpu.online_list()[1:]
        for i in online_cpus:
            cpu_file = "/sys/bus/cpu/devices/cpu%s/online" % i
            genio.write_one_line(cpu_file, "0")
            genio.write_one_line(cpu_file, "1")

    def run_supportconfig(self):
        self.is_fail = 0
        process.run("supportconfig", sudo=True, ignore_status=True)
        if self.is_fail >= 1:
            self.fail(
                "%s command(s) failed in sosreport tool verification" % self.is_fail)

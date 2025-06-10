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
# Copyright: 2020 IBM.
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
import configparser
import glob
import random
from avocado import Test
from avocado.utils import cpu, dmesg, genio, linux_modules, process
from avocado import skipIf, skipUnless

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')
IS_KVM_GUEST = 'qemu' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class PerfBasic(Test):

    """
    Performance analysis tools for Linux
    :avocado: tags=privileged,perf,pmu

    execute basic Performance Monitoring Unit(PMU) test cases:
    1. Check whether PMU registered or not
    """

    def _process_lscpu(self):
        output = process.system_output("lscpu", shell=True, ignore_status=True)
        for line in output.decode().splitlines():
            self.total_cpus = cpu.total_count()
            self.online_cpus = cpu.online_list()
            if 'Model name:' in line:
                self.model = line.split(':')[1].split('(')[0].strip().lower()
                self.log.info("CPU model %s" % self.model)
            if 'Physical chips:' in line:
                self.pchips = int(line.split(':')[1].strip())
                self.log.info("Physical Chips %s" % self.pchips)
            if 'Physical sockets:' in line:
                self.psockets = int(line.split(':')[1].strip())
                self.log.info("Physical Sockets %s" % self.psockets)
            if 'Physical cores/chip:' in line:
                self.pcorechips = int(line.split(':')[1].strip())
                self.log.info("Physical cores/chip %s" % self.pcorechips)
            nodesysfs = '/sys/devices/system/node/'
            for nodefile in os.listdir(nodesysfs):
                if 'node' in nodefile:
                    filename = os.path.join(nodesysfs, nodefile, 'cpulist')
                    self.node_cpu_dict[nodefile] = genio.read_file(filename)
                    self.log.info("Nodes and CPU list: %s" %
                                  self.node_cpu_dict)

    def setUp(self):
        self.pmu_list = []
        self.node_cpu_dict = {}
        self.total_cpus = self.online_cpus = self.pchips = self.psockets = 0
        self.pcorechips = 0
        self.model = ""
        self._process_lscpu()

    def _create_temp_user(self):
        # This function adds a temporary user required for testing
        if process.system('getent group test_pmu', ignore_status=True):
            process.run('groupadd test_pmu', sudo=True)
        if process.system('getent passwd test_pmu', ignore_status=True):
            process.run(
                'useradd -g test_pmu -m -d /home/test_pmu test_pmu',
                sudo=True, ignore_status=True)
        if not process.system('id test_pmu', sudo=True, ignore_status=True):
            process.run('usermod -a -G test_pmu test_pmu', sudo=True)

    def _remove_temp_user(self):
        # Remove the temporary user added for testing
        if not process.system('id test_pmu', sudo=True, ignore_status=True):
            process.system('userdel -r test_pmu', sudo=True,
                           ignore_status=True)

    def get_random_filenames(self, directory, num_files=3):
        files = os.listdir(directory)
        random_files = random.sample(files, num_files)
        return random_files

    def _check_kernel_config(self, config_option):
        # This function checks the kernel configuration with the input
        # 'config_option' a string. If the required configuration not set then
        # test gets cancelled.
        ret = linux_modules.check_kernel_config(config_option)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.cancel("%s not set." % config_option)

    def _check_file_existence(self, filelist, listdir):
        not_found_list = []
        for files in filelist:
            if files not in listdir:
                not_found_list.append(files)
        if not_found_list:
            self.fail('For %s, Not found files are %s' % (self.model,
                                                          not_found_list))

    def test_config_PMU_sysfs(self):
        # This function checks for a kernel configuration option named
        # CONFIG_PMU_SYSFS. If set then checks for file named 'mmcra' in the
        # sysfs directory and access the file using super user as well as a
        # normal user with out super user privileges.
        self._check_kernel_config('CONFIG_PMU_SYSFS')

        sysfs_file = "/sys/devices/system/cpu/cpu0/"

        parser = configparser.ConfigParser()
        parser.read(self.get_data('sysfs_PMU.cfg'))
        sysfs_PMU_list = parser.get(self.model, 'dir_list').split(',')
        # Check for any missing files according to the model
        self._check_file_existence(sysfs_PMU_list, os.listdir(sysfs_file))

        try:
            for filename in glob.glob("%smmcr*" % sysfs_file):
                os.stat(filename)
        except PermissionError:
            self.fail("Unable to read mmcr* files as super user.")

        self._create_temp_user()
        if not process.system('id test_pmu', sudo=True, ignore_status=True):
            result = process.run("su - test_pmu -c 'cat %smmcr*'" % sysfs_file,
                                 shell=True, ignore_status=True)
            output = result.stdout.decode() + result.stderr.decode()
            self._remove_temp_user()
            if 'Permission denied' not in output:
                self.fail("Able to read mmcr* files as normal user.")
        else:
            self.log.warn('User test_pmu does not exist, skipping test')

    def _verify_lscpu_sysfs(self, filename, value_to_verify):
        output = int(genio.read_file(filename))
        if not value_to_verify == output:
            self.fail("lscpu output %s, sysfs value = %s not matched for %s"
                      % (value_to_verify, output, filename))

    def _verify_lscpu_sysfs_test(self, cmd, value_to_verify):
        output = process.system_output(cmd, shell=True,
                                       ignore_status=True).decode()
        if not value_to_verify == int(output):
            self.fail("lscpu output %s, sysfs value = %s not matched for %s"
                      % (value_to_verify, output, cmd))

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is for PowerVM")
    def test_config_PPC_RTAS(self):
        # This function checks for a kernel configuration option named
        # CONFIG_PPC_RTAS. If set then checks for files namely sockets,
        # chips.
        self._check_kernel_config('CONFIG_PPC_RTAS')
        sysfs_file = "/sys/devices/hv_24x7/interface/"
        files = os.listdir(sysfs_file)
        if not ('sockets' in files and 'chipspersocket' in files and
                'coresperchip' in files):
            self.fail('Required sysfs files "sockets, coresperchip,\
                      chipspersocket" not found.')

        self._verify_lscpu_sysfs('%ssockets' % sysfs_file, self.psockets)
        self._verify_lscpu_sysfs('%schipspersocket' % sysfs_file, self.pchips)
        self._verify_lscpu_sysfs('%scoresperchip' %
                                 sysfs_file, self.pcorechips)

        self._create_temp_user()
        if not process.system('id test_pmu', sudo=True, ignore_status=True):
            user_cmd = "su - test_pmu -c"
            self._verify_lscpu_sysfs_test("%s 'cat %ssockets'"
                                          % (user_cmd, sysfs_file),
                                          self.psockets)
            self._verify_lscpu_sysfs_test("%s 'cat %schipspersocket'"
                                          % (user_cmd, sysfs_file),
                                          self.pchips)
            self._verify_lscpu_sysfs_test("%s 'cat %scoresperchip'"
                                          % (user_cmd, sysfs_file),
                                          self.pcorechips)
            self._remove_temp_user()
        else:
            self.log.warn('User test_pmu does not exist, skipping test')

        if self.pchips == "1" and self.psockets == "1" and self.pcorechips == "1":
            output = dmesg.collect_errors_dmesg(
                'rtas error: Error calling get-system-parameter')
            if len(output):
                self.fail("RTAS error occurred")

    def _check_count(self, event_type):
        base_dir = "/sys/bus/event_source/devices/"
        if not os.path.isdir(base_dir):
            self.fail("sysfs events folder not found")

        if not os.path.isdir(base_dir + event_type):
            self.cancel("sysfs %s folder not found" % event_type)

        sys_fs_events = os.listdir(
            os.path.join(base_dir, event_type, 'events'))
        if not sys_fs_events:
            self.fail("no events found in %s events folder" % event_type)
        self.log.info("%s events count = %s" %
                      (event_type, len(sys_fs_events)))

    def test_cpu_event_count(self):
        # This test checks for the sysfs event_source directory and checks for
        # cpu events count
        self._check_count('cpu')

    def test_write_sysfs_events(self):
        devices_events = ['cpu',  'hv_24x7', 'hv_gpci']
        self._create_temp_user()
        if process.system('id test_pmu', sudo=True, ignore_status=True):
            self.log.warn('User test_pmu does not exist, skipping test')
            return

        for type_events in devices_events:
            directory_base = '/sys/bus/event_source/devices'
            directory = os.path.join(directory_base, type_events, 'events')
            random_files = self.get_random_filenames(directory)
            for file in random_files:
                eventdir = os.path.join(directory, file)
                commands = {'root': f"echo 1 > {eventdir}", 'test_pmu': f"su - test_pmu -c echo 1 > {eventdir}"}
                for user, cmd in commands.items():
                    result = process.run(cmd, shell=True, ignore_status=True)
                    output = result.stdout.decode() + result.stderr.decode()
                    if 'Permission denied' not in output:
                        self.fail("sysfs files are readonly but user has write access")
        self._remove_temp_user()

    def test_caps_feat(self):
        caps_filepath = "/sys/bus/event_source/devices/cpu/caps/pmu_name"
        if os.path.isfile(caps_filepath):
            pmu_name = process.system_output(f'cat {caps_filepath}',
                                             shell=True).decode()
            self.log.info("Sysfs pmu registered: %s" % pmu_name)
        else:
            self.cancel("Caps file not found, skipping test")

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is for PowerVM")
    def test_hv_24x7_event_count(self):
        # This test checks for the sysfs event_source directory and checks for
        # hv_24x7  events count
        self._check_count('hv_24x7')

    @skipUnless(IS_POWER_NV, "This test is for PowerNV")
    def test_imc_event_count(self):
        self._check_count('core_imc')

    @skipUnless(IS_POWER_NV, "This test is for PowerNV")
    def test_thread_event_count(self):
        self._check_count('thread_imc')

    def _sysfs_pmu_entries(self, pmu_type):
        sysfs_pmu = os.listdir('/sys/devices/')
        sysfs_pmu_list = []
        for entry in sysfs_pmu:
            if pmu_type in entry:
                sysfs_pmu_list.append(entry)
        if not len(sysfs_pmu_list):
            self.cancel("%s PMUs not found in sysfs" % pmu_type)
        return sysfs_pmu_list

    def _sysfs_pmu_cpumask(self, pmu_list):
        failed_list = []
        for pmu in pmu_list:
            cpumask_file = os.path.join('/sys/devices/', pmu, 'cpumask')
            pmu_cpumask = genio.read_file(cpumask_file)
            if not len(pmu_cpumask):
                failed_list.append(pmu_cpumask)
            self.log.info("%s contains cpumask = %s" % (cpumask_file,
                                                        pmu_cpumask))
        if len(failed_list):
            self.fail("Not found cpumask for %s" % failed_list)

    @skipUnless(IS_POWER_NV, "This test is for PowerNV")
    def test_nest_cpumask(self):
        # TBD: compare with the self.pmu_list this is the registered list.
        nest_sysfs_pmu_list = self._sysfs_pmu_entries('nest_')
        self._sysfs_pmu_cpumask(nest_sysfs_pmu_list)

    @skipUnless(IS_POWER_NV, "This test is for PowerNV")
    def test_core_cpumask(self):
        core_sysfs_pmu_list = self._sysfs_pmu_entries('core_')
        self._sysfs_pmu_cpumask(core_sysfs_pmu_list)

    def tearDown(self):
        pass

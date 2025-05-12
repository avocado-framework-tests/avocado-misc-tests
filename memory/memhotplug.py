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
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

import os
import glob
import re
import multiprocessing
from avocado.utils import cpu
from avocado import Test
from avocado.utils import process, memory, build, archive, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


MEM_PATH = '/sys/devices/system/memory'
ERRORLOG = ['WARNING: CPU:', 'Oops',
            'Segfault', 'soft lockup',
            'Unable to handle paging request',
            'rcu_sched detected stalls',
            'NMI backtrace for cpu',
            'WARNING: at',
            'INFO: possible recursive locking detected',
            'Kernel BUG at', 'Kernel panic - not syncing:',
            'double fault:', 'BUG: Bad page state in']


def online(block):
    try:
        memory.hotplug(block)
        return ""
    except IOError:
        return "memory%s : Resource is busy" % block


def offline(block):
    try:
        memory.hotunplug(block)
        return ""
    except IOError:
        return "memory%s : Resource is busy" % block


def get_hotpluggable_blocks(path, ratio):
    mem_blocks = []
    for mem_blk in glob.glob(path):
        block = re.findall(r"\d+", os.path.basename(mem_blk))[0]
        block = re.sub(r'^\s*$', '', block)
        if memory.is_hot_pluggable(block):
            mem_blocks.append(block)

    def chunks(num):
        """
        Return number of blocks in chunks of 100
        """
        if num % 2:
            return num // 100 + 1
        return num // 100
    count = chunks(len(mem_blocks) * ratio)
    return mem_blocks[:count]


def collect_dmesg(object):
    object.whiteboard = process.system_output("dmesg")


class MemStress(Test):

    '''
    Stress test to exercize memory component

    This test performs memory hotunplug/hotplug tests with below scenarios:
       1. hotunplug one by one in a loop for all
       2. Toggle memory blocks by making off/on in a loop
       3. hot unplug % of memory for different ratios
       4. dlpar memory hotplug using  drmgr
       5. shared resource : dlpar in CMO mode
       6. try hotplug each different numa node memblocks
       7. run stress memory in background

    :avocado: tags=memory,privileged
    '''

    def setUp(self):

        if not memory.check_hotplug():
            self.cancel("UnSupported : memory hotplug not enabled\n")
        smm = SoftwareManager()
        for package in ['automake', 'make', 'autoconf']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        default_url = 'https://fossies.org/linux/privat/old/stress-1.0.5.tar.gz'
        stress_tar_url = self.params.get('stress_tar_url', default=default_url)
        if not smm.check_installed('stress') and not smm.install('stress'):
            tarball = self.fetch_asset(stress_tar_url)
            archive.extract(tarball, self.teststmpdir)
            self.sourcedir = os.path.join(
                self.teststmpdir, os.path.basename(tarball.split('.tar.')[0]))

            os.chdir(self.sourcedir)
            for package in ['automake', 'make', 'autoconf']:
                if not smm.check_installed(package) and not smm.install(package):
                    self.cancel('%s is needed for the test to be run' % package)
            process.run('./autogen.sh', shell=True)
            process.run('[ -x configure ] && ./configure', shell=True)
            build.make(self.sourcedir)
            build.make(self.sourcedir, extra_args='install')
        self.iteration = self.params.get('iteration', default=1)
        self.stresstime = self.params.get('stresstime', default=10)
        self.vmcount = self.params.get('vmcount', default=4)
        self.iocount = self.params.get('iocount', default=4)
        self.memratio = self.params.get('memratio', default=5)
        self.blocks_hotpluggable = get_hotpluggable_blocks(
            (os.path.join('%s', 'memory*') % MEM_PATH), self.memratio)
        if os.path.exists("%s/auto_online_blocks" % MEM_PATH):
            if not self.__is_auto_online():
                self.hotplug_all(self.blocks_hotpluggable)
        dmesg.clear_dmesg()

    def hotunplug_all(self, blocks):
        for block in blocks:
            if memory._check_memory_state(block):
                err = offline(block)
                if err:
                    self.log.error(err)

    def hotplug_all(self, blocks):
        for block in blocks:
            if not memory._check_memory_state(block):
                err = online(block)
                if err:
                    self.log.error(err)

    @staticmethod
    def __is_auto_online():
        with open('%s/auto_online_blocks' % MEM_PATH, 'r') as auto_file:
            if auto_file.read() == 'online\n':
                return True
            return False

    def __error_check(self):
        err_list = []
        logs = process.system_output("dmesg -Txl 1,2,3,4").splitlines()
        for error in ERRORLOG:
            for log in logs:
                if error in log.decode():
                    err_list.append(log)
        if "\n".join(err_list):
            collect_dmesg(self)
            self.fail('ERROR: Test failed, please check the dmesg logs')

    def run_stress(self):
        mem_free = memory.meminfo.MemFree.m // 4
        cpu_count = int(multiprocessing.cpu_count()) // 2
        process.run("stress --cpu %s --io %s --vm %s --vm-bytes %sM --timeout %ss" %
                    (cpu_count, self.iocount, self.vmcount, mem_free, self.stresstime), ignore_status=True, sudo=True, shell=True)

    def test_hotplug_loop(self):
        self.log.info("\nTEST: hotunplug and hotplug in a loop\n")
        for _ in range(self.iteration):
            self.log.info("\nhotunplug all memory\n")
            self.hotunplug_all(self.blocks_hotpluggable)
            self.run_stress()
            self.log.info("\nReclaim back memory\n")
            self.hotplug_all(self.blocks_hotpluggable)
        self.__error_check()

    def test_hotplug_toggle(self):
        self.log.info("\nTEST: Memory toggle\n")
        for _ in range(self.iteration):
            for block in self.blocks_hotpluggable:
                err = offline(block)
                if err:
                    self.log.error(err)
                self.log.info("memory%s block hotunplugged", block)
                self.run_stress()
                err = online(block)
                if err:
                    self.log.error(err)
                self.log.info("memory%s block hotplugged", block)
        self.__error_check()

    def test_dlpar_mem_hotplug(self):
        if 'power' in cpu.get_arch() and 'PowerNV' not in open('/proc/cpuinfo', 'r').read():
            if b"mem_dlpar=yes" in process.system_output("drmgr -C", ignore_status=True, shell=True):
                self.log.info("\nDLPAR remove memory operation\n")
                for _ in range(len(self.blocks_hotpluggable) // 2):
                    process.run(
                        "drmgr -c mem -d 5 -w 30 -r", shell=True, ignore_status=True, sudo=True)
                self.run_stress()
                self.log.info("\nDLPAR add memory operation\n")
                for _ in range(len(self.blocks_hotpluggable) // 2):
                    process.run(
                        "drmgr -c mem -d 5 -w 30 -a", shell=True, ignore_status=True, sudo=True)
                self.__error_check()
            else:
                self.log.info('UNSUPPORTED: dlpar not configured..')
        else:
            self.log.info("UNSUPPORTED: Test not supported on this platform")

    def test_hotplug_per_numa_node(self):
        self.log.info("\nTEST: Numa Node memory off on\n")
        with open('/sys/devices/system/node/has_normal_memory', 'r') as node_file:
            nodes = node_file.read()
        for node in re.split("[,-]", nodes):
            node = node.strip('\n')
            self.log.info("Hotplug all memory in Numa Node %s", node)
            mem_blocks = get_hotpluggable_blocks((
                '/sys/devices/system/node/node%s/memory[0-9]*' % node), self.memratio)
            for block in mem_blocks:
                self.log.info(
                    "offline memory%s in numa node%s", block, node)
                err = offline(block)
                if err:
                    self.log.error(err)
            self.run_stress()
        self.__error_check()

    def tearDown(self):
        self.hotplug_all(self.blocks_hotpluggable)

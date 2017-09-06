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
import platform
import multiprocessing
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import memory
from avocado.utils.software_manager import SoftwareManager


blocks_hotpluggable = []
mem_path = '/sys/devices/system/memory'
errorlog = ['WARNING: CPU:', 'Oops',
            'Segfault', 'soft lockup',
            'Unable to handle paging request',
            'rcu_sched detected stalls',
            'NMI backtrace for cpu',
            'Call Trace:', 'WARNING: at',
            'INFO: possible recursive locking detected',
            'Kernel BUG at', 'Kernel panic - not syncing:',
            'double fault:', 'BUG: Bad page state in']


def online(block):
    try:
        memory.hotplug(block)
    except IOError:
        print "memory%s : Resource is busy" % block
        pass


def offline(block):
    try:
        memory.hotunplug(block)
    except IOError:
        print "memory%s : Resource is busy" % block
        pass


def get_hotpluggable_blocks(path):
    mem_blocks = []
    for mem_blk in glob.glob(path):
        block = re.findall("\d+", os.path.basename(mem_blk))[0]
        block = re.sub(r'^\s*$', '', block)
        if memory.is_hot_pluggable(block):
            mem_blocks.append(block)
    return mem_blocks


def collect_dmesg(object):
    object.whiteboard = process.system_output("dmesg")


class memstress(Test):

    '''
    Stress test to excersize memory component

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
        sm = SoftwareManager()
        if not sm.check_installed('stress') and not sm.install('stress'):
            self.cancel(' stress package is needed for the test to be run')
        self.tests = self.params.get('test', default='all')
        self.iteration = int(self.params.get('iteration', default='1'))
        self.stresstime = int(self.params.get('stresstime', default='10'))
        self.vmcount = int(self.params.get('vmcount', default='4'))
        self.iocount = int(self.params.get('iocount', default='4'))
        self.memratio = self.params.get('memratio', default=None)
        self.blocks_hotpluggable = get_hotpluggable_blocks(
            '%s/memory*' % mem_path)

    @staticmethod
    def hotunplug_all(blocks):
        for block in blocks:
            if memory._check_memory_state(block):
                offline(block)

    @staticmethod
    def hotplug_all(blocks):
        for block in blocks:
            if not memory._check_memory_state(block):
                online(block)

    @staticmethod
    def __clear_dmesg():
        process.run("dmesg -c", sudo=True)

    @staticmethod
    def __error_check():
        ERROR = None
        logs = (process.system_output(
            "dmesg -T --level=alert,crit,err,warn", ignore_status=True, shell=True, sudo=True)).split()
        for log in logs:
            for error in errorlog:
                if error in log:
                    ERROR = 'Test: resulted %s in syslogs"' % error
        return ERROR

    @staticmethod
    def __is_auto_online():
        with open('%s/auto_online_blocks' % mem_path, 'r') as auto_file:
            if auto_file.read() == 'online\n':
                return True
            return False

    def run_stress(self):
        mem_free = memory.meminfo.MemFree.mb / 2
        cpu_count = int(multiprocessing.cpu_count()) / 2
        process.run("stress --cpu %s --io %s --vm %s --vm-bytes %sM --timeout %ss" %
                    (cpu_count, self.iocount, self.vmcount, mem_free, self.stresstime), ignore_status=True, sudo=True, shell=True)

    def test(self):
        if os.path.exists("%s/auto_online_blocks" % mem_path):
            if not self.__is_auto_online():
                self.hotplug_all(self.blocks_hotpluggable)
        if 'all' in self.tests:
            tests = ['hotplug_loop',
                     'hotplug_toggle',
                     'hotplug_ratio',
                     'dlpar_mem_hotplug',
                     'hotplug_per_numa_node']
        else:
            tests = self.tests.split()

        for method in tests:
            self.log.info("\nTEST: %s\n", method)
            self.__clear_dmesg()
            run_test = 'self.%s()' % method
            eval(run_test)
            msg = self.__error_check()
            if msg:
                collect_dmesg()
                self.log.error('Test: %s. ERROR Message: %s', run_test, msg)
            self.log.info("\nEND: %s\n", method)

    def hotplug_loop(self):
        self.log.info("\nTEST: hotunplug and hotplug in a loop\n")
        for _ in range(self.iteration):
            self.log.info("\nhotunplug all memory\n")
            self.hotunplug_all(self.blocks_hotpluggable)
            self.run_stress()
            self.log.info("\nReclaim back memory\n")
            self.hotplug_all(self.blocks_hotpluggable)

    def hotplug_toggle(self):
        self.log.info("\nTEST: Memory toggle\n")
        for _ in range(self.iteration):
            for block in self.blocks_hotpluggable:
                offline(block)
                self.log.info("memory%s block hotunplugged" % block)
                self.run_stress()
                online(block)
                self.log.info("memory%s block hotplugged" % block)

    def hotplug_ratio(self):
        if not self.memratio:
            self.memratio = ['25', '50', '75', '100']
        for ratio in self.memratio:
            target = 0
            self.log.info("\nTEST : Hotunplug %s%% of memory\n" % ratio)
            num = len(self.blocks_hotpluggable) * int(ratio)
            if num % 100:
                target = (num / 100) + 1
            else:
                target = num / 100
            for block in self.blocks_hotpluggable:
                if target > 0:
                    offline(block)
                    target -= 1
                    self.log.info("memory%s block offline" % block)
            self.run_stress()
            self.log.info("\nReclaim all memory\n")
            self.hotplug_all(self.blocks_hotpluggable)

    def dlpar_mem_hotplug(self):
        if 'ppc' in platform.processor() and 'PowerNV' not in open('/proc/cpuinfo', 'r').read():
            if "mem_dlpar=yes" in process.system_output("drmgr -C", ignore_status=True, shell=True):
                init_mem = memory.meminfo.MemTotal.kb
                self.log.info("\nDLPAR remove memory operation\n")
                for _ in range(len(self.blocks_hotpluggable) / 2):
                    process.run(
                        "drmgr -c mem -d 5 -w 30 -r", shell=True, ignore_status=True, sudo=True)
                if memory.meminfo.MemTotal.kb >= init_mem:
                    self.log.warn("dlpar mem could not complete")
                self.run_stress()
                init_mem = memory.meminfo.MemTotal.kb
                self.log.info("\nDLPAR add memory operation\n")
                for _ in range(len(self.blocks_hotpluggable) / 2):
                    process.run(
                        "drmgr -c mem -d 5 -w 30 -a", shell=True, ignore_status=True, sudo=True)
                if init_mem < memory.meminfo.MemTotal.kb:
                    self.log.warn("dlpar mem could not complete")
            else:
                self.log.info('UNSUPPORTED: dlpar not configured..')
        else:
            self.log.info("UNSUPPORTED: Test not supported on this platform")

    def hotplug_per_numa_node(self):
        self.log.info("\nTEST: Numa Node memory off on\n")
        with open('/sys/devices/system/node/has_normal_memory', 'r') as node_file:
            nodes = node_file.read()
        for node in nodes.split('-'):
            node = node.strip('\n')
            self.log.info("Hotplug all memory in Numa Node %s" % node)
            mem_blocks = get_hotpluggable_blocks(
                '/sys/devices/system/node/node%s/memory*' % node)
            for block in mem_blocks:
                self.log.info(
                    "offline memory%s in numa node%s" % (block, node))
                offline(block)
            self.run_stress()
            self.hotplug_all(self.blocks_hotpluggable)


if __name__ == "__main__":
    main()

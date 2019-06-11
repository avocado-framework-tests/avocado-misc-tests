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
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import time
import getpass
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import memory
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Memcached(Test):

    """
    Memcached - High performance memory object caching system.
    This test Runs the memcached server in the background, based
    upon the memory param given. And it tries to run the memcslap
    stress tool which generates a load against memcached server.
    For more options on memcached:
    Refer - https://linux.die.net/man/1/memcached

    :avocado: tags=memory,privileged
    """

    def setUp(self):
        """
        Sets up the args required to run the test.
        """

        smm = SoftwareManager()
        detected_distro = distro.detect()

        if detected_distro.name not in ['Ubuntu', 'rhel', 'SuSE', 'fedora']:
            self.cancel('Test Not applicable')

        if detected_distro.name == "Ubuntu":
            deps = ['memcached', 'libmemcached-tools']
            stress_tool = 'memcslap'

        if detected_distro.name in ["rhel", "SuSE", "fedora"]:
            deps = ['memcached', 'libmemcached']
            stress_tool = 'memslap'

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(' %s is needed for the test to be run' % package)

        # Memcached Required Args
        memory_to_use = self.params.get("memory_to_use",
                                        default=memory.meminfo.MemFree.m)
        port_no = self.params.get("port_no", default='12111')
        memcached_args = self.params.get('memcached_args', default='')
        self.memcached_cmd = 'memcached -u %s -p %s -m %d  %s &'\
                             % (getpass.getuser(), port_no, memory_to_use,
                                memcached_args)

        # Memcached stress tool required Args
        # For more options : memcslap --help
        system_ip = self.params.get('system_ip', default='127.0.0.1')
        test_to_run = self.params.get('test_to_run', default='get')
        concurrency = self.params.get('concurrency', default='100')
        stress_tool_args = self.params.get('stress_tool_args', default='')

        self.stress_tool_cmd = '%s -s %s:%s --test %s --verbose '\
                               '--concurrency %s %s' % (stress_tool,
                                                        system_ip, port_no,
                                                        test_to_run,
                                                        concurrency,
                                                        stress_tool_args)

    def test(self):
        """
        Runs memcached in the background and runs memcslap tool on
        top of memcached
        """

        process.run(self.memcached_cmd, shell=True, ignore_status=True,
                    verbose=True, ignore_bg_processes=True)

        # Givin some time for server to start properly
        self.log.info('Sleeping for 5 seconds for server startup')
        time.sleep(5)

        if process.system('pgrep memcached', verbose=False,
                          ignore_status=True):
            self.fail('Memcached Server not Running\n'
                      'Cmd "%s" Failed' % self.memcached_cmd)

        self.log.info("Memcached started successfully !! Running Stress tool")

        if (process.system(self.stress_tool_cmd, verbose=True,
                           shell=True, ignore_status=True)):
            self.fail('Stress tool fails to load memcached server'
                      'Cmd "%s" Failed' % self.stress_tool_cmd)

    def tearDown(self):
        """
        Kills the memcached which is running background
        """

        process.system('pkill memcached', ignore_status=True)


if __name__ == "__main__":
    main()

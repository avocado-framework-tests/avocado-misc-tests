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
# Author: Hariharan T.S.  <harihare@in.ibm.com>


from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class Sysbench(Test):

    """
    sysbench supports following performance tests
    :cpu, threads, oltp, fileio

    :avocado: tags=cpu,threads
    """

    def clear_dmesg(self):
        process.run("dmesg -c ", sudo=True)

    def verify_dmesg(self):
        self.whiteboard = process.system_output("dmesg")
        pattern = ['WARNING: CPU:', 'Oops',
                   'Segfault', 'soft lockup', 'Unable to handle']
        for fail_pattern in pattern:
            if fail_pattern in self.whiteboard:
                self.fail("Test Failed : %s in dmesg" % fail_pattern)

    def run_cmd(self, cmdline):
        try:
            process.run(cmdline, ignore_status=False, sudo=True)
        except process.CmdError as details:
            self.fail("The sysbench failed: %s" % details)

    def setUp(self):
        softmanager = SoftwareManager()
        if not softmanager.check_installed('sysbench') and not softmanager.install('sysbench'):
            self.cancel("sysbench package is required to continue the test")
        self.max_time = self.params.get('max-time', default=None)
        self.max_request = self.params.get('max-request', default=None)
        self.num_threads = int(self.params.get('num-threads', default=2))
        self.test_type = self.params.get('type', default='cpu')
        self.cpu_max_prime = int(self.params.get('cpu-max-prime', default=100))
        self.threads_locks = self.params.get('threads-locks', default=None)
        self.clear_dmesg()

    def test(self):
        args = []
        args.append("--test=%s" % self.test_type)

        if 'cpu' in self.test_type:
            args.append("--num-threads=%s" % self.num_threads)
            args.append("--cpu-max-prime=%s" % self.cpu_max_prime)
        elif 'threads' in self.test_type:
            if self.threads_locks is not None:
                args.append("--thread-locks=%s" % self.threads_locks)
            args.append("--num-threads=%s" % self.num_threads)
        args.append("run")
        cmdline = "sysbench %s" % " ".join(args)
        self.run_cmd(cmdline)
        self.verify_dmesg()


if __name__ == "__main__":
    main()

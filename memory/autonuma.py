#!/usr/bin/env python
#
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
# Copyright: 2025 IBM
# Author: Pavithra Prakash <pavrampu@linux.vnet.ibm.com>
#


import os
from avocado import Test
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import distro


class AutoNuma(Test):

    def count_numa_pte_updates(self):
        """
        This function retrieves the current value of numa_pte_updates
        from /proc/vmstat and returns it as an integer.
        """
        cmd = 'cat /proc/vmstat  | grep numa_pte_updates'
        output = process.system_output(cmd, shell=True)
        return(int(str(output).split()[-1].strip('\'')))

    def count_numa_hint_faults(self):
        """
        This function fetches the current value of numa_hint_faults from
        /proc/vmstat and returns it as an integer.
        """
        cmd = 'cat /proc/vmstat  | grep numa_hint_faults | head -1'
        output = process.system_output(cmd, shell=True)
        return(int(str(output).split()[-1].strip('\'')))

    def setUp(self):
        """
        This function sets up the test environment by downloading, extracting, and
        building the ebizzy workload from its source.
        """
        smm = SoftwareManager()

        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if detected_distro.name == "rhel":
            deps.extend(['numactl-devel'])
        for packages in deps:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.cancel('%s is needed for the test to be run' % packages)
        self.url = self.params.get('ebizzy_url',
                                   default='https://sourceforge.net/projects/ebizzy/files/ebizzy/0.3/ebizzy-0.3.tar.gz')
        tarball = self.fetch_asset("ebizzy-0.3.tar.gz", locations=[self.url], expire='7d')
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)
        os.chdir(self.sourcedir)
        process.run('[ -x configure ] && ./configure', shell=True)
        build.make(self.sourcedir)

    def test(self):
        """
        This test performs the following steps:

        - Records the initial values of numa_pte_updates and numa_hint_faults.
        - Disables NUMA balancing and runs ebizzy workload.
        - Records the new values of numa_pte_updates and numa_hint_faults.
        - Checks if there's any change in the values if yes, the test fails.
        - Enables NUMA balancing and runs ebizzy workload again.
        - Checks if numa_pte_updates and numa_hint_faults have increased by at least 10 after
          enabling NUMA balancing. If not, the test fails.
        """
        init_pte_updates = self.count_numa_pte_updates()
        init_hint_faults = self.count_numa_hint_faults()
        process.run('echo "0" > /proc/sys/kernel/numa_balancing', shell=True)
        process.run('./ebizzy', shell=True)
        pte_updates_0 = self.count_numa_pte_updates()
        hint_faults_0 = self.count_numa_hint_faults()
        if(pte_updates_0 - init_pte_updates) or (hint_faults_0 - init_hint_faults):
            self.fail("Numa balancing disable test failed")
        process.run('echo "1" > /proc/sys/kernel/numa_balancing', shell=True)
        process.run('./ebizzy', shell=True)
        pte_updates_1 = self.count_numa_pte_updates()
        hint_faults_1 = self.count_numa_hint_faults()
        if(pte_updates_1 - init_pte_updates) < 10:
            self.fail("numa_pte_updates has not incremented even after "
                      "running workload with numa balancing enabled.")
        if(hint_faults_1 - init_hint_faults) < 10:
            self.fail("numa_hint_faults has not incremented even after"
                      " running workload with numa balancing enabled.")

    def test_autonuma_benchmark(self):
        """
        This test case runs downloading, extracting, and running the autonuma-benchmark tests,
        Test results need to be verified manually.
        """
        url_autonuma = self.params.get('url_autonuma',
                                       default='https://github.com/pholasek/autonuma-benchmark/archive/refs/heads/master.zip')
        tarball = self.fetch_asset("master.zip", locations=[url_autonuma], expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, "autonuma-benchmark-master")
        os.chdir(self.sourcedir)
        process.system_output('./start_bench.sh -A', shell=True, ignore_status=True)
        self.log.warn("Have run the tests please review the results in debug.log")

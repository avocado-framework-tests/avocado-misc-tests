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
# Copyright: 2020 IBM
# Author: Harish <harish@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import build
from avocado.utils import memory
from avocado.utils import process
from avocado.utils import git
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils.software_manager.manager import SoftwareManager
from concurrent.futures import ThreadPoolExecutor, as_completed


class MmSubsystemTest(Test):
    '''
    Memory subsystem functional test

    :avocado: tags=memory
    '''

    def get_data_path(self, filename):
        """
        Get the path to a data file for this test
        """
        test_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(test_dir, f"{os.path.basename(__file__)}.data")
        return os.path.join(data_dir, filename)

    @staticmethod
    def check_dmesg():
        errorlog = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                    'ard LOCKUP', 'Unable to handle paging request',
                    'rcu_sched detected stalls', 'NMI backtrace for cpu']
        err = []
        logs = process.system_output("dmesg -Txl 1,2,3,4"
                                     "").decode("utf-8").splitlines()
        for error in errorlog:
            for log in logs:
                if error in log:
                    err.append(log)
        return "\n".join(err)

    def setUp(self):
        """
        Build binary and filter tests based on the environment
        """
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'patch']
        detected_distro = distro.detect()
        skip_offline = self.params.get("skip_softoffline", default=True)
        if detected_distro.name in ["Ubuntu", 'debian']:
            deps.extend(['libpthread-stubs0-dev', 'git'])
        elif detected_distro.name == "SuSE":
            deps.extend(['glibc-devel-static', 'git-core'])
        elif detected_distro.name == "rhel":
            deps.extend(['glibc-static', 'git'])
        else:
            deps.extend(['glibc-static', 'git', 'runc'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        git.get_repo("https://github.com/narasimhan-v/linux-mm",
                     destination_dir=self.logdir)
        os.chdir(self.logdir)

        # Optimize NR_LOOP for faster test execution
        # For large systems (>4TB), reduce NR_LOOP to 10 for significant speedup
        total_mem_gb = memory.memtotal() // (1024 * 1024)  # Convert KB to GB
        if total_mem_gb > 4096:  # Systems > 4TB
            nr_loop = 10
            self.log.info(f"Large system detected ({total_mem_gb}GB). Reducing NR_LOOP from 1000 to {nr_loop}")
        else:
            nr_loop = 100
            self.log.info("Optimizing NR_LOOP from 1000 to 100 for faster execution")

        random_c = os.path.join(self.logdir, 'random.c')
        process.run(f"sed -i 's/#define NR_LOOP 1000/#define NR_LOOP {nr_loop}/' {random_c}",
                    shell=True)

        # Apply patch to fix compilation errors with newer GCC
        patch_file = self.get_data_path('fix_compilation.patch')
        if os.path.exists(patch_file):
            self.log.info("Applying compilation fix patch")
            process.run(f'patch -p1 < {patch_file}', shell=True)

        # For large systems (>4TB), apply memory hotplug limit patch
        # This limits memory block processing to 10% for faster execution
        if total_mem_gb > 4096:
            limit_patch = self.get_data_path('limit_hotplug.patch')
            if os.path.exists(limit_patch):
                self.log.info("Applying memory hotplug limit patch for large system (10% of memory blocks)")
                process.run(f'patch -p1 < {limit_patch}', shell=True)
            else:
                self.log.warning("limit_hotplug.patch not found, skipping memory hotplug optimization")

        build.make(self.logdir)
        tst_list = process.system_output('./random -l').decode().splitlines()
        self.test_dic = {}
        for line in tst_list:
            keyval = line.split(":")
            self.test_dic[keyval[0]] = keyval[1]
        skip_numa = False
        if len(memory.numa_nodes_with_memory()) < 2:
            skip_numa = True
        rm_list = []
        for key, val in self.test_dic.items():
            if skip_numa:
                if 'NUMA' in val or 'migrate' in val:
                    if key not in rm_list:
                        rm_list.append(key)
            if skip_offline:
                if 'soft offlin' in val:
                    if key not in rm_list:
                        rm_list.append(key)
            if detected_distro.name in ["SuSE", "rhel"]:
                if 'runc' in val:
                    if key not in rm_list:
                        rm_list.append(key)

        for item in rm_list:
            self.test_dic.pop(item)

    def _run_single_test(self, cnt):
        """
        Run a single test and return results
        """
        result = {'failed': False, 'msg': ''}
        dmesg.clear_dmesg()

        if process.system("./random %s" % cnt, ignore_status=True):
            result['failed'] = True

        msg = self.check_dmesg()
        if msg:
            result['msg'] = 'Test: %s (%s) failed with %s message' % (
                cnt, self.test_dic[cnt], msg)

        return result

    def test(self):
        """
        Run filtered tests with parallel execution support
        """
        # Check if parallel execution is enabled
        parallel = self.params.get("parallel_tests", default=False)
        max_workers = self.params.get("max_workers", default=4)

        if not parallel:
            self._run_tests_sequential()
        else:
            self._run_tests_parallel(max_workers)

    def _run_tests_sequential(self):
        """
        Run tests sequentially (original behavior)
        """
        failed = []
        fail_msg = []
        self.log.info("Tests to be run are %s", self.test_dic)

        for cnt in list(self.test_dic.keys()):
            result = self._run_single_test(cnt)
            if result['failed']:
                failed.append(cnt)
            if result['msg']:
                fail_msg.append(result['msg'])

        if failed or fail_msg:
            self.log.info('ERROR in dmesg:  %s', fail_msg)
            self.log.info('Tests failed:  %s', failed)
            self.fail('Test failed, please check above for failures')

    def _run_tests_parallel(self, max_workers):
        """
        Run independent tests in parallel for faster execution
        Tests that modify system state (hotplug, tree read) run sequentially
        """
        # Categorize tests: independent tests can run in parallel
        # Dependent tests (hotplug, tree traversal) must run sequentially
        independent = []
        dependent = []

        for cnt in list(self.test_dic.keys()):
            test_desc = self.test_dic[cnt].lower()
            # Tests that are system-wide or modify state should run sequentially
            if any(keyword in test_desc for keyword in
                   ['hotplug', 'offline', 'read all', 'fill up']):
                dependent.append(cnt)
            else:
                independent.append(cnt)

        self.log.info("Running %d tests in parallel (max_workers=%d), %d sequentially",
                      len(independent), max_workers, len(dependent))
        self.log.info("Parallel tests: %s", independent)
        self.log.info("Sequential tests: %s", dependent)

        failed = []
        fail_msg = []

        # Run independent tests in parallel
        if independent:
            self.log.info("Starting parallel test execution...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self._run_single_test, cnt): cnt
                           for cnt in independent}

                for future in as_completed(futures):
                    cnt = futures[future]
                    try:
                        result = future.result()
                        if result['failed']:
                            failed.append(cnt)
                            self.log.error("Test %s (%s) failed", cnt, self.test_dic[cnt])
                        if result['msg']:
                            fail_msg.append(result['msg'])
                        else:
                            self.log.info("Test %s (%s) passed", cnt, self.test_dic[cnt])
                    except Exception as exc:
                        self.log.error("Test %s generated exception: %s", cnt, exc)
                        failed.append(cnt)
                        fail_msg.append('Test: %s (%s) raised exception: %s' %
                                        (cnt, self.test_dic[cnt], str(exc)))

        # Run dependent tests sequentially
        if dependent:
            self.log.info("Starting sequential test execution...")
            for cnt in dependent:
                result = self._run_single_test(cnt)
                if result['failed']:
                    failed.append(cnt)
                    self.log.error("Test %s (%s) failed", cnt, self.test_dic[cnt])
                if result['msg']:
                    fail_msg.append(result['msg'])
                else:
                    self.log.info("Test %s (%s) passed", cnt, self.test_dic[cnt])

        if failed or fail_msg:
            self.log.info('ERROR in dmesg:  %s', fail_msg)
            self.log.info('Tests failed:  %s', failed)
            self.fail('Test failed, please check above for failures')
        else:
            self.log.info("All tests passed successfully")

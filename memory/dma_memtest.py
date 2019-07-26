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
# Copyright: 2016 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>
#
# Based on code by :
# Martin Bligh <mbligh@google.com>
# copyright 2009 Google, Inc.
# https://github.com/autotest/autotest-client-tests/tree/master/dma_memtest


import os
import shutil
import re
from avocado import Test
from avocado.utils import process
from avocado.utils import disk
from avocado.utils import archive
from avocado.core import data_dir


class DmaMemtest(Test):

    """
    A test for the memory subsystem against heavy IO and DMA operations,
    implemented based on the work of Doug Leford
    (http://people.redhat.com/dledford/memtest.shtml).
    It will uncompress several copies of the linux kernel in a way that will
    force the system to go swap, then will compare the trees generated for
    differences.

    :avocado: tags=memory,privileged
    """

    def setUp(self):
        """
        Downloads a copy of the linux kernel, calculate an estimated size of
        the uncompressed tarball, use this value to calculate the number of
        copies of the linux kernel that will be uncompressed.
        """
        self.nfail = 0
        self.tmpdir = data_dir.get_tmp_dir()
        self.tmpdir = self.params.get('dir_to_extract', default=self.tmpdir)
        self.base_dir = os.path.join(self.tmpdir, 'linux.orig')
        tarball_base = self.params.get('tarball_base',
                                       default='linux-2.6.18.tar.bz2')
        kernel_repo = self.params.get('kernel_repo',
                                      default='http://www.kernel.org/pub/'
                                      'linux/kernel/v2.6')
        tarball_url = os.path.join(kernel_repo, tarball_base)
        tarball_md5 = self.params.get('tarball_md5',
                                      default='296a6d150d260144639c3664d127d1'
                                      '74')
        parallel = self.params.get('parallel', default=True)
        self.parallel = parallel
        self.log.info('Downloading linux kernel tarball')
        self.tarball = self.fetch_asset(tarball_url, asset_hash=tarball_md5,
                                        algorithm='md5')
        size_tarball = os.path.getsize(self.tarball) / 1024 / 1024

        # Estimation of the tarball size after uncompression
        compress_ratio = 5
        est_size = size_tarball * compress_ratio
        self.sim_cps = self.get_sim_cps(est_size)
        self.log.info('Source file: %s', tarball_base)
        self.log.info('Megabytes per copy: %s', size_tarball)
        self.log.info('Compress ratio: %s', compress_ratio)
        self.log.info('Estimated size after uncompression: %s', est_size)
        self.log.info('Number of copies: %s', self.sim_cps)
        self.log.info('Parallel: %s', parallel)

        # Verify if space is available in disk
        disk_free_mb = (disk.freespace(self.tmpdir) / 1024) / 1024
        if disk_free_mb < (est_size * self.sim_cps):
            self.cancel("Space not available to extract the %s linux tars\n"
                        "Mount and Use other partitions in dir_to_extract arg "
                        "to run the test" % self.sim_cps)

    @staticmethod
    def get_sim_cps(est_size):
        '''
        Calculate the amount of simultaneous copies that can be uncompressed
        so that it will make the system swap.

           :param est_size: Estimated size of uncompressed linux tarball
        '''
        mem_str = process.system_output('grep MemTotal /proc/meminfo')
        mem = int(re.search(r'\d+', mem_str.decode()).group(0))
        mem = int(mem / 1024)
        sim_cps = (1.5 * mem) / est_size

        if (mem % est_size) >= (est_size / 2):
            sim_cps += 1

        if (mem / 32) < 1:
            sim_cps += 1

        return int(sim_cps)

    def test(self):
        parallel_procs = []
        os.chdir(self.tmpdir)
        # This is the reference copy of the linux tarball
        # that will be used for subsequent comparisons
        self.log.info('Unpacking base copy')
        archive.extract(self.tarball, self.base_dir)
        self.log.info('Unpacking test copies')
        for j in range(self.sim_cps):
            tmp_dir = 'linux.%s' % j
            if self.parallel:
                if not os.path.exists(tmp_dir):
                    os.makedirs(tmp_dir)
                # Start parallel process
                tar_cmd = 'tar jxf ' + self.tarball + ' -C ' + tmp_dir
                self.log.info("Unpacking tarball to %s", tmp_dir)
                obj = process.SubProcess(cmd=tar_cmd, verbose=False,
                                         shell=True)
                obj.start()
                parallel_procs.append(obj)
            else:
                self.log.info("Unpacking tarball to %s", tmp_dir)
                archive.extract(self.tarball, tmp_dir)
        # Wait for the subprocess before comparison
        if self.parallel:
            self.log.info("Wait background processes before proceed")
            for proc in parallel_procs:
                proc.wait()
        parallel_procs = []
        self.log.info('Comparing test copies with base copy')
        for j in range(self.sim_cps):
            kernel_ver = os.path.basename(self.tarball).strip('.tar.bz2')
            tmp_dir = 'linux.%s/%s' % (j, kernel_ver)
            if self.parallel:
                diff_cmd = 'diff -U3 -rN linux.orig/' + kernel_ver
                diff_cmd += ' ' + tmp_dir
                self.log.info("Comparing linux.orig with %s", tmp_dir)
                obj = process.SubProcess(cmd=diff_cmd, verbose=False,
                                         shell=True)
                obj.start()
                parallel_procs.append(obj)
            else:
                try:
                    self.log.info('Comparing linux.orig with %s', tmp_dir)
                    process.system('diff -U3 -rN linux.orig linux.%s' % j)
                except process.CmdError as error:
                    self.nfail += 1
                    self.log.info('Error comparing trees: %s', error)

        for proc in parallel_procs:
            out_buf = proc.get_stdout()
            out_buf += proc.get_stderr()
            proc.wait()
            if out_buf != "":
                self.nfail += 1
                self.log.error('Error when comparing test with base copies in'
                               'parallel')

        # Clean up for the next iteration
        parallel_procs = []

        if self.nfail != 0:
            self.fail('DMA memory test failed.')
        else:
            self.log.info('DMA memory test passed.')

    def tearDown(self):
        self.log.info('Cleaning up')
        for j in range(self.sim_cps):
            tmp_dir = 'linux.%s' % j
            shutil.rmtree(tmp_dir)
        shutil.rmtree(self.base_dir)

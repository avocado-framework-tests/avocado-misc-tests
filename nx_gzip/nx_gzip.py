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
# Copyright: 2020 IBM
# Author: Kalpana Shetty <kalshett@in.ibm.com>

import os
import shutil
from avocado import Test, skipUnless
from avocado.utils import build, process, distro, git, archive, memory
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.partition import Partition

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_POWER10 = 'POWER10' in open('/proc/cpuinfo', 'r').read()


class NXGZipTests(Test):
    """
    nx-gzip test cases make use of testsuite provided by the
    library source package and performs functional tests.
    """

    def download_tarball(self):
        '''
        Get linux source tarball for compress/decompress
        '''
        url = 'https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.15.tar.gz'
        tarball = self.fetch_asset(self.params.get("linuxsrc_url",
                                   default=url))
        os.chdir(self.workdir)
        archive.extract(tarball, self.workdir)
        archive.compress("%s/linux-src.tar" % self.workdir, self.workdir)

    def create_ddfile(self):
        '''
        create dd file for compress/decompress
        '''
        blk_size = self.params.get('blk_size', default='1073741824')
        file_size = self.params.get('file_size', default='150')
        dd_cmd = 'dd if=/dev/urandom of=%sgb-file bs=%s count=%s'\
                 % (file_size, blk_size, file_size)
        if process.system(dd_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: create_ddfile: dd file creation failed")

    def build_tests(self, testdir_name):
        '''
        build different test builds
        '''
        if self.name.uid == 15:
           test_dir = os.path.join(self.buldir, testdir_name)
        else:
           test_dir = os.path.join(self.teststmpdir, testdir_name)
        os.chdir(test_dir)
        testdir_dict = {
          "": "check",
          "selftest": "run_tests",
          "test": "unsafe-check",
          "samples": "bench",
          "oct": "-j16",
          "tools/testing/selftests/powerpc/nx-gzip": "run_tests"
        }

        failed_tests = []
        output = build.run_make(test_dir,
                                extra_args=testdir_dict[testdir_name],
                                process_kwargs={"ignore_status": True})
        for line in output.stdout.decode('utf-8').splitlines():
            if "failed" in line:
                failed_tests.append(line)
        if failed_tests:
            self.fail("%s" % failed_tests)

    @skipUnless(IS_POWER_NV | IS_POWER10,
                "NX-GZIP tests are supported only on PowerNV(POWER9) or "
                "POWER10 platform.")
    def setUp(self):
        """
        Install pre-requisite packages
        """
        smg = SoftwareManager()
        self.dist = distro.detect()
        if self.dist.name not in ['rhel']:
            self.cancel('Unsupported OS %s' % self.dist.name)

        deps = ['gcc', 'make', 'glibc-static', 'zlib', 'zlib-devel']
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % (package))

        self.url = self.params.get(
            'url', default="https://github.com/libnxz/power-gzip")
        self.branch = self.params.get('git_branch', default='master')
        git.get_repo(self.url, branch=self.branch,
                     destination_dir=self.teststmpdir)

        os.chdir(self.teststmpdir)
        build.make(self.teststmpdir)

    def test_inflate_deflate(self):
        '''
        Running NX-GZIP: Inflate and Deflate tests
        '''
        self.log.info("NX-GZIP: test_inflate_deflate:\
                      Inflate and Deflate tests")
        self.build_tests("")

    def test_basic_comp_decomp(self):
        '''
        Running NX-GZIP: Simple compression/decompression
        '''
        self.log.info("NX-GZIP: test_basic_comp_decomp:\
                      basic compression/decompression tests")
        self.build_tests("selftest")

    def test_kernel_oops(self):
        '''
        Running NX-GZIP: testing kernel oops
        '''
        self.log.info("NX-GZIP: test_kernel_oops: testing kernel oops tests")
        self.build_tests("test")

    def test_zpipe(self):
        '''
        Running NX-GZIP: Compress/Decompress using zpipe which uses nx-gzip
        '''
        self.log.info("NX-GZIP: test_zpipe:\
                      Compress/Decompress using zpipe which uses nx-gzip")
        self.build_tests("samples")

        file_size = self.params.get('file_size', default='150')
        out_file = self.params.get('out_file', default='out_file')
        new_file = self.params.get('new_file', default='new_file')
        self.create_ddfile()

        comp_cmd = './zpipe < %sgb-file > %s' % (file_size, out_file)
        if process.system(comp_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_zpipe: zpipe compress failed")

        decomp_cmd = './zpipe -d < %s > %s' % (out_file, new_file)
        if process.system(decomp_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_zpipe: zpipe decompress failed")

    def test_gzip_series(self):
        '''
        Running NX-GZIP: Compress/Decompress using gzip series
        '''
        self.log.info("NX-GZIP: test_gzip_series: Running gzip series")
        self.build_tests("samples")
        self.create_ddfile()

        mnt_path = "/mnt/ramdisk"
        file_size = self.params.get('file_size', default='150')
        tmpfs_size = self.params.get('tmpfs_size', default='50')

        free_mem = memory.meminfo.MemFree.m
        if int(tmpfs_size) > free_mem:
            self.cancel("NX-GZIP: test_gzip_series: Test needs minimum %s\
                        memory" % tmpfs_size)

        if not os.path.ismount('%s' % mnt_path):
            if not os.path.exists('%s' % mnt_path):
                os.makedirs('%s' % mnt_path)
        self.device = Partition(device="none", mountpoint='%s' % mnt_path)
        self.device.mount(mountpoint='%s' % mnt_path, fstype="tmpfs",
                          args="-o size=%sG" % tmpfs_size, mnt_check=False)

        gzip_series_cmd = './gzip-series.sh %sgb-file' % file_size
        if process.system(gzip_series_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_gzip_series: gzip_series tests failed")

        self.log.info("NX-GZIP: test_gzip_series: Cleaning..")
        if os.path.exists('%s' % mnt_path):
            self.device.unmount()
            shutil.rmtree('%s' % mnt_path)

    def test_numamany(self):
        '''
        Running NX-GZIP: Run compress/decompress on multiple numa nodes
        '''
        self.log.info("NX-GZIP: test_numamany:\
                      Run compress/decompress on multiple numa nodes")
        self.build_tests("samples")
        self.create_ddfile()

        file_size = self.params.get('file_size', default='150')
        numamany_cmd = './runnumamany.sh %sgb-file' % file_size
        if process.system(numamany_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_numamany: numa node tests failed")

    def test_simple_decomp(self):
        '''
        Running NX-GZIP: Run simple decomp tests
        '''
        self.log.info("NX-GZIP: test_simple_decomp:simple decomp tests")
        self.build_tests("samples")
        self.create_ddfile()

        file_size = self.params.get('file_size', default='150')
        dcomp_cmd = 'sh ./rundecomp.sh %sgb-file' % file_size
        if process.system(dcomp_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_simple_dcomp: dcomp tests failed")

    def test_zpipe_repeat(self):
        '''
        Running NX-GZIP: Run zpipe repeates tests
        '''
        self.log.info("NX-GZIP: test_zpipe: Repeated zpipe tests")
        self.download_tarball()
        self.build_tests("samples")

        gcc_cmd = 'gcc -O3 -I../inc_nx -I../ -L../ -L/usr/lib/ \
                  -o zpipe-repeat-test zpipe-repeat-test.c \
                  ../lib/libnxz.a -lpthread'
        if process.system(gcc_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_zpipe_repeat: zpipe repeat tests failed")

        zpipe_cmd = './zpipe-repeat-test < %s/linux-src.tar> %s/junk.Z' \
                    % (self.workdir, self.workdir)
        if process.system(zpipe_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_zpipe_repeat: zpipe repeat tests failed")

        zpipe_d_cmd = './zpipe-repeat-test -d < %s/junk.Z > /dev/null' \
                      % self.workdir
        if process.system(zpipe_d_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_zpipe_repeat: zpipe repeat tests failed")

    def test_compdecomp_threads(self):
        '''
        Running NX-GZIP: Run 100 parallel threads and
        compress/decompress the source file 5 times
        '''
        self.log.info("NX-GZIP: test_compdecomp_threads: Run 100\
                      parallel threads and compress/decompress\
                      the source file 5 times")
        self.download_tarball()
        self.build_tests("samples")

        thr = self.params.get('comp_decomp_thr', default='100')
        iters = self.params.get('comp_decomp_iter', default='5')

        compdecomp_cmd = './compdecomp_th %s/linux-src.tar %s %s'\
                         % (self.workdir, thr, iters)
        if process.system(compdecomp_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_compdecomp_threads:\
                      compress/decompress with parallel threads failed")

    def test_dictionary(self):
        '''
        Running NX-GZIP: Test deflate/inflate with dictionary file
        '''
        self.log.info("NX-GZIP: test_dictionary:\
                      Run deflate/inflate with dictionary file")
        self.download_tarball()
        self.build_tests("samples")
        make_cmd = 'make zpipe_dict'
        if process.system(make_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_dictionary: make failed")

        dict_cmd = './dict-test.sh alice29.txt %s/linux-src.tar'\
                   % self.workdir
        if process.system(dict_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_test_dictionary:\
                      deflate/inflate with dictionary tests failed")

    def test_nxdht(self):
        '''
        Running NX-GZIP: Run nxdht tests
        '''
        self.log.info("NX-GZIP: test_nxdht: Run nxdht tests")
        self.download_tarball()
        self.build_tests("samples")

        nxdht_cmd = './gzip_nxdht_test %s/linux-src.tar' % self.workdir
        if process.system(nxdht_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_nxdht: nxdht tests failed")

    def test_zlib_series(self):
        '''
        Running NX-GZIP: Run compress/decompress zlib series
        '''
        self.log.info("NX-GZIP: test_zlib_series:\
                      Run compress/decomp zlib test series")
        self.build_tests("samples")
        self.create_ddfile()

        file_size = self.params.get('file_size', default='150')
        zlib_cmd = './zlib-run-series.sh %sgb-file' % file_size
        if process.system(zlib_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_zlib_series: zlib test series failed")

    def test_compdecomp_2nx(self):
        '''
        Running NX-GZIP: Run compress/decompress on 2nx devices
        '''
        self.log.info("NX-GZIP: test_compdecomp_2nx:\
                      Run compress/decompress on 2nx devices")
        self.build_tests("samples")
        self.create_ddfile()

        file_size = self.params.get('file_size', default='150')
        nx2_cmd = './run-series_2nx.sh %sgb-file' % file_size
        if process.system(nx2_cmd, shell=True, ignore_status=True):
            self.fail("NX-GZIP: test_compdecomp_2nx:\
                      comp/decomp on 2nx devices tests failed")

    def test_oct(self):
        '''
        Running NX-GZIP: Run OCT - Libnxz Output Comparison Tests
        '''
        self.log.info("NX-GZIP: test_oct:\
                      Libnxz Output Comparison Tests")
        test_dir = os.path.join(self.teststmpdir, "oct")
        shutil.copyfile(self.get_data('minigzipsh'),
                        os.path.join(test_dir, 'minigzipsh'))
        os.chdir(test_dir)
        os.chmod('minigzipsh', 0o777)
        self.build_tests("oct")

    def test_kself_nxgzip(self):
        '''
        nx-gzip tests from kself tests
        '''
        self.testdir = "tools/testing/selftests/powerpc/nx-gzip"
        linux_src = 'https://github.com/torvalds/linux/archive/master.zip'
        self.output = "linux-master"
        match = next(
                (ext for ext in [".zip", ".tar"] if ext in linux_src), None)
        if match:
           tarball = self.fetch_asset("kselftest%s" % match,
                                      locations=[linux_src], expire='1d')
           archive.extract(tarball, self.teststmpdir)
        else:
           git.get_repo(linux_src, destination_dir=self.teststmpdir)
        self.buldir = os.path.join(self.teststmpdir, self.output)
        self.build_tests(self.testdir)

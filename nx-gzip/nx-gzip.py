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
import tempfile
from avocado import Test
from avocado.utils import archive, build, process, distro, git
from avocado.utils.software_manager import SoftwareManager

class NXGZipTests(Test):
    """
    nx-gzip test cases make use of testsuite provided by the
    library source package and performs functional tests.
    """

    def download_tarball(self):
        '''
        Get linux source tarball for compress/decompress
        '''
        self.tmpdir = tempfile.mkdtemp()
        os.chdir(self.tmpdir)
        if process.system('git clone https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git', shell=True):
            self.fail("NX-GZIP: download_tarball: linux source git failed")
        if process.system('tar cvf linux-src.tar %s/linux' % self.tmpdir, shell=True):
            self.fail("NX-GZIP: download_tarball: linux source tarball download failed")
        process.system('ls -l %s' % self.tmpdir, shell=True)

    def setUp(self):
        """
	Install pre-requisite packages 
        """

        smg = SoftwareManager()
        self.dist = distro.detect()
        if self.dist.name not in ['SuSE', 'rhel']:
            self.cancel('Unsupported OS %s' % self.dist.name)

        deps = ['gcc', 'make', 'zlib-*']
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % (package))

        self.url = self.params.get(
            'url', default="https://github.com/libnxz/power-gzip")
        self.branch = self.params.get('branch', default='master')

        git.get_repo(self.url, branch=self.branch,
                     destination_dir=self.teststmpdir)

        self.sourcedir = self.teststmpdir
        os.chdir(self.sourcedir)
        build.make(self.sourcedir)
        self.log.info("Sourcedir: %s" % self.sourcedir)

    def test_inflate_deflate(self):
        """
        Running NX-GZIP: Inflate and Deflate tests 
        """
        self.log.info("NX-GZIP: test_inflate_deflate: Inflate and Deflate tests")
        failed_tests = []
        output = build.run_make(
            self.sourcedir, extra_args='check', process_kwargs={"ignore_status": True})
        for line in output.stdout.decode('utf-8').splitlines():
            if "failed" in line:
                failed_tests.append(line)
        if failed_tests:
            self.fail("%s" % failed_tests)

    def test_basic_comp_decomp(self):
        """
        Running NX-GZIP: Simple compression/decompression 
        """
        self.log.info("NX-GZIP: test_basic_comp_decomp: basic compression/decompression tests")
        test_dir = '%s/selftest' % (self.sourcedir)
        os.chdir(test_dir)
        failed_tests = []
        output = build.run_make(
            test_dir, extra_args='run_tests', process_kwargs={"ignore_status": True})
        for line in output.stdout.decode('utf-8').splitlines():
            if "failed" in line:
                failed_tests.append(line)
        if failed_tests:
            self.fail("%s" % failed_tests)

    def test_kernel_oops(self):
        """
        Running NX-GZIP: testing kernel oops 
        """
        self.log.info("NX-GZIP: test_kernel_oops: testing kernel oops tests")
        test_dir = '%s/test' % (self.sourcedir)
        os.chdir(test_dir)

        failed_tests = []
        output = build.run_make(
            test_dir, extra_args='unsafe-check', process_kwargs={"ignore_status": True})
        for line in output.stdout.decode('utf-8').splitlines():
            if "failed" in line:
                failed_tests.append(line)
        if failed_tests:
            self.fail("%s" % failed_tests)

    def test_zpipe(self):
         """
         Running NX-GZIP: Compress/Decompress using zpipe which uses nx-gzip
         """
         self.log.info("NX-GZIP: test_zpipe: Compress/Decompress using zpipe which uses nx-gzip")

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         file_size = self.params.get('file_size', default='5')
         out_file = self.params.get('out_file', default='/tmp/out_file')
         new_file = self.params.get('new_file', default='/tmp/new_file')

         dd_cmd = 'dd if=/dev/urandom of=/tmp/%sgb-file bs=1000000000 count=%s' % (file_size, file_size)
         if process.system(dd_cmd):
             self.fail("NX-GZIP: test_zpipe: dd file creation failed")

         comp_cmd = './zpipe < /tmp/%sgb-file > %s' % (file_size, out_file)
         if process.system(comp_cmd, shell=True):
             self.fail("NX-GAIP: test_zpipe: zpipe compress failed")

         decomp_cmd = './zpipe -d < %s > %s' % (out_file, new_file)
         if process.system(decomp_cmd, shell=True):
             self.fail("NX-GAIP: test_zpipe: zpipe decompress failed")

         self.log.info("test_zpipe: remove /tmp/%sgb-file file" % file_size)
         if os.remove("/tmp/%sgb-file" % file_size):
             self.fail("NX-GZIP: test_zpipe: %sgb-file remove failed" % file_size)

    def test_zpipe_repeat(self):
         """
         Running NX-GZIP: Run zpipe repeates tests
         """
         self.log.info("NX-GZIP: test_zpipe: Repeated zpipe tests")

         self.download_tarball()

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         gcc_cmd = 'gcc -O3 -I../inc_nx -I../ -L../ -L/usr/lib/ -o zpipe-repeat-test zpipe-repeat-test.c ../lib/libnxz.a -lpthread'
         if process.system(gcc_cmd, shell=True):
             self.fail("NX-GZIP: test_zpipe_repeat: zpipe repeat tests failed")

         zpipe_cmd = './zpipe-repeat-test < %s/linux-src.tar > %s/junk.Z' % (self.tmpdir, self.tmpdir)
         if process.system(zpipe_cmd, shell=True):
             self.fail("NX-GZIP: test_zpipe_repeat: zpipe repeat tests failed")

         zpipe_d_cmd = './zpipe-repeat-test -d < %s/junk.Z > /dev/null' % self.tmpdir
         if process.system(zpipe_d_cmd, shell=True):
             self.fail("NX-GZIP: test_zpipe_repeat: zpipe repeat tests failed")

    def test_gzip_series(self):
         """
         Running NX-GZIP: Compress/Decompress using gzip series 
         """
         self.log.info("NX-GZIP: test_gzip_series: Running gzip series")

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         file_size = self.params.get('file_size', default='5')

         dd_cmd = 'dd if=/dev/urandom of=/tmp/%sgb-file bs=1000000000 count=%s' % (file_size, file_size)
         if process.system(dd_cmd):
             self.fail("NX-GZIP: test_gzip_series: dd file creation failed")

         mkdir_cmd = 'mkdir /mnt/ramdisk'
         if process.system(mkdir_cmd):
             self.fail("NX-GZIP: test_gzip_series: mnt cmd failed")
         mnt_ramdisk_cmd = 'mount -t tmpfs -o size=250G tmpfs /mnt/ramdisk/'
         if process.system(mnt_ramdisk_cmd):
             self.fail("NX-GZIP: test_gzip_series: mnt ramdisk failed")

         gzip_series_cmd = './gzip-series.sh /tmp/%sgb-file' % file_size
         if process.system(gzip_series_cmd, shell=True):
             self.fail("NX-GZIP: test_gzip_series: gzip_series tests failed")

         self.log.info("test_gzip_series, remove /tmp/%sgb-file file" % file_size)
         if os.remove("/tmp/%sgb-file" % file_size):
             self.fail("NX-GZIP: test_gzip_series: %sgb-file remove failed" % file_size)
         if process.system("umount /mnt/ramdisk", shell=True):
             self.fail("NX-GZIP:test_gzip_series: umount /mnt/ramdisk failed")
         if os.path.exists("/mnt/ramdisk"):
             shutil.rmtree("/mnt/ramdisk")

    def test_compdecomp_threads(self):
         """
         Running NX-GZIP: Run 100 parallel threads and compress/decompress the source file 5 times
         """
         self.log.info("NX-GZIP: test_compdecomp_threads: Run 100 parallel threads and compress/decompress the source file 5 times")
       
         self.download_tarball()

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         thr = self.params.get('comp_decomp_thr', default='100')
         iter = self.params.get('comp_decomp_iter', default='5')

         compdecomp_cmd = './compdecomp_th %s/linux-src.tar %s %s' % (self.tmpdir, thr, iter)
         if process.system(compdecomp_cmd, shell=True):
             self.fail("NX-GZIP: test_compdecomp_threads: compress/decompress with parallel threads failed")

    def test_numamany(self):
         """
         Running NX-GZIP: Run compress/decompress on multiple numa nodes
         """
         self.log.info("NX-GZIP: test_numamany: Run compress/decompress on multiple numa nodes")

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         file_size = self.params.get('file_size', default='5')
         dd_cmd = 'dd if=/dev/urandom of=%sgb-file bs=1000000000 count=%s' % (file_size, file_size)
         if process.system(dd_cmd):
             self.fail("NX-GZIP: test_mumamany: dd file creation failed")

         numamany_cmd = './runnumamany.sh %sgb-file' % file_size
         if process.system(numamany_cmd, shell=True):
             self.fail("NX-GZIP: test_numamany: numa node tests failed")

         self.log.info("test_numamany, remove %sgb-file file" % file_size)
         if os.remove("%sgb-file" % file_size):
             self.fail("NX-GZIP: test_numamany: %sgb-file remove failed" % file_size)

    def test_dictionary(self):
         """
         Running NX-GZIP: Test deflate/inflate with dictionary file
         """
         self.log.info("NX-GZIP: test_dictionary: Run deflate/inflate with dictionary file")

         self.download_tarball()

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         dict_cmd = './dict-test.sh alice29.txt %s/linux-src.tar' % self.tmpdir
         if process.system(dict_cmd, shell=True):
             self.fail("NX-GZIP: test_test_dictionary: deflate/inflate with dictionary tests failed")

    def test_nxdht(self):
         """
         Running NX-GZIP: Run nxdht tests
         """
         self.log.info("NX-GZIP: test_nxdht: test failed")

         self.download_tarball()

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         nxdht_cmd = './gzip_nxdht_test %s/linux-src.tar' % self.tmpdir
         if process.system(nxdht_cmd, shell=True):
             self.fail("NX-GZIP: test_nxdht: nxdht tests failed")

    def test_simple_decomp(self):
         """
         Running NX-GZIP: Run simple decomp tests
         """
         self.log.info("NX-GZIP: test_simple_decomp: test failed")

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         file_size = self.params.get('file_size', default='5')
         dd_cmd = 'dd if=/dev/urandom of=%sgb-file bs=1000000000 count=%s' % (file_size, file_size)
         if process.system(dd_cmd):
             self.fail("NX-GZIP: test_simple_decomp_2nx: dd file creation failed")

         dcomp_cmd = 'sh ./rundecomp.sh 5gb-file'
         if process.system(dcomp_cmd, shell=True):
             self.fail("NX-GZIP: test_simple_dcomp: dcomp tests failed")

    def test_zlib_series(self):
         """
         Running NX-GZIP: Run compress/decompress zlib series
         """
         self.log.info("NX-GZIP: test_zlib_series: Run compress/decomp zlib test series")

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         file_size = self.params.get('file_size', default='5')
         dd_cmd = 'dd if=/dev/urandom of=%sgb-file bs=1000000000 count=%s' % (file_size, file_size)
         if process.system(dd_cmd):
             self.fail("NX-GZIP: test_zlib_series: dd file creation failed")

         nx2_cmd = './zlib-run-series.sh %sgb-file' % file_size
         if process.system(nx2_cmd, shell=True):
             self.fail("NX-GZIP: test_zlib_series: zlib test series failed")

         self.log.info("remove %sgb-file file" % file_size)
         if os.remove("%sgb-file" % file_size):
             self.fail("NX-GZIP: test_zlib_series: %sgb-file remove failed" % file_size)

    def test_compdecomp_2nx(self):
         """
         Running NX-GZIP: Run compress/decompress on 2nx devices
         """
         self.log.info("NX-GZIP: test_compdecomp_2nx: Run compress/decompress on 2nx devices")

         test_dir = '%s/samples' % (self.sourcedir)
         os.chdir(test_dir)
         output = build.run_make(
             test_dir, extra_args='bench', process_kwargs={"ignore_status": True})

         file_size = self.params.get('file_size', default='5')
         dd_cmd = 'dd if=/dev/urandom of=%sgb-file bs=1000000000 count=%s' % (file_size, file_size)
         if process.system(dd_cmd):
             self.fail("NX-GZIP: test_compdecomp_2nx: dd file creation failed")

         nx2_cmd = './run-series_2nx.sh %sgb-file' % file_size
         if process.system(nx2_cmd, shell=True):
             self.fail("NX-GZIP: test_compdecomp_2nx: comp/decomp on 2nx devices tests failed")

         self.log.info("remove %sgb-file file" % file_size)
         if os.remove("%sgb-file" % file_size):
             self.fail("NX-GZIP: test_compdecomp_2nx: %sgb-file remove failed" % file_size)

    def tearDown(self):
        if self.name.uid == 5 or self.name.uid == 7 or self.name.uid == 9 or self.name.uid == 10: 
           self.log.info('Cleaning up')
           if os.path.exists("%s/linux" % self.tmpdir):
                 shutil.rmtree("%s/linux" % self.tmpdir)
           if os.remove("%s/linux-src.tar" % self.tmpdir):
               self.fail("NX-GZIP: tearDown: clean up routine failed")


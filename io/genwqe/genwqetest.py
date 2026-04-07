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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
This Suite tests the GenWQE Accelerator.
"""

import os
import shutil
import time
from avocado import Test
from avocado.utils import process
from avocado.utils import download
from avocado.utils import dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class GenWQETest(Test):

    """
    Test Class for GenWQE Tests.

    :param device: Name of the GenWQE device
    :param test_tar_url: URL for the test tarball
    """

    def setUp(self):
        """
        Install genwqe packages, and downloads test tarball.
        """
        self.card = self.params.get('device', default='0')
        url = "http://corpus.canterbury.ac.nz/resources/cantrbry.tar.gz"
        self.url = self.params.get('test_tar_url', default=url)
        self.files_used = []
        self.dirs_used = []
        if not os.path.isdir("/sys/class/genwqe/genwqe%s_card/" % self.card):
            self.cancel("Device %s does not exist" % self.card)
        smm = SoftwareManager()
        for pkg in ['genwqe-tools', 'genwqe-zlib']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)
        self.test_tar = download.get_file(self.url, "cantrbry.tar.gz")
        self.files_used = [self.test_tar]

    def test_genwqe_echo(self):
        """
        Tests genwqe_echo on the device.
        """
        cmd = "genwqe_echo -C %s -c 100000 -f -s hi" % self.card
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_echo fails")

    def test_genwqe_mt_perf(self):
        """
        Tests genwqe_mt_perf on the device.
        """
        cmd = "genwqe_mt_perf -A SW -C %s -v" % self.card
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_mt_perf SW fails")
        cmd = "genwqe_mt_perf -A GENWQE -C %s -v" % self.card
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_mt_perf GENWQE fails")

    def test_genwqe_test_gz(self):
        """
        Tests genwqe_test_gz on the device.
        """
        data_tar = "data.tar.gz"
        shutil.copyfile(self.test_tar, data_tar)
        self.files_used.append(data_tar)
        data_dir = "/usr/share/testdata/"
        self.dirs_used.append(data_dir)
        if not os.path.isdir(data_dir):
            os.makedirs(data_dir)
        cmd = "genwqe_test_gz -A SW -C %s -v -t %s" % (self.card, data_tar)
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_test_gz SW fails")
        cmd = "genwqe_test_gz -A GENWQE -S -C %s -v -t %s" % (self.card,
                                                              data_tar)
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_test_gz SW forced fails")
        cmd = "genwqe_test_gz -A GENWQE -C %s -v -t %s" % (self.card, data_tar)
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_test_gz GENWQE fails")

    def test_genwqe_memcopy(self):
        """
        Tests genwqe_memcopy on the device.
        """
        failures = []
        in_file = "in.bin"
        out_file = "out.bin"
        self.files_used.extend([in_file, out_file])
        for err in ['', '0x1', '0x2', '0x4', '0x8']:
            cmd = "dd if=/dev/urandom bs=4096 count=1000 of=%s" % in_file
            process.system(cmd, shell=True)
            err_opt = ''
            if err:
                err_opt = " -Y %s" % err
            cmd = "genwqe_memcopy -A GENWQE -C %s -c 1000 -v -F -D %s " \
                "--patternfile %s %s" % (self.card, err_opt, in_file, out_file)
            if process.system(cmd, shell=True, ignore_status=True) and not err:
                self.fail("genwqe_memcopy %s fails" % err_opt)
            cmd = "diff %s %s" % (in_file, out_file)
            if process.system(cmd, shell=True, ignore_status=True):
                failures.append(err_opt)
            for fil in [in_file, out_file]:
                os.remove(fil)
        if failures:
            self.fail("%s fails on file comparison" % ", ".join(failures))

    def test_genwqe_gzip_gunzip(self):
        """
        Tests genwqe_gzip and genwqe_gunzip on the device.
        """
        self.files_used.extend(["file", "file.gz"])
        cmd = "dd if=/dev/urandom bs=4096 count=100000 of=file"
        process.system(cmd, shell=True, ignore_status=True)
        for opt in ['', '-1', '-9']:
            orig_size = os.stat("file").st_size
            cmd = "genwqe_gzip -A GENWQE -B %s file %s" % (self.card, opt)
            if process.system(cmd, shell=True, ignore_status=True):
                self.fail("genwqe_gzip %s fails" % opt)
            cmd = "genwqe_gunzip -A GENWQE -B %s file.gz %s" % (self.card, opt)
            if process.system(cmd, shell=True, ignore_status=True):
                self.fail("genwqe_gunzip %s fails" % opt)
            processed_size = os.stat("file").st_size
            if orig_size != processed_size:
                self.log.debug("Original size: %s", orig_size)
                self.log.debug("Processed size: %s", processed_size)
                self.fail("File size not retained after gzip and gunzip back")

    def test_genwqe_poke(self):
        """
        Tests genwqe_poke on the device.
        """
        dmesg.clear_dmesg()
        cmd = "genwqe_poke -A GENWQE -C %s 0x00000008 0x001" % self.card
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_poke fails")
        time.sleep(10)
        recovered = 0
        cmd = "dmesg -C"
        for line in process.system_output(cmd, shell=True,
                                          ignore_status=True).splitlines():
            if "chip reload/recovery" in line:
                recovered = 1
        if recovered == 0:
            self.fail("genwqe_poke card recovery fails")

    def test_genwqe_peek(self):
        """
        Tests genwqe_peek on the device.
        """
        cmd = "genwqe_peek -C %s -A GENWQE 0x0" % self.card
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_peek fails")

    def test_genwqe_ffdc(self):
        """
        Creates namespace on the device.
        """
        cmd = "genwqe_ffdc -Q -C %s -v" % self.card
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_ffdc fails")

    def test_genwqe_cksum(self):
        """
        Creates namespace on the device.
        """
        cmd = "genwqe_cksum -C %s -c -D -v %s" % (self.card, self.test_tar)
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_cksum fails")
        cmd = "genwqe_cksum -C %s -c -G -D -v %s" % (self.card, self.test_tar)
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("genwqe_cksum with scatter gather list support fails")

    def tearDown(self):
        """
        Clean up
        """
        for fil in self.files_used:
            if os.path.isfile(fil):
                os.remove(fil)
        for fol in self.dirs_used:
            if os.path.isdir(fol):
                shutil.rmtree(fol)

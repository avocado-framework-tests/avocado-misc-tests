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
# Author: Pooja B Surya <pooja@linux.vnet.ibm.com>

import os

from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process, archive
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro


class Openblas(Test):
    """
    OpenBLAS is an optimized BLAS library based on GotoBLAS2 1.13 BSD version.
    This test runs openblas tests
    """
    def setUp(self):
        smm = SoftwareManager()
        detected_distro = distro.detect()
        packages = ['make', 'gcc']
        if detected_distro.name == "Ubuntu":
            packages.append("gfortran")
        else:
            packages.append("gcc-gfortran")
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.skip(package + ' is needed for the test to be run')
        url = "https://github.com/xianyi/OpenBLAS/archive/develop.zip"
        tarball = self.fetch_asset("OpenBLAS-develop.zip", locations=[url])
        archive.extract(tarball, self.srcdir)
        openblas_dir = os.path.join(self.srcdir, "OpenBLAS-develop")
        os.chdir(openblas_dir)
        openblas_bin_dir = os.path.join(openblas_dir, 'bin')
        os.mkdir(openblas_bin_dir)
        build.make(openblas_dir, extra_args='FC=gfortran')
        build.make(openblas_dir, extra_args='PREFIX=%s install' %
                   openblas_bin_dir)
        os.chdir("test/")

    def test(self):
        process.run("make", ignore_status=True, sudo=True)
        logfile = os.path.join(self.logdir, "stdout")
        failed_tests = process.system_output(
            "grep -w FAIL %s" % logfile, shell=True, ignore_status=True)
        if failed_tests:
            self.fail("test failed, Please check debug log for failed"
                      "test cases")


if __name__ == "__main__":
    main()

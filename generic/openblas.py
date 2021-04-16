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
import re

from avocado import Test
from avocado.utils import build
from avocado.utils import archive, process, cpu
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
        if detected_distro.name in ["Ubuntu", 'debian']:
            packages.append("gfortran")
        elif detected_distro.name == "SuSE":
            packages.extend(["gcc-fortran", "libgfortran4"])
        else:
            packages.append("gcc-gfortran")
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(' %s is needed for the test to be run' % package)
        url = "https://github.com/xianyi/OpenBLAS/archive/develop.zip"
        tarball = self.fetch_asset("OpenBLAS-develop.zip", locations=[url],
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        openblas_dir = os.path.join(self.workdir, "OpenBLAS-develop")
        openblas_bin_dir = os.path.join(openblas_dir, 'bin')
        os.mkdir(openblas_bin_dir)
        cmd = "gcc --version"
        output = process.system_output(cmd, shell=True).decode("utf-8")
        gcc_ver = re.search(r'\d+', output.splitlines()[0])
        proc_type = cpu.get_family()
        self.target = ""
        if int(gcc_ver.group()) < 10 and 'power10' in proc_type:
            self.target = "TARGET=POWER9"
            build.make(openblas_dir, extra_args='FC=gfortran '
                       'ISMAXKERNEL=imax.S ISMINKERNEL=imin.S TARGET=POWER9')
        else:
            build.make(openblas_dir, extra_args='FC=gfortran '
                       'ISMAXKERNEL=imax.S ISMINKERNEL=imin.S')
        build.make(openblas_dir, extra_args='PREFIX=%s install' %
                   openblas_bin_dir)
        self.test_dir = os.path.join(openblas_dir, "test")

    def test(self):
        result = build.run_make(self.test_dir, extra_args=self.target)
        for line in str(result).splitlines():
            if '[FAIL]' in line:
                self.fail("test failed, Please check debug log for failed"
                          "test cases")

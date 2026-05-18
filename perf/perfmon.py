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
# Copyright: 2016 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#

import os

from avocado import Test
from avocado.utils import process, build, git, distro
from avocado.utils.software_manager.manager import SoftwareManager


class Perfmon(Test):

    """
    performance monitoring on Linux : test perf_events on Linux
    :avocado: tags=perf,perfmon
    """

    def setUp(self):

        # libpfm4 build deps only (gcc, make, ncurses) — no linux-tools / perf packages here.
        smm = SoftwareManager()
        dist = distro.detect()

        deps = ["gcc", "make"]
        if dist.name in ['Ubuntu', 'debian']:
            deps.extend(['libncurses-dev'])
        elif dist.name in ['rhel', 'SuSE']:
            deps.extend(['ncurses-devel'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % package)

        # Optional mux: `perf_bin` in perfmon.py.data/*.yaml — tests/validate uses `perf` from PATH.
        perf_path = (self.params.get('perf_bin', default='') or '').strip()
        self._mux_perf_bin = bool(perf_path)
        self._saved_path = os.environ.get("PATH", "")
        if perf_path:
            if not os.path.isfile(perf_path):
                self.cancel("perf not found at %s" % perf_path)
            ret = process.run("%s --version" % perf_path, ignore_status=True,
                              shell=True)
            if ret.exit_status != 0:
                self.cancel("perf at %s is not functional" % perf_path)
            ver = getattr(ret, "stdout_text", ret.stdout.decode()).strip()
            self.log.info("Perf version: %s", ver)
            self.perf_bin = perf_path
            bindir = os.path.dirname(os.path.abspath(perf_path))
            os.environ["PATH"] = bindir + os.pathsep + self._saved_path
        else:
            self.perf_bin = "perf"

        git.get_repo('https://git.code.sf.net/p/perfmon2/libpfm4',
                     destination_dir=self.workdir)

        os.chdir(self.workdir)

        build.make('.')

    def test(self):

        self.log.info("Running tests/validate with perf resolved as: %s",
                      self.perf_bin)
        out = process.system_output('%s ' % os.path.join(
            self.workdir, 'tests', 'validate'))
        if isinstance(out, bytes):
            out = out.decode("utf-8")
        if 'fail' in out:
            self.fail("test failed:check manually")

    def tearDown(self):
        if getattr(self, "_mux_perf_bin", False):
            os.environ["PATH"] = self._saved_path

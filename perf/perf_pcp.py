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
# Copyright: 2019 IBM.
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import cpu, distro, genio, process
from avocado.utils.software_manager import SoftwareManager


class PCP(Test):

    """
    Performance Co Pilot (PCP)
    1. Starts pmcd daemon
    2. Install perfevent pmda
    3. Test pcp command
    4. Test 24x7 events
    5. Remove perfevent pmda
    :avocado: tags=perf,pcp
    """

    def setUp(self):
        smg = SoftwareManager()
        self.cpu_arch = cpu.get_cpu_arch().lower()
        self.dist = distro.detect()
        if self.dist.name in ['centos', 'fedora', 'rhel', 'SuSE']:
            pkgs = ['pcp', 'pcp-pmda-perfevent']
        else:
            self.cancel("PCP is not supported on %s" % self.dist.name)

        for pkg in pkgs:
            if not smg.check_installed(pkg) and not smg.install(pkg):
                self.cancel("Package %s is missing/could not be installed"
                            % pkg)

    def lpar_24x7_ppc64le_check(self):
        if self.dist.arch != 'ppc64le':
            self.cancel("Not supported on %s" % self.dist.arch)
        # Check if this is a guest
        # 24x7 is not suported on guest
        if "emulated by" in genio.read_file("/proc/cpuinfo").rstrip('\t\r\n\0'):
            self.cancel("24x7: This test is not supported on guest")

        # Check if 24x7 is present
        if not os.path.exists("/sys/bus/event_source/devices/hv_24x7"):
            self.cancel("hv_24x7 Event doesn't exist.This feature is supported"
                        " only on LPAR")

    def test_pmcd_daemon(self):
        output = process.run("systemctl start pmcd", shell=True)
        output = process.run("systemctl status pmcd", shell=True)
        if "active (running)" not in output.stdout:
            self.fail("PCP: Can not start pmcd daemon")

    def test_pmda_perfevent_install(self):
        if not os.path.isfile("/var/lib/pcp/pmdas/perfevent/Install"):
            self.fail("PCP: perfevent pmda package not installed")
        os.chdir("/var/lib/pcp/pmdas/perfevent/")
        cmd = "echo pipe | ./Install"
        output = process.run(cmd, shell=True)
        if "Check perfevent metrics have appeared" not in output.stdout:
            self.fail("PCP: perfevent pmda install failed.")
        process.run("systemctl restart pmcd", shell=True)
        output = process.run("systemctl status pmcd", shell=True)
        if "active (running)" and "pmdaperfevent" not in output.stdout:
            self.fail("PCP: perfevent pmda not reflected in pmcd daemon")

    def test_pcp_cmd(self):
        output = process.run("pcp", shell=True)
        if "Cannot connect to PMCD" in output.stdout:
            self.fail("PCP: pmcd daemon dead")

    def test_perfevent_24x7_events(self):
        self.lpar_24x7_ppc64le_check()
        if self.cpu_arch == 'power8':
            self.cancel("Not supported on Power8")
        # -s 2 collects two samples
        cmd = "pmval -s 2 perfevent.hwcounters.hv_24x7.PM_MBA0_CLK_CYC.value"
        process.run(cmd, shell=True)
        # -s 2 collects two samples
        cmd = "pmval -s 2 perfevent.hwcounters.hv_24x7.PM_PB_CYC.value"
        process.run(cmd, shell=True)

    def test_pmda_perfevent_remove(self):
        os.chdir("/var/lib/pcp/pmdas/perfevent/")
        cmd = "./Remove"
        output = process.run(cmd, shell=True)
        if "perfevent metrics have gone away ... OK" not in output.stdout:
            self.fail("PCP: perfevent pmda removal failed.")
        process.run("systemctl restart pmcd", shell=True)
        output = process.run("systemctl status pmcd", shell=True)
        if "active (running)" and "pmdaperfevent" in output.stdout:
            self.fail("PCP: perfevent pmda not removed from pmcd daemon")


if __name__ == "__main__":
    main()

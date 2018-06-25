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
# Copyright: 2018 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
iperf is a tool for active measurements of the maximum achievable
bandwidth on IP networks.
"""

import os
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process
from avocado.utils.genio import read_file


class Iperf(Test):
    """
    Iperf Test
    """

    def setUp(self):
        """
        To check and install dependencies for the test
        """
        smm = SoftwareManager()
        for pkg in ["gcc", "autoconf", "perl", "m4"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface", default="")
        self.peer_ip = self.params.get("peer_ip", default="")
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if self.peer_ip == "":
            self.cancel("%s peer machine is not available" % self.peer_ip)
        self.peer_user = self.params.get("peer_user_name", default="root")
        iperf_download = self.params.get("iperf_download", default="https:"
                                         "//github.com/esnet/"
                                         "iperf/archive/master.zip")
        tarball = self.fetch_asset(iperf_download, expire='7d')
        archive.extract(tarball, self.teststmpdir)
        self.iperf_dir = os.path.join(self.teststmpdir, "iperf-master")
        cmd = "scp -r %s %s@%s:/tmp" % (self.iperf_dir, self.peer_user,
                                        self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.cancel("unable to copy the iperf into peer machine")
        cmd = "ssh %s@%s \"cd /tmp/iperf-master;./configure; " \
              "make\"" % (self.peer_user, self.peer_ip)
        if process.system(cmd, ignore_status=True, shell=True, sudo=True):
            self.cancel("Unable to compile Iperf into peer machine")
        self.iperf_run = str(self.params.get("IPERF_SERVER_RUN", default=0))
        if self.iperf_run == '1':
            cmd = "ssh %s@%s \"cd /tmp/iperf-master/src/;./iperf3 -s\""\
                  % (self.peer_user, self.peer_ip)
            obj = process.SubProcess(cmd, verbose=False, shell=True)
            obj.start()
        os.chdir(self.iperf_dir)
        process.system('./configure', shell=True)
        build.make(self.iperf_dir)
        self.iperf = os.path.join(self.iperf_dir, 'src')
        self.expected_tp = self.params.get("EXPECTED_THROUGHPUT", default="85")
        speed = int(read_file("/sys/class/net/%s/speed" % self.iface))
        self.expected_tp = int(self.expected_tp) * speed / 100

    def test(self):
        """
        Test run is a One way throughput test. In this test, we have one host
        transmitting (or receiving) data from a client. This transmit large
        messages using multiple threads or processes.
        """
        os.chdir(self.iperf)
        cmd = "iperf3 -c %s" % self.peer_ip
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status:
            self.fail("FAIL: Iperf Run failed")
        for line in result.stdout.splitlines():
            if 'sender' in line:
                tput = int(line.split()[6].split('.')[0])
                if tput < self.expected_tp:
                    self.fail("FAIL: Throughput Actual - %d, Expected - %d"
                              % (tput, self.expected_tp))

    def tearDown(self):
        """
        Killing Iperf process in peer machine
        """
        cmd = "ssh %s@%s \"pkill iperf; rm -rf /tmp/iperf-master\""\
              % (self.peer_user, self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("Either the ssh to peer machine machine\
                       failed or iperf process was not killed")


if __name__ == "__main__":
    main()

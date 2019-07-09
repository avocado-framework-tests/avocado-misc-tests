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
# Author: Harsha Thygaraaja <harshkid@linux.vnet.ibm.com>

"""
Unified Performance Tool or uperf for short, is a network
performance measurement tool that supports execution of
workload profiles
"""

import os
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process
from avocado.utils.genio import read_file


class Uperf(Test):
    """
    Uperf Test
    """

    def setUp(self):
        """
        To check and install dependencies for the test
        """
        self.peer_ip = self.params.get("peer_ip", default="")
        self.peer_user = self.params.get("peer_user_name", default="root")
        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = ["gcc", "autoconf", "perl", "m4", "git-core", "automake"]
        if detected_distro.name == "Ubuntu":
            pkgs.extend(["libsctp1", "libsctp-dev", "lksctp-tools"])
        else:
            pkgs.extend(["lksctp-tools", "lksctp-tools-devel"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
            cmd = "ssh %s@%s \"%s install %s\"" % (self.peer_user,
                                                   self.peer_ip,
                                                   smm.backend.base_command,
                                                   pkg)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.cancel("unable to install the package %s on peer machine "
                            % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface", default="")
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if self.peer_ip == "":
            self.cancel("%s peer machine is not available" % self.peer_ip)
        uperf_download = self.params.get("uperf_download", default="https:"
                                         "//github.com/uperf/uperf/"
                                         "archive/master.zip")
        tarball = self.fetch_asset("uperf.zip", locations=[uperf_download],
                                   expire='7d')
        archive.extract(tarball, self.teststmpdir)
        self.uperf_dir = os.path.join(self.teststmpdir, "uperf-master")
        cmd = "scp -r %s %s@%s:/tmp" % (self.uperf_dir, self.peer_user,
                                        self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.cancel("unable to copy the uperf into peer machine")
        cmd = "ssh %s@%s \"cd /tmp/uperf-master;autoreconf -fi;./configure " \
              "ppc64le;make\"" % (self.peer_user, self.peer_ip)
        if process.system(cmd, ignore_status=True, shell=True, sudo=True):
            self.cancel("Unable to compile Uperf into peer machine")
        self.uperf_run = str(self.params.get("UPERF_SERVER_RUN", default=0))
        if self.uperf_run == '1':
            cmd = "ssh %s@%s \"cd /tmp/uperf-master/src;./uperf -s\""\
                  % (self.peer_user, self.peer_ip)
            obj = process.SubProcess(cmd, verbose=False, shell=True)
            obj.start()
        os.chdir(self.uperf_dir)
        process.system('autoreconf -fi', shell=True)
        process.system('./configure ppc64le', shell=True)
        build.make(self.uperf_dir)
        self.expected_tp = self.params.get("EXPECTED_THROUGHPUT", default="85")

    def test(self):
        """
        Test run is a One way throughput test. In this test, we have one host
        transmitting (or receiving) data from a client. This transmit large
        messages using multiple threads or processes.
        """
        speed = int(read_file("/sys/class/net/%s/speed" % self.iface))
        cmd = "h=%s proto=tcp ./src/uperf -m manual/throughput.xml -a" \
            % self.peer_ip
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status:
            self.fail("FAIL: Uperf Run failed")
        for line in result.stdout.splitlines():
            if self.peer_ip in line:
                if 'Mb/s' in line:
                    tput = int(line.split()[3].split('.')[0])
                else:
                    # Converting the throughput calculated in Gb to Mb
                    tput = int(line.split()[3].split('.')[0]) * 1000
                if tput < (int(self.expected_tp) * speed) / 100:
                    self.fail("FAIL: Throughput Actual - %s%%, Expected - %s%%, \
                              Throughput Actual value - %s "
                              % ((tput*100)/speed, self.expected_tp,
                                 str(tput)+'Mb/sec'))
        if 'WARNING' in result.stdout:
            self.log.warn('Test completed with warning')

    def tearDown(self):
        """
        Killing Uperf process in peer machine
        """
        cmd = "ssh %s@%s \"pkill uperf; rm -rf /tmp/uperf-master\""\
              % (self.peer_user, self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("Either the ssh to peer machine machine\
                       failed or uperf process was not killed")


if __name__ == "__main__":
    main()

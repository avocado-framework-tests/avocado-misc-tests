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
# Author: Harsha Thyagaraja <harshkid@linux.vnet.ibm.com>

import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro


class MultiportStress(Test):
    '''
    To perform IO stress on multiple ports on a NIC adapter
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        self.host_interfaces = self.params.get("host_interfaces",
                                               default="").split(",")
        if not self.host_interfaces:
            self.cancel("user should specify host interfaces")
        smm = SoftwareManager()
        if distro.detect().name == 'Ubuntu':
            pkg = 'iputils-ping'
        else:
            pkg = 'iputils'
        if not smm.check_installed(pkg) and not smm.install(pkg):
            self.cancel("Package %s is needed to test" % pkg)
        self.peer_ips = self.params.get("peer_ips",
                                        default="").split(",")
        interfaces = netifaces.interfaces()
        for self.host_interface in self.host_interfaces:
            if self.host_interface not in interfaces:
                self.cancel("interface is not available")
        self.count = self.params.get("count", default="1000")

    def multiport_ping(self, ping_option):
        '''
        Ping to multiple peers parallely
        '''
        parallel_procs = []
        for host, peer in zip(self.host_interfaces, self.peer_ips):
            self.log.info('Starting Ping test')
            cmd = "ping -I %s %s -c %s %s" % (host, peer, self.count,
                                              ping_option)
            obj = process.SubProcess(cmd, verbose=False, shell=True)
            obj.start()
            parallel_procs.append(obj)
        self.log.info('Wait for background processes to finish'
                      ' before proceeding')
        for proc in parallel_procs:
            proc.wait()
        errors = []
        for proc in parallel_procs:
            out_buf = proc.get_stdout()
            out_buf += proc.get_stderr()
            for val in out_buf.decode("utf-8").splitlines():
                if 'packet loss' in val and ', 0% packet loss,' not in val:
                    errors.append(out_buf)
                    break
        if errors:
            self.fail("\n".join(errors))

    def test_multiport_ping(self):
        self.multiport_ping('')

    def test_multiport_floodping(self):
        self.multiport_ping('-f')


if __name__ == "__main__":
    main()

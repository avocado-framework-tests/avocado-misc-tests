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
# Copyright: 2022 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#        :Shaik Abdulla <shaik.abdulla1@ibm.com>

import os
from random import choice
from avocado import Test
from avocado.utils import archive, build, process, distro, memory, cpu, wait
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils import genio, process


class Numactl(Test):

    """
    Self test case of numactl

    :avocado: tags=cpu
    """

    def setUp(self):
        '''
        Build Numactl Test
        Source:
        https://github.com/numactl/numactl
        '''
        # Check for basic utilities
        smm = SoftwareManager()

        detected_distro = distro.detect()
        deps = ['gcc', 'libtool', 'autoconf', 'automake', 'make']
        if detected_distro.name in ["Ubuntu", 'debian']:
            deps.extend(['libnuma-dev'])
        elif detected_distro.name in ["centos", "rhel", "fedora"]:
            deps.extend(['numactl-devel'])
        else:
            deps.extend(['libnuma-devel'])

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

        locations = ["https://github.com/numactl/numactl/archive/master.zip"]
        tarball = self.fetch_asset("numactl.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'numactl-master')

        os.chdir(self.sourcedir)
        process.run('./autogen.sh', shell=True)

        process.run('./configure', shell=True)

        build.make(self.sourcedir)
        self.localhost = LocalHost()
        self.interface = None
        interfaces = os.listdir('/sys/class/net')
        iface = self.params.get("interface", default="")
        self.disk = self.params.get("disk", default="")
        if iface:
            if iface in interfaces:
                self.interface = iface
            elif self.localhost.validate_mac_addr(iface) and iface in self.localhost.get_all_hwaddr():
                self.interface = self.localhost.get_interface_by_hwaddr(iface).name
            else:
                self.cancel("Please check the network device")
            self.ping_count = self.params.get("ping_count", default=100)
            self.peer = self.params.get("peer_ip", default="")
            if not self.peer:
                self.cancel("peer ip need to specify in YAML")
            self.ipaddr = self.params.get("host_ip", default="")
            self.networkinterface = NetworkInterface(self.interface,
                                                     self.localhost)
            if not self.networkinterface.validate_ipv4_format(self.ipaddr):
                self.cancel("Host IP formatt in YAML is incorrect,"
                            "Please specify it correctly")
            if not self.networkinterface.validate_ipv4_format(self.peer):
                self.cancel("Peer IP formatt in YAML is incorrect,"
                            "Please specify it correctly")
            self.netmask = self.params.get("netmask", default="")
            if not (self.networkinterface.validate_ipv4_netmask_format
                    (self.netmask)):
                self.cancel("Netmask formatt in YAML is incorrect,"
                            "please specify it correctly")
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
            self.networkinterface.bring_up()
            if not wait.wait_for(self.networkinterface.is_link_up, timeout=60):
                self.cancel("Link up of interface taking more than"
                            "60 seconds")
            if self.networkinterface.ping_check(self.peer,
                                                count=5) is not None:
                self.cancel("No connection to peer")

        elif self.disk:
            if not self.disk:
                self.cancel("Disk name has not given")
            self.seek = self.params.get("seek", default="1024")
            self.count = self.params.get("count", default="1024")
            self.bytes = self.params.get("bytes", default="1M")
            self.input_file = self.params.get("input_file",
                                              default="/dev/zero")
        self.device = self.params.get('pci_device', default="")

        for subtest in ["preferred_node", "cpunode_with_membind", "physical_cpu_bind", "numa_pci_bind"]:
            if subtest in str(self.name):
                if self.device:
                    if not os.path.isdir('/sys/bus/pci/devices/%s' % self.device):
                        self.cancel("%s not present in device path" % self.device)
                    self.cpu_path = "/sys/devices/system/node/has_cpu"
                    if not os.path.exists(self.cpu_path):
                        self.cancel("No NUMA nodes have CPU")
                    self.numa_dict = cpu.numa_nodes_with_assigned_cpus()
                else:
                    self.cancel("Device input missing, skipping the test")

    def check_numa_nodes(self):
        '''
        :return: True when at least two NUMA nodes with assigned CPU's
                 are available on system
        :return: False if the above condition has not met.
        :rtype: bool
        '''
        if len(cpu.get_numa_node_has_cpus()) < 2:
            self.cancel("Required at least two NUMA nodes with CPU"
                        " assigned for this test case!")
        else:
            return True

    def dd_run(self, cmd):
        '''
        Runs the dd command on given Disk and returns True or False
        '''
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("dd run on %s failed" % self.disk)

    def numa_ping(self, cmd):
        '''
        Ping Test using numactl command to remote Peer
        with -f and count options.
        '''
        output = process.run(cmd, shell=True,
                             ignore_status=True
                             ).stdout.decode("utf-8").split(",")
        if " 0% packet loss" not in output:
            self.cancel("failed due to packet loss")

    def test_basic(self):

        if build.make(self.sourcedir, extra_args='-k -j 1'
                      ' test', ignore_status=True):
            if len(memory.numa_nodes_with_memory()) < 2:
                self.log.warn('Few tests failed due to less NUMA mem-nodes')
            else:
                self.fail('test failed, Please check debug log')

    def test_interleave(self):
        '''
        To check memory interleave on NUMA nodes.
        '''
        if not self.interface and not self.disk:
            self.cancel("Network interface or disk/device input missing")
        if self.interface:
            cmd = "numactl --interleave=all ping -I %s %s -c %s -f"\
                % (self.interface, self.peer, self.ping_count)
            self.numa_ping(cmd)

        if self.disk:
            cmd = "numactl --interleave=all dd if=%s of=%s \
              seek=%s bs=%s count=%s" % (self.input_file,
                                         self.disk,
                                         self.seek,
                                         self.bytes,
                                         self.count)
            self.dd_run(cmd)

    def test_localalloc(self):
        '''
        Test memory allocation on the current node
        '''
        if not self.interface and not self.disk:
            self.cancel("Network interface or disk/device input missing")
        if self.interface:
            cmd = "numactl --localalloc ping -I %s %s -c %s -f"\
                % (self.interface, self.peer, self.ping_count)
            self.numa_ping(cmd)

        if self.disk:
            cmd = "numactl --localalloc  dd if=%s of=%s \
                  seek=%s bs=%s count=%s" % (self.input_file,
                                             self.disk,
                                             self.seek,
                                             self.bytes,
                                             self.count)
            self.dd_run(cmd)

    def test_preferred_node(self):
        '''
        Test Preferably allocate memory on node
        '''
        if not self.interface and not self.disk:
            self.cancel("Network interface or disk/device input missing")

        if self.check_numa_nodes():

            self.node_number = [key for key in self.numa_dict.keys()][1]

            if self.interface:
                cmd = "numactl --preferred=%s  ping -I %s %s -c %s -f" \
                        % (self.node_number,
                           self.interface,
                           self.peer,
                           self.ping_count)
                self.numa_ping(cmd)

            if self.disk:
                cmd = "numactl --preferred=%s dd if=%s of=%s \
                     seek=%s bs=%s count=%s" % (self.node_number,
                                                self.input_file,
                                                self.disk,
                                                self.seek,
                                                self.bytes,
                                                self.count)
                self.dd_run(cmd)

    def test_cpunode_with_membind(self):
        '''
        Test CPU and memory bind
        '''
        if not self.interface and not self.disk:
            self.cancel("Network interface or disk/device input missing")
        if self.check_numa_nodes():
            self.first_cpu_node_number = [key
                                          for key
                                          in self.numa_dict.keys()][0]
            self.second_cpu_node_number = [key
                                           for key
                                           in self.numa_dict.keys()][1]
            self.membind_node_number = [key
                                        for key
                                        in self.numa_dict.keys()][1]
            if self.interface:
                for cpu in [self.first_cpu_node_number,
                            self.second_cpu_node_number]:
                    cmd = "numactl --cpunodebind=%s --membind=%s ping -I %s \
                           %s -c %s -f" % (cpu,
                                           self.membind_node_number,
                                           self.interface,
                                           self.peer,
                                           self.ping_count)
                    self.numa_ping(cmd)

            if self.disk:
                for cpu in [self.first_cpu_node_number,
                            self.second_cpu_node_number]:
                    cmd = "numactl --cpunodebind=%s --membind=%s \
                           dd if=%s of=%s seek=%s bs=%s count=%s" \
                        % (cpu,
                           self.membind_node_number,
                           self.input_file, self.disk,
                           self.seek, self.bytes,
                           self.count)
                    self.dd_run(cmd)

    def test_physical_cpu_bind(self):
        '''
        Test physical  CPU binds
        '''
        if not self.interface and not self.disk:
            self.cancel("Network interface or disk/device input missing")
        if self.check_numa_nodes():
            self.cpu_number = [value
                               for value
                               in self.numa_dict.values()][0][1]
            if self.interface:

                cmd = "numactl --physcpubind=%s ping -I %s %s -c %s -f"\
                    % (self.cpu_number, self.interface, self.peer, self.ping_count)
                self.numa_ping(cmd)

            if self.disk:
                cmd = "numactl --physcpubind=%s dd if=%s of=%s \
                   seek=%s bs=%s count=%s" % (self.cpu_number,
                                              self.input_file,
                                              self.disk,
                                              self.seek,
                                              self.bytes, self.count)
                self.dd_run(cmd)

    def test_numa_pci_bind(self):
        '''
        Test PCI binding to different NUMA nodes
        '''
        if self.check_numa_nodes():
            nodes = [node for node in self.numa_dict.keys()]
            node_path = '/sys/bus/pci/devices/%s/numa_node' % self.device
            pci_node_number = genio.read_file(node_path)
            alter_node = (choice([i
                                  for i
                                  in nodes if i not in [pci_node_number]]))
            genio.write_file(node_path, str(alter_node))
            self.log.info(f"PCI NUMA node changed to {alter_node}")

    def tearDown(self):
        '''
        Cleaning up Host IP address
        '''
        if self.interface:
            if self.networkinterface:
                self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
                try:
                    self.networkinterface.restore_from_backup()
                except Exception:
                    self.networkinterface.remove_cfg_file()
                    self.log.info("backup file not available,"
                                  "could not restore file.")

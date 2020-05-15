#!/usr/bin/python

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
# Author: Harsha Thyagaraja <harshkid@linux.vnet.ibm.com>
# Author: Bismruti Bidhibrata Pattjoshi<bbidhibr@in.ibm.com>
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

import os
import time
import netifaces
from avocado.utils import genio
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost


class VirtualizationDriverBindTest(Test):

    """
    virtualized devices can be bound and unbound to drivers.
    This test verifies that for a given virtualized device.
    :param device: Name of the virtualized device
    """

    def setUp(self):
        """
        Identify the virtualized device.
        """
        smm = SoftwareManager()
        for pkg in ["net-tools"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.virtual_device = self.params.get('virtual_device')
        self.virtual_slot = self.params.get('virtual_slot')
        if "T" in self.virtual_slot:
            self.virtual_slot = self.virtual_slot.split("-T")[0]
        output = process.system_output("lsslot", shell=True)
        for line in output.decode("utf-8").splitlines():
            if self.virtual_slot in line:
                self.device_type = line.split()[-1]
                self.device = line.split()[-2]
        self.count = int(self.params.get('count', default="1"))
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        local = LocalHost()
        if self.device_type in ["l-lan", "vnic"]:
            if self.virtual_device not in interfaces:
                self.cancel("%s interface is not available"
                            % self.virtual_device)
            self.networkinterface = NetworkInterface(self.virtual_device,
                                                     local)
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
            self.networkinterface.bring_up()

    def is_exists_device(self, device):
        '''
        Check whether the scsi_device is present in lsscsi output
        '''
        devices = []
        output = process.system_output("lsscsi").decode('utf-8')
        for line in output.splitlines():
            devices.append(line.split('/')[-1].strip(' '))
        if device in devices:
            return True
        return False

    def test(self):
        """
        Performs driver unbind and bind for the Network virtualized device
        """
        if self.device_type in ["l-lan", "vnic"]:
            if self.networkinterface.ping_check(self.peer_ip,
                                                count=5) is not None:
                self.cancel("Please make sure the network peer is configured ?")
        else:
            if self.is_exists_device(self.virtual_device) is False:
                self.cancel("failed to detect the test disk")
        try:
            for _ in range(self.count):
                for operation in ["unbind", "bind"]:
                    self.log.info("Running %s operation for Network virtualized \
                                   device" % operation)
                    dict = {"vnic": "ibmvnic", "l-lan": "ibmveth",
                            "v-scsi": "ibmvscsi", "vfc-client": "ibmvfc"}
                    if self.device_type in dict.keys():
                        param = dict[self.device_type]
                        genio.write_file(os.path.join
                                         ("/sys/bus/vio/drivers/%s" % param,
                                          operation), "%s" % self.device)
                    time.sleep(5)
                if self.device_type in ["l-lan", "vnic"]:
                    self.log.info("Running a ping test to check if unbind/bind \
                                   affected newtwork connectivity")
                    if self.networkinterface.ping_check(self.peer_ip,
                                                        count=5) is not None:
                        self.fail("Ping test failed. Network virtualized \
                                  unbind/bind has affected Network connectivity")
                else:
                    self.log.info("checking for disk available if unbind/bind \
                                   affected to disk")
                    if self.is_exists_device(self.virtual_device) is False:
                        self.fail("exists device test failed.unbind/bind has \
                                   affected disk")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Driver %s operation failed for Network virtualized \
                       device %s" % (operation, self.interface))

    def tearDown(self):
        """
        remove ip from interface
        """
        if self.device_type in ["l-lan", "vnic"]:
            self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.restore_from_backup()


if __name__ == "__main__":
    main()

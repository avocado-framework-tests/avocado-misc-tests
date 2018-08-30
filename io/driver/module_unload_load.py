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
# Author: Naresh Bannoth<nbannoth@in.ibm.com>
#

import time
from avocado import main
from avocado.utils import process
from avocado.utils import linux_modules
from avocado.utils import pci
from avocado import Test


class ModuleLoadUnload(Test):

    """
    PCI devices can be bound and unbound to drivers.
    This test verifies that for given adapters.

    :param module: Name of the driver module
    :param iteration: Number of time to unload and load the module
    """
    def setUp(self):
        """
        get parameters.
        """
        self.module = self.params.get('module', default=None)
        self.iteration = self.params.get('iteration', default=1)
        self.only_io = self.params.get('only_io', default=None)
        self.fc = self.params.get('fc', default=None)

    def built_in_module(self, module):
        """
        checking whether the given module is built_in module or not
        """
        uname = process.getoutput("uname -r")
        cmd = "cat /lib/modules/%s/modules.builtin" % uname
        for each in str(process.getoutput(cmd)).split('\n'):
            out = process.getoutput(each.split('/')[-1])
            if module == out.split('.'[0]):
                return True
            return False

    def module_load_unload(self, module):
        """
        Unloading and loading the given module
        """
        if self.built_in_module(module) is True:
            self.fail("%s is built_in Module can't be unloaded" % self.module)
        if linux_modules.module_is_loaded(module) is False:
            linux_modules.load_module(module)
            time.sleep(5)
        self.sub_modules = linux_modules.get_submodules(module)
        self.sub_modules.append(module)
        for _ in range(0, self.iteration):
            for mdl in self.sub_modules:
                if self.fc is True:
                    process.system("multipath -F", ignore_status=True)
                    time.sleep(4)
                self.log.info("unloading : %s " % mdl)
                linux_modules.unload_module(mdl)
                time.sleep(3)
            for mdl in reversed(self.sub_modules):
                self.log.info("loading : %s " % mdl)
                linux_modules.load_module(mdl)
                time.sleep(3)

    def test(self):
        """
        Begining the test here
        """
        pci_addrs = []
        if self.only_io is True:
            self.module_load_unload(self.module)
        else:
            pci_addrs = pci.get_pci_addresses()
            for pci1 in pci_addrs:
                driver = pci.get_driver(pci1)
                self.module_load_unload(driver)


if __name__ == "__main__":
    main()

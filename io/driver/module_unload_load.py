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

    def built_in_module(self):
        """
        checking whether the given module is built_in module or not
        """
        uname = process.getoutput("uname -r")
        cmd = "cat /lib/modules/%s/modules.builtin" % uname
        for each in str(process.getoutput(cmd)).split('\n'):
            out = process.getoutput(each.split('/')[-1])
            if self.module == out.split('.'[0]):
                return True
            return False

    def test(self):
        """
        Unloading and loading the given module
        """
        if self.built_in_module() is True:
            self.fail("%s is built_in Module can't be unloaded" % self.module)
        if linux_modules.module_is_loaded(self.module) is False:
            linux_modules.load_module(self.module)
            time.sleep(5)
        self.sub_modules = linux_modules.get_submodules(self.module)
        self.sub_modules.append(self.module)
        for _ in range(0, self.iteration):
            for module in self.sub_modules:
                self.log.info("\n\nunloading : %s " % module)
                process.system("rmmod %s" % module)
                time.sleep(3)
            for module in reversed(self.sub_modules):
                self.log.info("\n\nloading : %s " % module)
                process.system("modprobe %s" % module)
                time.sleep(3)


if __name__ == "__main__":
    main()

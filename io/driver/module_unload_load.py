#!/usr/bin/env python



#import sys
#import os
import time
#from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import linux_modules
#from avocado.utils import pci
#from commands import *
from avocado import Test


class ModuleLoadUnload(Test):

    """
    PCI devices can be bound and unbound to drivers.
    This test verifies that for given adapters.

    :param device: Name of the pci device
    """
    def setUp(self):
        """
        Setup the device.
        """
        self.module = self.params.get('module', default=None)
        self.iteration = self.params.get('iteration', default=1)
        # self.module_type = self.params.get('module_type', default=1)

    def built_in_module(self):
        uname = process.getoutput("uname -r")
        cmd = "cat /lib/modules/%s/modules.builtin" % uname
        for each in str(process.getoutput(cmd)).split('\n'):
            out = process.getoutput(each.split('/')[-1])
            if self.module == out.split('.'[0]): 
                return True
            return False

    def test(self):
        """
        Creates namespace on the device.
        """
        if self.built_in_module() is True:
            self.fail("Given Module %s is a built_in Module. Hence Cannot be unloaded" % self.module)
        if linux_modules.module_is_loaded(self.module) is False:
            linux_modules.load_module(self.module)
            time.sleep(5)
        self.sub_modules = linux_modules.get_submodules(self.module) 
        self.sub_modules.append(self.module)
        for i in range(0, self.iteration):
            # self.sub_modules = linux_modules.get_submodules(self.module)
            # self.sub_modules.append(self.module)
            self.log.info("\n\nunloading the module : %s" % self.sub_modules)
            for module in self.sub_modules:
                self.log.info("unloading : %s " % module)
                # linux_modules.unload_module(module)
                process.system("rmmod %s" % module)
                time.sleep(3)
            for module in reversed(self.sub_modules):
                self.log.info("loading : %s " % module)
                process.system("modprobe %s" % module)
                # linux_modules.load_module(module)
                time.sleep(3)


if __name__ == "__main__":
    main()


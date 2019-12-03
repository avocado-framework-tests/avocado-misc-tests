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
# Copyright: 2019 IBM
# Author: Manvanthara Puttashankar<manvanth@linux.vnet.ibm.com>

"""
This Script verfies driver module parameter.
"""
import time
import netifaces
from avocado import main
from avocado.utils import process
from avocado.utils import linux_modules, genio
from avocado.utils import configure_network
from avocado.utils.configure_network import HostInfo
from avocado import Test


class Moduleparameter(Test):

    """
    This Script verfies driver module parameter.
    """

    def setUp(self):
        """
        get parameters
        """
        self.module = self.params.get('module', default=None)
        interfaces = netifaces.interfaces()
        self.ifaces = self.params.get("interface")
        if self.ifaces not in interfaces:
            self.cancel("%s interface is not available" % self.ifaces)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.peer = self.params.get("peer_ip")
        if not self.peer:
            self.cancel("No peer provided")
        self.param_name = self.params.get('module_param_name', default=None)
        self.param_value = self.params.get('module_param_value', default=None)
        self.sysfs_chk = self.params.get('sysfs_check_required', default=None)
        if self.ifaces[0:2] == 'ib':
            configure_network.set_ip(self.ipaddr, self.netmask, self.ifaces,
                                     interface_type='Infiniband')
        else:
            configure_network.set_ip(self.ipaddr, self.netmask, self.ifaces,
                                     interface_type='Ethernet')
        self.load_unload_sleep_time = 30
        self.error_modules = []
        self.mod_list = []
        self.uname = linux_modules.platform.uname()[2]
        if self.built_in_module(self.module) is True:
            self.cancel("Module %s is Built-in Skipping " %
                        self.module)
        if self.param_check() is False:
            self.cancel("Param %s is not Valid for Module %s" %
                        (self.param_name, self.module))

    def built_in_module(self, module):
        """
        checking whether the given module is built_in module or not
        """
        path = "/lib/modules/%s/modules.builtin" % self.uname
        for each in genio.read_all_lines(path):
            out = process.getoutput(each.split('/')[-1])
            if module == out.split('.'[0]):
                return True
            return False

    def sysfs_value_check(self):
        '''
        Checks if sysfs value matches to test value, Returns True if yes.
        Returns False otherwise.
        '''
        value_check = process.system_output('/usr/bin/cat \
                               /sys/module/%s/parameters/%s' %
                                            (self.module, self.param_name
                                             )).decode('utf-8')
        if self.param_value not in value_check:
            return False
        return True

    def param_check(self):
        '''
        Checks if Param is available for the Module, Returns True if yes.
        Returns False otherwise.
        '''
        value_check = process.system_output('/usr/sbin/modinfo -p %s '
                                            % self.module).decode('utf-8')
        if self.param_name not in value_check:
            return False
        return True

    def module_load_unload(self, mod1):
        """
        Unloading and loading the given module
        """
        if linux_modules.module_is_loaded(mod1) is False:
            linux_modules.load_module(mod1)
            time.sleep(self.load_unload_sleep_time)
        sub_mod = linux_modules.get_submodules(mod1)
        if sub_mod:
            for mod in sub_mod:
                linux_modules.unload_module(mod)
                if linux_modules.module_is_loaded(mod) is True:
                    self.error_modules.append(mod)
                    break
        if linux_modules.unload_module(mod1) is False:
            self.fail("Unloading Module %s failed" % mod1)
        time.sleep(self.load_unload_sleep_time)
        cmd = "%s %s=%s" % (mod1, self.param_name, self.param_value)
        if linux_modules.load_module(cmd) is False:
            self.fail("Param %s = Value %s Failed for Module %s" %
                      (self.param_name, self.param_value, mod1))
        if self.sysfs_chk:
            if self.sysfs_value_check() is False:
                self.fail("Sysfs check failed ")
        if not HostInfo.ping_check(self, self.ifaces, self.peer, '1000',
                                   flood=True):
            self.fail("ping test failed")

    def test(self):
        """
        Test Begins here
        """
        self.module_load_unload(self.module)
        if self.error_modules:
            self.fail("Failed Modules: %s" % self.error_modules)

    def tearDown(self):
        """
        Restore back the default Parameters
        """
        self.log.info("Restoring Default param")
        linux_modules.unload_module(self.module)
        linux_modules.load_module(self.module)
        time.sleep(self.load_unload_sleep_time)
        if linux_modules.module_is_loaded(self.module) is False:
            self.fail("Cannot restore default values for Module : %s"
                      % self.module)


if __name__ == "__main__":
    main()

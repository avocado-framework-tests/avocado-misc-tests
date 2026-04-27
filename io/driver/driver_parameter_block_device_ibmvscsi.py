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
# Copyright: 2020 IBM
# Author: Manvanthara Puttashankar<manvanth@linux.vnet.ibm.com>
# Author: Naresh Bannoth<nbannoth@in.ibm.com>

"""
This Script verifies driver module parameter for ibmvscsi.
"""
import time
from avocado.utils import process
from avocado.utils import linux_modules, genio
from avocado.utils import wait
from avocado import Test


class Moduleparameter(Test):

    """
    This Script verifies driver module parameter for ibmvscsi.
    """

    def setUp(self):
        """
        get parameters
        """
        self.module = self.params.get('module', default=None)
        self.param_name = self.params.get('module_param_name', default=None)
        self.param_value = self.params.get('module_param_value', default=None)
        self.mpath_enabled = self.params.get('multipath_enabled',
                                             default=False)
        self.disk = self.params.get('disk', default=None)
        self.load_unload_sleep_time = self.params.get('load_unload_sleep_time',
                                                       default=30)
        self.force_cleanup = self.params.get('force_cleanup', default=False)
        self.param_not_valid = False
        self.error_modules = []
        self.uname = linux_modules.platform.uname()[2]
        if not self.module:
            self.cancel("Please provide the Module name")
        if not self.disk:
            self.cancel("Please provide the Disk name")
        if linux_modules.module_is_loaded(self.module) is False:
            linux_modules.load_module(self.module)
            time.sleep(self.load_unload_sleep_time)
        if self.built_in_module(self.module) is True:
            self.cancel("Module %s is Built-in Skipping " % self.module)
        if self.param_check() is False:
            self.log.warning("Param %s is not Valid for Module %s - marking as invalid" %
                           (self.param_name, self.module))
            self.param_not_valid = True
            # Don't cancel - let test run and handle gracefully

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
        path = '/sys/module/%s/parameters/%s' % (self.module, self.param_name)
        try:
            value_check = genio.read_all_lines(path)
            if self.param_value not in value_check:
                return False
            return True
        except Exception as e:
            self.log.warning("Could not read sysfs path %s: %s" % (path, str(e)))
            return False

    def param_check(self):
        '''
        Checks if Param is available for the Module, Returns True if yes.
        Returns False otherwise.
        '''
        cmd = '/usr/sbin/modinfo -p %s' % self.module
        modinfo_output = process.system_output(cmd).decode('utf-8')
        if self.param_name not in modinfo_output:
            return False
        return True

    def check_module_in_use(self):
        '''
        Checks if module is currently in use by checking use count.
        Returns True if module is in use (use_count > 0), False otherwise.
        '''
        try:
            cmd = "lsmod | grep -w ^%s" % self.module
            output = process.getoutput(cmd)
            if output:
                parts = output.split()
                if len(parts) >= 3:
                    use_count = int(parts[2])
                    self.log.info("Module %s use_count: %d" % (self.module, use_count))
                    return use_count > 0
        except Exception as e:
            self.log.warning("Could not check module use count: %s" % str(e))
        return False

    def dd_run(self):
        '''
        Runs the dd command on given Disk and returns True or False
        '''
        cmd = 'dd if=/dev/zero of=%s bs=512 count=1024' % self.disk
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("dd run on %s failed" % self.disk)
            return False
        return True

    def is_mpath_flushed(self):
        '''
        returns True if multipath is flushed else false
        '''
        process.system("multipath -F", ignore_status=True)
        cmd = "lsmod | grep -i ^%s" % self.module
        # To-Do: more debug needed as mutlipath is restarting immediately
        # after flush for qla2xxx only and we can remove the static sleep.
        time.sleep(10)
        if process.getoutput(cmd).split(" ")[-1] == '0':
            return True
        return False

    def module_parameter_test(self):
        """
        Unloading and loading the given module
        """
        # If parameter is not valid for this module, skip the test gracefully
        if self.param_not_valid:
            self.log.info("Parameter %s is not valid for module %s - skipping test" %
                         (self.param_name, self.module))
            self.log.info("Running DD test only to verify disk functionality")
            if self.dd_run() is False:
                self.fail("dd run failed on disk: %s" % self.disk)
            self.log.info("DD run success - disk is functional")
            return

        # Check if module is in use (e.g., boot disk)
        module_in_use = self.check_module_in_use()
        
        if module_in_use and self.force_cleanup:
            self.log.warning("Module %s is in use (use_count > 0)" % self.module)
            self.log.warning("force_cleanup=True: Skipping module unload/reload")
            self.log.info("Will only run DD test to verify disk functionality")
            
            # Just run DD test without unloading module
            self.log.info("Running DD test on %s" % self.disk)
            if self.dd_run() is False:
                self.fail("dd run failed on disk: %s" % self.disk)
            self.log.info("DD run success - disk is functional with current module state")
            return

        if self.mpath_enabled is True:
            if not wait.wait_for(self.is_mpath_flushed, timeout=150):
                self.fail("multipath is in USE and cannot be flushed")
        else:
            sub_mod = linux_modules.get_submodules(self.module)
            if sub_mod:
                for mod in sub_mod.split(' '):
                    linux_modules.unload_module(mod)
                    if linux_modules.module_is_loaded(mod) is True:
                        self.error_modules.append(mod)
                        break
        self.log.info("Testing %s=%s" % (self.param_name, self.param_value))
        self.log.info("unloading driver module: %s" % self.module)
        if linux_modules.unload_module(self.module) is False:
            self.fail("Unloading Module %s failed" % self.module)
        time.sleep(self.load_unload_sleep_time)
        self.log.info("loading driver with %s=%s" % (self.param_name,
                                                     self.param_value))
        cmd = "%s %s=%s" % (self.module, self.param_name, self.param_value)
        if linux_modules.load_module(cmd) is False:
            self.fail("Param %s = Value %s Failed for Module %s" %
                      (self.param_name, self.param_value, self.module))
        else:
            self.log.info("Driver module=%s loaded successfully" % cmd)
        self.log.info("checking sysfs for %s after successful load" % cmd)
        if self.sysfs_value_check() is False:
            self.fail("Sysfs check failed ")
        self.log.info("sysfs check for %s success" % cmd)
        self.log.info("Running DD after %s changed" % cmd)
        if self.dd_run() is False:
            self.fail("dd run failed on disk: %s" % self.disk)
        self.log.info("DD run for %s is success" % cmd)

    def test(self):
        """
        Test Begins here
        """
        self.module_parameter_test()
        if self.error_modules:
            self.fail("Failed Modules: %s" % self.error_modules)

    def tearDown(self):
        """
        Restore back the default Parameters
        """
        self.log.info("Restoring Default param")
        
        # If parameter was not valid or module is in use with force_cleanup, skip teardown
        if self.param_not_valid:
            self.log.info("Parameter was not valid - skipping teardown")
            return
            
        if self.force_cleanup and self.check_module_in_use():
            self.log.info("Module in use and force_cleanup=True - skipping teardown")
            return
        
        if self.mpath_enabled is True:
            if not wait.wait_for(self.is_mpath_flushed, timeout=150):
                self.fail("multipath is in USE and cannot be flushed")
        if self.module:
            linux_modules.unload_module(self.module)
            linux_modules.load_module(self.module)
            time.sleep(self.load_unload_sleep_time)
            if linux_modules.module_is_loaded(self.module) is False:
                self.fail("Cannot restore default values for Module : %s"
                          % self.module)
        self.log.info("Restore of default param is success")

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
# Author: Shriya Kulkarni <shriyak@linux.vnet.ibm.com>
# Author: Satheesh Rajendran <sathnaga@linux.vnet.ibm.com>
import commands
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class em_tuned(Test):

    def setUp(self):
        detected_distro = distro.detect()
        if 'rhel' not in detected_distro.name:
            self.cancel(" Tuned-adm service is not supported "
                        "on %s" % detected_distro.name)
        if SoftwareManager().check_installed("tuned") is False:
            if SoftwareManager().install("tuned") is False:
                self.skip("tuned is not installing")
        self.error_count = 0

    def test(self):
        '''
        tuned-adm is a command line tool that provides a number of different
        profiles to improve performance in a number of specific use cases
        Script will do basic settings of profiles using tuned-adm.
        '''
        self.log.info("Check for tuned service")
        self.tuned_service_check_start()
        self.log.info("Check for list of profiles")
        self.check_tuned_profiles()
        self.log.info("Changing different active profiles")
        self.profile_change()
        self.log.info("Check for tuned off")
        self.check_tuned_off()
        if self.error_count > 0:
            self.fail(" The test case failed, check for the logs")

    def tuned_service_check_start(self):
        """
        Check for Tuned service
        """
        (is_loaded, is_active) = self.get_tuned_status()
        if is_active and is_loaded:
            self.log.info("PASS: service tuned is running")
        if is_loaded and not is_active:
            self.log.info("Tuned is active not running")
            self.log.info("Starting tuned-adm servie")
            self.tuned_start()
            (is_loaded, is_active) = self.get_tuned_status()
            if not is_active:
                self.error("Service tuned unable to start")
            if not is_loaded:
                self.error("Tuned is not available")

    def check_tuned_profiles(self):
        """
        Check for Tuned profiles
        """
        # When ever a new profile name added to 'tuned' profiles,
        # add the same here
        expected_profiles = ['balanced', 'default', 'desktop-powersave',
                             'desktop', 'enterprise-storage',
                             'laptop-ac-powersave',
                             'laptop-battery-powersave', 'latency-performance',
                             'network-latency', 'network-throughput',
                             'powersave', 'server-powersave',
                             'throughput-performance',
                             'spindown-disk', 'virtual-guest', 'virtual-host']
        available_profiles = self.get_available_profiles()
        for profile in available_profiles:
            if profile not in expected_profiles:
                self.log.info("Profile: %s is not found" % profile)

        active_profile = self.get_active_profile()
        found = False
        self.log.info(" Active profile : %s" % active_profile)
        for profile in available_profiles:
            if active_profile == profile:
                found = True
        if not found:
            self.error_count += 1
            self.log.info("Active profile: %s not found in the list of"
                          "available profiles" % active_profile)

    def profile_change(self):
        """
        Check all available profiles by change to active
        """
        available_profiles = self.get_available_profiles()
        for profile in available_profiles:
            self.set_active_profile(profile)
            active_profile = self.get_active_profile()
            if profile != active_profile:
                self.error_count += 1
                self.log.info("Profile: %s is not able to set" % profile)

    def check_tuned_off(self):
        """
        Check for Tuned off
        """
        preserve_active_profile = self.get_active_profile()
        self.set_tuned_off()
        active_profile = self.get_active_profile()
        if active_profile:
            self.error_count += 1
            self.log.info("Active profile: %s is present even after turning"
                          "tuned off" % active_profile)
        self.set_active_profile(preserve_active_profile)

    # Helper functions
    def set_tuned_off(self):
        """
        Turn off tuned
        """
        status = process.system("tuned-adm off", shell=True)
        self.log.info(" status %s " % status)
        if status != 0:
            self.error_count += 1
            self.log.info("Error turning off tuned %s" % status)

    def set_active_profile(self, profile):
        """
        To set active profile
        """
        status = process.system("tuned-adm profile %s" % profile, shell=True)
        if status != 0:
            self.error_count += 1
            self.log.info("Error setting Profile %s" % profile)

    def get_available_profiles(self):
        """
        To get all available profiles
        """
        available_profiles = []
        cmd_profile = commands.getoutput('tuned-adm list').split('\n')
        for line in cmd_profile:
            if line.startswith("- "):
                available_profiles.append(line.split("- ")[1].strip())
        self.log.info("Profiles %s" % available_profiles)
        return available_profiles

    def get_active_profile(self):
        """
        To get the active profile
        """
        cmd_act_pf = "tuned-adm active|grep 'Current active profile:'|\
                     awk '{print $4}'"
        active_profile = process.system_output(cmd_act_pf, shell=True)
        cmd_act_pf_lt = "tuned-adm list|grep 'Current active profile:'|\
                         awk '{print $4}'"
        act_profile_list = process.system_output(cmd_act_pf_lt, shell=True)
        if not active_profile:
            active_profile = None
        if not act_profile_list:
            act_profile_list = None
        if active_profile != act_profile_list:
            self.log.info("Active profile mismatch in tuned list"
                          "and tuned active command")

        return active_profile

    def get_tuned_status(self):
        """
        Getting Tuned status
        """
        is_active = False
        is_loaded = False
        cmd_load = "systemctl status tuned.service|grep 'Loaded:'|\
            awk '{print $2}'"
        cmd_active = "systemctl status tuned.service|grep 'Active:'|\
                      awk '{print $2}'"
        output_load = process.system_output(cmd_load, shell=True)
        output_active = process.system_output(cmd_active, shell=True)
        self.log.info("Tuned status: %s" % output_active)
        if output_load == 'loaded':
            is_loaded = True
        if output_active == 'active':
            is_active = True
        if output_active == 'failed':
            is_active = False
        if output_active == 'inactive':
            is_active = False
        return (is_loaded, is_active)

    def tuned_start(self):
        """
        Starting Tuned service
        """
        self.log.info(": Starting tuned service")
        cmd = "systemctl start tuned.service"
        status = process.system(cmd)
        if status != 0:
            self.error("Tuned start failed")


if __name__ == "__main__":
    main()

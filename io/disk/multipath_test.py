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
# Copyright: 2016 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
Multipath Test.
Needs to be run as root.
"""

import os
import shutil
import time
from pprint import pprint
from avocado import Test
from avocado import main
from avocado.utils import distro, process
from avocado.utils import multipath
from avocado.utils import service
from avocado.utils import wait
from avocado.utils.software_manager import SoftwareManager


class MultipathTest(Test):
    """
    Multipath Test
    """

    def setUp(self):
        """
        Set up.
        """
        self.policy = self.params.get('policy', default='service-time')
        self.policies = ["service-time", "round-robin", "queue-length"]
        # We will remove and add the policy back, so that this becomes
        # the last member of the list. This is done so that in the
        # policy change test later, this policy is set in the last
        # iteration.
        self.policies.remove(self.policy)
        self.policies.append(self.policy)
        # Install needed packages
        dist = distro.detect()
        pkg_name = ""
        svc_name = ""
        if dist.name == 'Ubuntu':
            pkg_name += "multipath-tools"
            svc_name = "multipath-tools"
        elif dist.name == 'SuSE':
            pkg_name += "multipath-tools"
            svc_name = "multipathd"
        else:
            pkg_name += "device-mapper-multipath"
            svc_name = "multipathd"

        smm = SoftwareManager()
        if not smm.check_installed(pkg_name) and not smm.install(pkg_name):
            self.cancel("Can not install %s" % pkg_name)

        # Check if given multipath devices are present in system
        self.wwids = self.params.get('wwids', default='').split(',')
        system_wwids = multipath.get_multipath_wwids()
        wwids_to_remove = []
        for wwid in self.wwids:
            if wwid not in system_wwids:
                self.log.info("%s not present in the system", wwid)
                wwids_to_remove.append(wwid)
        for wwid in wwids_to_remove:
            self.wwids.remove(wwid)
        if self.wwids == []:
            self.cancel("No Multipath Devices Given")

        # Create service object
        self.mpath_svc = service.SpecificServiceManager(svc_name)
        self.mpath_svc.restart()
        wait.wait_for(self.mpath_svc.status, timeout=10)

        # Take a backup of current config file
        self.mpath_file = "/etc/multipath.conf"
        if os.path.isfile(self.mpath_file):
            shutil.copyfile(self.mpath_file, "%s.bkp" % self.mpath_file)

        self.mpath_list = []

        # Find all details of multipath devices
        for wwid in self.wwids:
            if wwid not in process.system_output('multipath -ll',
                                                 ignore_status=True,
                                                 shell=True).decode("utf-8"):
                continue
            self.mpath_dic = {}
            self.mpath_dic["wwid"] = wwid
            self.mpath_dic["name"] = multipath.get_mpath_name(wwid)
            self.mpath_dic["paths"] = multipath.get_paths(wwid)
            self.mpath_dic["policy"] = multipath.get_policy(wwid)
            self.mpath_dic["size"] = multipath.get_size(wwid)
            self.mpath_list.append(self.mpath_dic)
        pprint(self.mpath_list)

    def test(self):
        """
        Tests Multipath.
        """
        msg = ""
        multipath.form_conf_mpath_file()
        plcy = "path_selector \"%s 0\"" % self.policy
        multipath.form_conf_mpath_file(defaults_extra=plcy)
        for path_dic in self.mpath_list:
            self.log.debug("operating on paths", path_dic["paths"])
            # Path Selector policy
            self.log.info("changing Selector policy")
            for policy in self.policies:
                cmd = "path_selector \"%s 0\"" % policy
                multipath.form_conf_mpath_file(defaults_extra=cmd)
                if multipath.get_policy(path_dic["wwid"]) != policy:
                    msg += "%s for %s fails\n" % (policy, path_dic["wwid"])

            # mutipath -f mpathX
            if not multipath.flush_path(path_dic["name"]):
                msg += "Flush of %s fails\n" % path_dic["name"]
            self.mpath_svc.restart()
            wait.wait_for(self.mpath_svc.status, timeout=10)

            # Blacklisting wwid
            self.log.info("Black listing WWIDs")
            cmd = "wwid %s" % path_dic["wwid"]
            multipath.form_conf_mpath_file(blacklist=cmd, defaults_extra=plcy)
            if multipath.device_exists(path_dic["wwid"]):
                msg += "Blacklist of %s fails\n" % path_dic["wwid"]
            else:
                multipath.form_conf_mpath_file(defaults_extra=plcy)
                if not multipath.device_exists(path_dic["wwid"]):
                    msg += "Recovery of %s fails\n" % path_dic["wwid"]

            # Blacklisting sdX
            self.log.info("Black listing individual paths")
            for disk in path_dic["paths"]:
                cmd = "devnode %s" % disk
                multipath.form_conf_mpath_file(blacklist=cmd,
                                               defaults_extra=plcy)
                if disk in multipath.get_paths(path_dic["wwid"]):
                    msg += "Blacklist of %s fails\n" % disk
            multipath.form_conf_mpath_file(defaults_extra=plcy)

            # Failing and reinstating individual paths eg: sdX
            self.log.info(" Failing and reinstating the individual paths")
            for path in path_dic["paths"]:
                if multipath.fail_path(path) is False:
                    msg += "test failed while failing %s\n" % path
                elif multipath.reinstate_path(path) is False:
                    msg += "test failed while reinstating %s\n" % path
            self.mpath_svc.restart()
            wait.wait_for(self.mpath_svc.status, timeout=10)

            # Failing n-1 paths for short time and reinstating back
            self.log.info("Failing and reinstating the n-1 paths")
            for path in path_dic['paths'][:-1]:
                if multipath.fail_path(path) is False:
                    msg += "%s did not failed in n-1 path fail\n" % path

            time.sleep(180)
            for path in path_dic['paths'][:-1]:
                if multipath.reinstate_path(path) is False:
                    msg += "%s failed to recover in n-1 paths fails\n" % path
            self.mpath_svc.restart()
            wait.wait_for(self.mpath_svc.status, timeout=10)

            # Failing all paths for short time and reinstating back
            self.log.info("Failing and reinstating the All paths")
            for path in path_dic['paths']:
                if multipath.fail_path(path) is False:
                    msg += "%s did not failed in all paths fail\n" % path

            time.sleep(180)
            for path in path_dic['paths']:
                if multipath.reinstate_path(path) is False:
                    msg += "%s did not recovered  in all path fail\n" % path
            self.mpath_svc.restart()
            wait.wait_for(self.mpath_svc.status, timeout=10)

        # Print errors
        if msg:
            self.fail("Some tests failed. Find details below:\n%s" % msg)

    def tearDown(self):
        """
        Restore config file, if existed, and restart services
        """
        if os.path.isfile(self.mpath_file):
            shutil.copyfile("%s.bkp" % self.mpath_file, self.mpath_file)
        self.mpath_svc.restart()

        # Need to wait for some time to make sure multipaths are loaded.
        wait.wait_for(self.mpath_svc.status, timeout=10)


if __name__ == "__main__":
    main()

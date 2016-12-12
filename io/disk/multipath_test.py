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
"""

import os
from pprint import pprint
from avocado import Test
from avocado import main
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import multipath
from avocado.utils.software_manager import SoftwareManager


class MultipathTest(Test):
    """
    Multipath Test functions.
    """
    def setUp(self):
        """
        Set up.
        """
        # Check if multipath devices are present in sytem
        self.wwids = multipath.get_multipath_wwids()
        if self.wwids == ['']:
            self.skip("No Multipath Devices")

        # Install needed packages
        dist = distro.detect()
        pkg_name = ""
        if dist.name == 'Ubuntu':
            pkg_name += "multipath-tools"
        else:
            pkg_name += "device-mapper-multipath"
        smm = SoftwareManager()
        if not smm.check_installed(pkg_name) and not smm.install(pkg_name):
            self.skip("Can not install %s" % pkg_name)

        # Take a backup of current config file
        self.mpath_file = "/etc/multipath.conf"
        if os.path.isfile(self.mpath_file):
            cmd = "cp %s %s.bkp" % (self.mpath_file, self.mpath_file)
            process.system(cmd)

        self.mpath_list = []

        # Find all details of multipath devices
        for wwid in self.wwids:
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
        Tests Flushing, Blacklisting, patch_checker policy.
        """
        msg = ""

        multipath.form_conf_mpath_file()
        for path_dic in self.mpath_list:
            # mutipath -f mpathX
            if not multipath.flush_path(path_dic["name"]):
                msg += "Flush of %s fails\n" % path_dic["name"]
            multipath.multipath_service(operation='restart')

            # Path Selector policy
            for policy in ["service-time", "round-robin", "queue-length"]:
                cmd = "path_selector \"%s 0\"" % policy
                multipath.form_conf_mpath_file(defaults_extra=cmd)
                if multipath.get_policy(path_dic["wwid"]) != policy:
                    msg += "%s for %s fails\n" % (policy, path_dic["wwid"])

            # Blacklist wwid
            cmd = "wwid %s" % path_dic["wwid"]
            multipath.form_conf_mpath_file(blacklist=cmd)
            if multipath.path_exists(path_dic["wwid"]):
                msg += "Blacklist of %s fails\n" % path_dic["wwid"]
            else:
                multipath.form_conf_mpath_file()
                if not multipath.path_exists(path_dic["wwid"]):
                    msg += "Recovery of %s fails\n" % path_dic["wwid"]

            # Blacklist sdX
            for disk in path_dic["paths"]:
                cmd = "devnode %s" % disk
                multipath.form_conf_mpath_file(blacklist=cmd)
                if disk in multipath.get_paths(path_dic["wwid"]):
                    msg += "Blacklist of %s fails\n" % disk

        # Print errors
        if msg:
            msg = "Following Tests Failed\n" + msg
            self.log.debug(msg)
            self.fail("Some tests failed")

    def tearDown(self):
        """
        Restore config file, if existed, and restart services
        """
        if os.path.isfile(self.mpath_file):
            cmd = "cp %s.bkp %s" % (self.mpath_file, self.mpath_file)
            process.run(cmd)
        multipath.multipath_service(operation='restart')

if __name__ == "__main__":
    main()

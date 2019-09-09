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
# Author: Basheer Khadarsabgari <basheer@linux.vnet.ibm.com>

import os
import re
import shutil
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Supportconfig(Test):
    """
    The supportconfig script gathers system troubleshooting information on
    SUSE Linux Enterprise Server systems.It captures the current system
    environment and generates a tar-archive.

    The script file collects complementary information to the dbginfo.sh
    script. The supportconfig script is part of the Supportutils package.
    """

    def setUp(self):
        """
        Install all the dependency packages required for Test.
        """
        sm = SoftwareManager()

        if "SuSE" not in distro.detect().name:
            self.cancel("supportconfig is supported on the SuSE Distro only.")

        pkgs = ["supportutils", "psmisc"]

        for pkg in pkgs:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.cancel("Package %s is missing/could not be installed" % pkg)

    def test_supportconfig_options(self):
        """
        Test the supportconfig options:
        Use the minimal option (-m):supportconfig -m
        Limiting the Information to a Specific Topic: supportconfig -i LVM
        List of feature keywords: supportconfig -F
        Collecting already Rotated Log Files: supportconfig -l
        """
        # verify the normal functionality of the supportconfig
        ret = process.run("supportconfig",
                          sudo=True,
                          ignore_status=True)
        logfile = re.search(r"Log file tar ball: (\S+)\n", ret.stdout.decode("utf-8")).group(1)
        if not os.path.exists(logfile) or ret.exit_status:
            self.fail("supportconfig failed to create log file")

        options_to_verify = self.params.get('supportconfig_opt', default="m")
        feature = self.params.get('feature', default="AUTOFS")
        for option in options_to_verify:
            if option == "i":
                self.log.info("Limiting the Information to a Specific feature")
                ret = process.run("supportconfig -%s %s" % (option, feature),
                                  sudo=True,
                                  ignore_status=True)
                if not re.search(r"%s...\s*Done" % feature, ret.stdout.decode("utf-8")) \
                   or ret.exit_status:
                    self.fail(
                        "Failed to verify the %s feature using supportconfig" %
                        feature)
            elif option == "R":
                self.log.info(
                    "Changing default directory path for supportconfig" +
                    " output files")
                ret = process.run("supportconfig -%s %s" %
                                  (option, self.workdir),
                                  sudo=True,
                                  ignore_status=True)
                if self.workdir not in ret.stdout.decode("utf-8") or ret.exit_status:
                    self.fail(
                        "Failed to change the supportconfig output" +
                        " files directory")
            else:
                self.log.info("verifying %s option of supportconfig" % option)
                ret = process.system("supportconfig -%s" % option,
                                     sudo=True,
                                     ignore_status=True)
                if ret:
                    self.fail(
                        "supportconfig %s option failed with %s exit option" %
                        (option, ret))

    def test_enable_disable_plugins(self):
        """
        1.create the /usr/lib/supportconfig/plugins
        2.copy your script file there
        3.output will be in the plugin-plugin_name.txt file
        """
        plugin_dir = "/usr/lib/supportconfig/plugins"
        plugin_dir_exists = 1
        if not os.path.exists(plugin_dir):
            plugin_dir_exists = 0
            os.mkdir(plugin_dir)
        # copy the plugin file
        plugin_name = '/usr/bin/pstree'
        shutil.copy(plugin_name, plugin_dir)
        ret = process.run("supportconfig",
                          sudo=True,
                          ignore_status=True)
        logfile = re.search(r"Log file tar ball: (\S+)\n", ret.stdout.decode("utf-8")).group(1)
        res = process.system("tar -tvf %s | grep 'plugin-pstree.txt'"
                             % logfile,
                             ignore_status=True,
                             shell=True)
        if ret.exit_status or res:
            self.fail("support failed to execute plugin")
        # disable a plugin
        ret = process.run("supportconfig -p",
                          sudo=True,
                          ignore_status=True)
        logfile = re.search(r"Log file tar ball: (\S+)\n", ret.stdout.decode("utf-8")).group(1)
        res = process.system("tar -tvf %s | grep 'plugin-pstree.txt'"
                             % logfile,
                             ignore_status=True,
                             shell=True)
        if ret.exit_status or not res:
            self.fail("support failed to disable plugin")

        # cleanup the plugin dir
        if not plugin_dir_exists:
            process.system("rm -rf %s" % plugin_dir)


if __name__ == "__main__":
    main()

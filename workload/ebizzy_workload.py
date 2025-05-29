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
# Copyright: 2024 IBM
# Author: Krishan Gopal Saraswat <krishang@linux.ibm.com>


import os

from avocado import Test
from avocado.utils import distro, process, archive, build
from avocado.utils.software_manager.manager import SoftwareManager


class Ebizzyworkload(Test):

    """
    ebizzy workload
    """

    def setUp(self):
        '''
        Build ebizzy
        Source:
        https://sourceforge.net/projects/ebizzy/files/ebizzy/0.3
        /ebizzy-0.3.tar.gz
        '''
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not powerpc")
        sm = SoftwareManager()
        deps = ['tar', 'make']
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        url = 'https://sourceforge.net/projects/ebizzy/files/ebizzy/0.3/ebizzy-0.3.tar.gz'
        tarball = self.fetch_asset(self.params.get("ebizy_url", default=url))
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)
        os.chdir(self.sourcedir)
        process.run("./configure")
        build.make(self.sourcedir, extra_args='LDFLAGS=-static')
        # Get the arguments for ebizzy workload from YAML file
        self.args = self.params.get('ebizzy_args', default='-S 20')

    def test_start_ebizzy_workload(self):
        # Run ebizzy workload for time duration taken from YAML file
        process.run("./ebizzy {0} &> /tmp/ebizzy_workload.log &".format(self.args), ignore_status=True, sudo=True, shell=True)
        self.log.info("Workload started--!!")

    def test_stop_ebizzy_workload(self):
        ps = process.system_output("ps -e", ignore_status=True, shell=True).decode().splitlines()
        pid = 0
        flag = 0
        for w_load in ps:
            if "ebizzy" in w_load:
                pid = int(w_load.strip().split(" ")[0])
                flag = 1
                break
        if pid:
            os.kill(pid, 9)
        if flag == 0:
            self.cancel("Ebizzy workload is not running or already execution finished")

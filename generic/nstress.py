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
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import distro, archive, process


class NStress(Test):

    is_fail = 0

    def run_cmd(self, cmd):
        cmd_result = process.run(cmd, ignore_status=True, sudo=True,
                                 shell=True)
        if cmd_result.exit_status != 0:
            self.log.info("%s test failed" % cmd)
            self.is_fail += 1
        return

    def setUp(self):
        dist = distro.detect()
        if dist.name == 'Ubuntu':
            tar_ball = self.params.get('tar_ball_ubuntu', default='nstress_Ubuntu1410_ppc64_Nov_2015.tar')
        elif dist.name == 'rhel':
            tar_ball = self.params.get('tar_ball_rhel', default='nstress_RHEL71_LE_ppc64_Nov_2015.tar')
        elif dist.name == 'SuSE':
            tar_ball = self.params.get('tar_ball_sles', default='nstress_SLES12_ppc64_Nov_2015.tar')
        url = os.path.join('http://public.dhe.ibm.com/systems/power/community/wikifiles/PerfTools/',
                           tar_ball)
        tarball = self.fetch_asset(url, expire='10d')
        archive.extract(tarball, self.srcdir)
        self.duration = self.params.get('duration', default=300)

    def test(self):
        os.chdir(self.srcdir)
        self.run_cmd("./nmem -m 250 -s %s" % self.duration)
        self.run_cmd("./nmem64 -m 2047 -s %s" % self.duration)
        if self.is_fail >= 1:
            self.fail("nstress test failed")
        ''' ncpu retrun code is 1 even after successful completion'''
        ncpu_result = process.run("./ncpu -p 255 -s %s" % self.duration, ignore_status=True, sudo=True)
        if ncpu_result.exit_status != 1:
            self.log.info("ncpu test failed")


if __name__ == "__main__":
    main()

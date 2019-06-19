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

    def setUp(self):
        if "ppc" not in distro.detect().arch:
            self.cancel("supported only on Power platform")
        dist = distro.detect()
        if dist.name == 'Ubuntu':
            tar_ball = self.params.get(
                'tar_ball_ubuntu',
                default='nstress_Ubuntu1410_ppc64_Nov_2015.tar')
        elif dist.name == 'rhel':
            tar_ball = self.params.get(
                'tar_ball_rhel',
                default='nstress_RHEL71_LE_ppc64_Nov_2015.tar')
        elif dist.name == 'SuSE':
            tar_ball = self.params.get(
                'tar_ball_sles',
                default='nstress_SLES12_ppc64_Nov_2015.tar')
        url = os.path.join('http://public.dhe.ibm.com/systems/power/'
                           'community/wikifiles/PerfTools/',
                           tar_ball)
        tarball = self.fetch_asset(url, expire='10d')
        archive.extract(tarball, self.workdir)
        self.duration = self.params.get('duration', default=300)
        self.testcase = self.params.get('testcase', default='nmem')
        self.memchunk = self.params.get('memchunk', default="250")
        self.procs = self.params.get('procs', default="250")

    def test(self):
        os.chdir(self.workdir)
        if process.system('./%s -m %s -s %s' % (self.testcase,
                                                self.memchunk, self.duration),
                          ignore_status=True, sudo=True, shell=True):
            self.fail("%s test failed " % self.test)

        ''' ncpu retrun code is 1 even after successful completion'''

        if process.system("./ncpu -p %s -s %s" %
                          (self.procs, self.duration),
                          ignore_status=True, sudo=True) != 1:
            self.fail("ncpu test failed")


if __name__ == "__main__":
    main()

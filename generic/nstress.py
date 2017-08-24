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
        dist = distro.detect()
        if dist.name == 'Ubuntu':
            tar_ball = self.params.get('tar_ball_ubuntu', default='nstress_Ubuntu1410_ppc64_Nov_2015.tar')
        elif dist.name == 'rhel':
            tar_ball = self.params.get('tar_ball_rhel', default='nstress_RHEL71_LE_ppc64_Nov_2015.tar')
        elif dist.name == 'SuSE':
            tar_ball = self.params.get('tar_ball_sles', default='nstress_SLES12_ppc64_Nov_2015.tar')
        url = os.path.join('http://public.dhe.ibm.com/systems/power/community/wikifiles/PerfTools/', tar_ball)
        tarball = self.fetch_asset(url)
        archive.extract(tarball, self.srcdir)
        os.chdir(self.srcdir)

    def test(self):
        os.chdir(self.srcdir)
        duration = self.params.get('duration', default=300)
        process.run("./nmem -m 250 -s %s" % duration, ignore_status=True, sudo=True)
        process.run("./nmem64 -m 2047 -s %s" % duration, ignore_status=True, sudo=True)
        process.run("./ncpu -p 255 -s %s" % duration, ignore_status=True, sudo=True)


if __name__ == "__main__":
    main()

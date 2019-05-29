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
# Copyright: 2016 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import archive
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro
from avocado.core import data_dir


class Atlas(Test):
    '''
    The Test fetches the tar of the ATLAS and LAPACK libraries and
    performs the sanity checks on the built libraries.
    '''

    def setUp(self):
        sm = SoftwareManager()
        detected_distro = distro.detect()
        self.tmpdir = data_dir.get_tmp_dir()
        # Check for basic utilities
        for package in ['gcc', 'make', 'gfortran']:
            if detected_distro.name == "SuSE" and package == "gfortran":
                package = 'gcc-fortran'
            # FIXME: "redhat" as the distro name for RHEL is deprecated
            # on Avocado versions >= 50.0.  This is a temporary compatibility
            # enabler for older runners, but should be removed soon
            if detected_distro.name in ["rhel", "redhat"] and package == "gfortran":
                package = 'gcc-gfortran'
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        atlas_url = 'https://sourceforge.net/projects/'\
                    'math-atlas/files/Stable/3.10.3/atlas3.10.3.tar.bz2'
        lapack_url = 'http://www.netlib.org/lapack/lapack-3.6.1.tgz'
        atlas_url = self.params.get('atlas_url', default=atlas_url)
        lapack_url = self.params.get('lapack_url', default=lapack_url)
        atlas_tarball = self.fetch_asset(atlas_url, expire='7d')
        archive.extract(atlas_tarball, self.workdir)
        self.atlas_dir = os.path.join(self.workdir, 'ATLAS')
        self.atlas_build_dir = os.path.join(self.atlas_dir, 'atlas_build_dir')
        os.makedirs(self.atlas_build_dir)
        lapack_tarball = self.fetch_asset(lapack_url, expire='7d')
        os.chdir(self.atlas_build_dir)
        config_args = '--shared -b 64 '\
                      '--with-netlib-lapack-tarfile=%s '\
                      '--cripple-atlas-performance' % lapack_tarball
        config_args = self.params.get('config_args', default=config_args)
        process.system('../configure %s' % config_args)
        # Tune and compile library
        build.make(self.atlas_build_dir)

    def test(self):
        '''
        Various test options are available which can be
        explored in INSTALL.txt file and used. Here, the test performs
        sanity tests using make check option if no extra user option is
        specified.
        '''
        make_option = self.params.get('make_option', default='check')
        ret = build.run_make(self.atlas_build_dir, extra_args=make_option,
                             process_kwargs={'ignore_status': True})
        if ret.exit_status:
            self.fail("Make check Has been Failed !!"
                      "Please, refer the log file")


if __name__ == "__main__":
    main()

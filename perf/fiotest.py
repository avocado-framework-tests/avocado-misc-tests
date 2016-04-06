#!/usr/bin/env python

import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process


class FioTest(Test):

    """
    fio is an I/O tool meant to be used both for benchmark and
    stress/hardware verification.

    :see: http://freecode.com/projects/fio

    :param fio_tarbal: name of the tarbal of fio suite located in deps path
    :param fio_job: config defining set of executed tests located in deps path
    """

    def setUp(self):
        """
        Build 'fio'.
        """
        tarball = self.fetch_asset('http://brick.kernel.dk/snaps/fio-2.1.10.tar.gz')
        archive.extract(tarball, self.srcdir)
        fio_version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, fio_version)
        build.make(self.srcdir)

    def test(self):
        """
        Execute 'fio' with appropriate parameters.
        """
        fio_job = self.params.get('fio_job', default='fio-mixed.job')
        cmd = '%s/fio %s' % (self.srcdir,
                             os.path.join(self.datadir, fio_job))
        process.system(cmd)


if __name__ == "__main__":
    main()

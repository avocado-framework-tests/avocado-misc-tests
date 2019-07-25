#!/usr/bin/env python
#
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
# Copyright: 2018 IBM
# Author: Harish <harish@linux.vnet.ibm.com>
#

import os
from avocado import Test
from avocado import main
from avocado.utils import process, memory, disk, genio


class SumCheck(Test):
    """
    Test allocates file chuck of RAM size and checks for md5sum of the file
    repetitively so that memory integrity persists

    :avocado: tags=memory
    """

    def setUp(self):
        self.iter = int(self.params.get('iterations', default='5'))
        self.memsize = int(self.params.get(
            'mem_size', default=memory.meminfo.MemFree.k * 0.9))
        self.ddfile = os.path.join(self.workdir, 'ddfile')
        if (disk.freespace(self.workdir) // 1024) < self.memsize:
            self.cancel('%sM is needed for the test to be run' %
                        (self.memsize // 1024))

    def test(self):
        mdsum = []

        self.log.info("Creating chunk with dd")
        try:
            process.system('dd if=/dev/urandom of=%s bs=%s count=1024' %
                           (self.ddfile, self.memsize))
        except process.CmdError as details:
            self.fail("Chunk creation failed due to %s" % details)
        for i in range(self.iter):
            mdsum.append(process.system_output('md5sum %s' % self.ddfile))
            self.log.info("MD5 : %s", mdsum[i])

        if len(set(mdsum)) > 1:
            self.fail('Md5sum for created file differs')

    def tearDown(self):
        genio.write_file("/proc/sys/vm/drop_caches", "3")


if __name__ == "__main__":
    main()

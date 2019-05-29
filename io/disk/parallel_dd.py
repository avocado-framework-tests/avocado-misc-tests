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
# Copyright: 2016 IBM.
# Author: Pooja B Surya <pooja@linux.vnet.ibm.com>
# Author: Rajashree Rajendran<rajashr7@linux.vnet.ibm.com>

# Based on code by Martin J. Bligh <mbligh@google.com>
#   Copyright: 2007 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/parallel_dd

"""
Measures the performance of writing and reading multiple streams of files onto
the files system.
"""

import os
import time
import sys
import json
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import partition as partition_lib


class ParallelDd(Test):
    """
    Avocado test for parallel_dd.
    """

    def setUp(self):
        """
        :params disk: The disk on which the operations are to be performed.
        :params fsys: A L{utils.partition} instance.
        :params megabytes: The amount of data to read/write.
        :params blocks: The blocksize in bytes to use.
        :params streams: Number of streams. Defaults to 2.
        :params blocks_per_file: The number of blocks per file.
        :params fs: The file system type of the disk.
        :params seq_read: Perform sequential operations. Defaults to true.
        :params dd_woptions: dd write options.
        :params dd_roptions: dd read options.
        :params fs_dd_woptions: dd write in streams.
        :params fs_dd_roptions: dd read in streams.
        """

        self.disk = self.params.get('disk')
        if not self.disk:
            self.cancel('Test requires disk parameter,Please check README')
        self.fsys = partition_lib.Partition(self.disk, mountpoint=self.workdir)
        self.megabytes = self.params.get('megabytes', default=100)
        self.blocks = self.params.get('blocks', default=None)
        self.streams = self.params.get('streams', default=2)
        self.blocks_per_file = self.params.get(
            'blocks_per_file', default=None)
        self.fstype = self.params.get('fs', default=None)
        self.seq_read = self.params.get('seq_read', default=True)
        self.dd_woptions = self.params.get('dd_woptions', default='')
        self.dd_roptions = self.params.get('dd_roptions', default='')
        self.fs_dd_woptions = self.params.get('fs_dd_woptions', default='')
        self.fs_dd_roptions = self.params.get('fs_dd_roptions', default='')
        if not self.blocks:
            self.blocks = self.megabytes * 256

        if not self.blocks_per_file:
            self.blocks_per_file = self.blocks / self.streams

        root_fs_device = process.system_output("df | egrep /$ | awk "
                                               "'{print $1}'", shell=True)
        self.root_fstype = self._device_to_fstype('/etc/fstab', root_fs_device)

        if not self.fstype and self.root_fstype:
            self.fstype = self.root_fstype

        self.old_fstype = self._device_to_fstype('/etc/mtab')
        if not self.old_fstype:
            self.old_fstpye = self._device_to_fstype('/etc/fstab')
        if not self.old_fstype:
            self.old_fstype = self.fstype
        self.log.info('Dumping %d megabytes across %d streams', self.megabytes,
                      self.streams)

    def raw_io(self, operation=''):
        """
        Performs raw read write operation.
        """
        if operation == 'read':
            self.log.info("Timing raw read of %d megabytes", self.megabytes)
            cmd = 'dd if=%s of=/dev/null bs=4k count=%d' % (self.fsys.device,
                                                            self.blocks)
            for option in self.dd_roptions.split():
                cmd += " %s=%s" % (option.split(":")[0], option.split(":")[1])
            process.run(cmd + ' > /dev/null', shell=True)
        if operation == 'write':
            self.log.info("Timing raw write of %d megabytes", self.megabytes)
            cmd = 'dd if=/dev/zero of=%s bs=4k count=%d' % (self.fsys.device,
                                                            self.blocks)
            for option in self.dd_woptions.split():
                cmd += " %s=%s" % (option.split(":")[0], option.split(":")[1])
            process.run(cmd, shell=True)

    def fs_write(self):
        """
         Write out 'streams' files in parallel background task.
        """
        for i in range(self.streams):
            s_file = os.path.join(self.workdir, 'poo%d' % (i + 1))
            cmd = 'dd if=/dev/zero of=%s bs=4k count=%d' % \
                (s_file, self.blocks_per_file)
            for option in self.fs_dd_woptions.split():
                cmd += " %s=%s" % (option.split(":")[0],
                                   option.split(":")[1])
            # Wait for everyone to complete
            proc = process.get_sub_process_klass(cmd)(cmd + ' > /dev/null',
                                                      shell=True)
            proc.start()
            proc.poll()
            proc.wait()
        sys.stdout.flush()
        sys.stderr.flush()

    def fs_read(self):
        """
        Read in 'streams' files in parallel background tasks.
        """
        for i in range(self.streams):
            s_file = os.path.join(self.workdir, 'poo%d' % (i + 1))
            cmd = 'dd if=%s of=/dev/null bs=4k count=%d' % \
                (s_file, self.blocks_per_file)
            for option in self.fs_dd_roptions.split():
                cmd += " %s=%s" % (option.split(":")[0],
                                   option.split(":")[1])
            if self.seq_read:
                process.run(cmd + ' > /dev/null', shell=True)
            else:
                # Wait for everyone to complete
                proc = process.get_sub_process_klass(cmd)(cmd + ' > /dev/null',
                                                          shell=True)
                proc.start()
                proc.poll()
                proc.wait()
            sys.stdout.flush()

    def _device_to_fstype(self, s_file, device=None):
        """
        Checks for the filesystem and returns the type of the filesystem.
        """
        if not device:
            device = self.fsys.device
        try:
            line = process.system_output('egrep ^%s %s' % (device, s_file))
            self.log.debug(line)
            fstype = line.split()[2]
            self.log.debug('Found %s is type %s from %s', device, fstype,
                           s_file)
            return fstype
        except process.CmdError:
            self.log.error('No %s found in %s', device, s_file)
            return None

    def test(self):
        """
        Test Execution.
        """
        operation = "self.megabytes / (time.time() - start)"

        try:
            self.fsys.unmount()
        except process.CmdError:
            pass

        self.log.info('------------- Timing raw operations ------------------')
        start = time.time()
        self.raw_io("write")
        self.raw_write_rate = operation

        start = time.time()
        self.raw_io("read")
        self.raw_read_rate = operation

        self.fsys.mkfs(self.fstype)
        self.fsys.mount(None)

        self.log.info('------------- Timing fs operations ------------------')
        start = time.time()
        self.fs_write()
        self.fs_write_rate = operation
        self.fsys.unmount()

        self.fsys.mount(None)
        start = time.time()
        self.fs_read()
        self.fs_read_rate = operation

        self.whiteboard = json.dumps({'raw_write': self.raw_write_rate,
                                      'raw_read': self.raw_read_rate,
                                      'fs_write': self.fs_write_rate,
                                      'fs_read': self.fs_read_rate})

    def cleanup(self):
        """
        Formatting the disk.
        """
        try:
            self.fsys.unmount()
        except process.CmdError:
            pass
        self.log.debug('\nFormatting %s back to type %s\n', self.fsys,
                       self.old_fstype)
        self.fsys.mkfs(self.old_fstype)
        self.fsys.mount(None)


if __name__ == "__main__":
    main()

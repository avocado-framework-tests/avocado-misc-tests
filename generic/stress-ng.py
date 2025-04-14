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
# Modified by : Abdul Haleem <abdhalee@linux.vnet.ibm.com>
# Author: Aneesh Kumar K.V <anesh.kumar@linux.vnet.ibm.com>
#

import os
import multiprocessing
from avocado import Test
from avocado.utils import process, build, archive, distro, memory, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class Stressng(Test):

    """
    Stress-ng testsuite
    :param stressor: Which streess-ng stressor to run (default is "mmapfork")
    :param timeout: Timeout for each run (default 300)
    :param workers: How many workers to create for each run (default 0)
    :source: git://kernel.ubuntu.com/cking/stress-ng.git

    :avocado: tags=cpu,memory,io,fs,privileged
    """

    def setUp(self):
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.stressors = self.params.get('stressors', default=None)
        self.ttimeout = self.params.get('ttimeout', default='300')
        self.workers = self.params.get(
            'workers', default=multiprocessing.cpu_count())
        self.class_type = self.params.get('class', default='all')
        self.verify = self.params.get('verify', default=True)
        self.syslog = self.params.get('syslog', default=True)
        self.metrics = self.params.get('metrics', default=True)
        self.maximize = self.params.get('maximize', default=True)
        self.times = self.params.get('times', default=True)
        self.aggressive = self.params.get('aggressive', default=True)
        self.exclude = self.params.get('exclude', default=None)
        self.v_stressors = self.params.get('v_stressors', default=None)
        self.parallel = self.params.get('parallel', default=True)
        self.common_args = self.params.get('common_args', default='')
        self.iteration = self.params.get('iteration', default=1)

        deps = ['gcc', 'make']
        if detected_distro.name in ['Ubuntu', 'debian']:
            deps.extend([
                'libaio-dev', 'libapparmor-dev', 'libattr1-dev', 'libbsd-dev',
                'libcap-dev', 'libgcrypt20-dev', 'libkeyutils-dev',
                'libsctp-dev', 'zlib1g-dev'])
        else:
            deps.extend(['libattr-devel', 'libcap-devel',
                         'libgcrypt-devel', 'zlib-devel', 'libaio-devel'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed, get the source and build" %
                            package)

        self.branch = self.params.get('branch', default='master')
        self.base_url = 'https://github.com/ColinIanKing/stress-ng/archive'
        if 'master' in self.branch:
            asset_url = '%s/master.zip' % self.base_url
        else:
            asset_url = '%s/refs/tags/V%s.zip' % (self.base_url, self.branch)
        tarball = self.fetch_asset('stressng.zip', locations=[asset_url],
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        sourcedir = os.path.join(self.workdir, 'stress-ng-%s' % self.branch)
        os.chdir(sourcedir)
        result = build.run_make(sourcedir,
                                process_kwargs={'ignore_status': True})
        for line in str(result).splitlines():
            if 'error:' in line:
                self.cancel(
                    "Build Failed, Please check the build logs for details !!")
        build.make(sourcedir, extra_args='install')
        dmesg.clear_dmesg()

    def test(self):
        args = []
        cmdline = ''
        timeout = ''
        if not (self.stressors or self.v_stressors):
            if 'all' in self.class_type:
                args.append('--all %s ' % self.workers)
            elif 'cpu' in self.class_type:
                self.workers = 2 * multiprocessing.cpu_count()
                args.append('--cpu %s --cpu-method all ' % self.workers)
            else:
                args.append('--class %s --sequential %s ' %
                            (self.class_type, self.workers))
        else:
            if self.parallel:
                if self.stressors:
                    for stressor in self.stressors.split(' '):
                        stressor_params = self.params.get(stressor, default='')
                        cmdline += '--%s %s %s ' % (stressor, self.workers,
                                                    stressor_params)
                if self.v_stressors:
                    for v_stressor in self.v_stressors.split(' '):
                        stressor_params = self.params.get(v_stressor, default='')
                        cmdline += '--%s %s %s ' % (v_stressor, self.workers,
                                                    stressor_params)
                args.append(cmdline)
        if self.class_type in ['memory', 'vm', 'all']:
            args.append('--vm-bytes 80% ')
        if 'filesystem' in self.class_type:
            self.loop_dev = process.system_output('losetup -f').decode("utf-8").strip()
            fstype = self.params.get('fs', default='ext4')
            mnt = self.params.get('dir', default='/mnt')
            self.stressmnt = os.path.join(mnt, "stressng")
            if (not os.path.exists(self.stressmnt)):
                os.mkdir(self.stressmnt)
            self.tmpout = process.system_output("ls /tmp", shell=True,
                                                ignore_status=True,
                                                sudo=True).decode("utf-8")
            if 'blockfile' not in self.tmpout:
                blk_dev = process.run("dd if=/dev/zero of=/tmp/blockfile \
                                      bs=1M count=5120")
                create_dev = process.run("losetup %s /tmp/blockfile"
                                         % self.loop_dev)
            if fstype == 'btrfs':
                if distro.detect().name == 'rhel':
                    self.cancel("btrfs is not supported on rhel")
            if fstype == "ext4":
                cmd = "mkfs.%s %s" % (fstype, self.loop_dev)
            else:
                cmd = "mkfs.%s -f %s" % (fstype, self.loop_dev)
            process.run(cmd)
            process.run("mount %s %s" % (self.loop_dev, self.stressmnt))
        if self.aggressive and self.maximize:
            args.append('--aggressive --maximize --oomable ')
        if self.exclude:
            args.append('--exclude %s ' % self.exclude)
        if self.verify:
            args.append('--verify ')
        if self.syslog:
            args.append('--syslog ')
        if self.metrics:
            args.append('--metrics ')
        if self.times:
            args.append('--times ')
        if self.common_args:
            args.append('%s ' % self.common_args)
        cmd = 'stress-ng %s' % " ".join(args)
        if self.parallel:
            if self.ttimeout:
                cmd += ' --timeout %s ' % self.ttimeout
            for _ in range(self.iteration):
                process.run(cmd, ignore_status=True, sudo=True)
        else:
            if self.ttimeout:
                timeout = ' --timeout %s ' % self.ttimeout
            if self.stressors:
                for stressor in self.stressors.split(' '):
                    stressor_params = self.params.get(stressor, default='')
                    stress_cmd = ' --%s %s %s %s ' % (stressor, self.workers, timeout,
                                                      stressor_params)
                    for _ in range(self.iteration):
                        process.run("%s %s" % (cmd, stress_cmd),
                                    ignore_status=True, sudo=True)
            if self.ttimeout and self.v_stressors:
                timeout = ' --timeout %s ' % str(
                    int(self.ttimeout) + int(memory.meminfo.MemTotal.g))
            if self.v_stressors:
                for stressor in self.v_stressors.split(' '):
                    stressor_params = self.params.get(stressor, default='')
                    stress_cmd = ' --%s %s %s %s ' % (stressor, self.workers, timeout,
                                                      stressor_params)
                    for _ in range(self.iteration):
                        process.run("%s %s" % (cmd, stress_cmd),
                                    ignore_status=True, sudo=True)
        error = dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops',
                                            'Segfault', 'soft lockup',
                                            'Unable to handle', 'ard LOCKUP'])
        if len(error):
            self.fail("Test failed with errors %s in dmesg" % error)

    def tearDown(self):
        if hasattr(self, 'loop_dev') and os.path.exists(self.loop_dev):
            process.run("umount %s" % self.loop_dev, ignore_status=True,
                        sudo=True)
            process.run("losetup -d %s" % self.loop_dev, ignore_status=True,
                        sudo=True)
        if os.path.exists('/tmp/blockfile'):
            process.run("rm -rf /tmp/blockfile", ignore_status=True, sudo=True)
        if hasattr(self, 'stressmnt') and os.path.exists(self.stressmnt):
            process.run(f"rm -rf {self.stressmnt}", ignore_status=True)

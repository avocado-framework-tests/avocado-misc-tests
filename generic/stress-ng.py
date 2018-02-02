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
from avocado import Test
from avocado import main
import multiprocessing
from avocado.utils import process, build, archive, distro, memory
from avocado.utils.software_manager import SoftwareManager


def clear_dmesg():
    process.run("dmesg -c ", sudo=True)


def collect_dmesg(object):
    object.whiteboard = process.system_output("dmesg")


class stressng(Test):

    """
    Stress-ng testsuite
    :param stressor: Which streess-ng stressor to run (default is "mmapfork")
    :param timeout: Timeout for each run (default 300)
    :param workers: How many workers to create for each run (default 0)
    :source: git://kernel.ubuntu.com/cking/stress-ng.git

    :avocado: tags=cpu,memory,io,fs,privileged
    """

    def setUp(self):
        sm = SoftwareManager()
        detected_distro = distro.detect()
        self.stressors = self.params.get('stressors', default=None)
        self.ttimeout = self.params.get('ttimeout', default='300')
        self.workers = self.params.get('workers', default='0')
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

        if 'Ubuntu' in detected_distro.name:
            deps = [
                'libaio-dev', 'libapparmor-dev', 'libattr1-dev', 'libbsd-dev',
                'libcap-dev', 'libgcrypt11-dev', 'libkeyutils-dev', 'libsctp-dev', 'zlib1g-dev']
        else:
            deps = ['libattr-devel', 'libbsd-devel', 'libcap-devel',
                    'libgcrypt-devel', 'keyutils-libs-devel', 'zlib-devel', 'libaio-devel']
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.log.info(
                    '%s is needed, get the source and build' % package)

        tarball = self.fetch_asset('stressng.zip', locations=[
                                   'https://github.com/ColinIanKing/'
                                   'stress-ng/archive/master.zip'],
                                   expire='7d')
        archive.extract(tarball, self.srcdir)
        sourcedir = os.path.join(self.srcdir, 'stress-ng-master')
        os.chdir(sourcedir)
        result = build.run_make(sourcedir, ignore_status=True)
        for line in str(result).splitlines():
            if 'error:' in line:
                self.cancel(
                    "Unsupported OS, Please check the build logs !!")
        build.make(sourcedir, extra_args='install')
        clear_dmesg()

    def test(self):
        args = []
        cmdline = ''
        timeout = ''
        self.workers = multiprocessing.cpu_count()
        if not self.stressors:
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
                for stressor in self.stressors.split(' '):
                    cmdline += '--%s %s ' % (stressor, self.workers)
                for v_stressor in self.v_stressors.split(' '):
                    cmdline += '--%s %s ' % (v_stressor, self.workers)
                args.append(cmdline)
        if self.class_type in ['memory', 'vm', 'all']:
            args.append('--vm-bytes 80% ')
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
        cmd = 'stress-ng %s' % " ".join(args)
        if self.parallel:
            if self.ttimeout:
                cmd += ' --timeout %s ' % self.ttimeout
            process.run(cmd, ignore_status=True, sudo=True)
        else:
            if self.ttimeout:
                timeout = ' --timeout %s ' % self.ttimeout
            for stressor in self.stressors.split(' '):
                stress_cmd = ' --%s %s %s' % (stressor, self.workers, timeout)
                process.run("%s %s" % (cmd, stress_cmd), ignore_status=True, sudo=True)
            if self.ttimeout and self.v_stressors:
                timeout = int(self.ttimeout) + int(memory.memtotal()/1024/1024)
            for stressor in self.v_stressors.split(' '):
                stress_cmd = ' --%s %s %s' % (stressor, self.workers, timeout)
                process.run("%s %s" % (cmd, stress_cmd), ignore_status=True, sudo=True)
        collect_dmesg(self)
        ERROR = []
        pattern = ['WARNING: CPU:', 'Oops',
                   'Segfault', 'soft lockup', 'Unable to handle']
        logs = process.system_output('dmesg').splitlines()
        for fail_pattern in pattern:
            for log in logs:
                if fail_pattern in log:
                    ERROR.append(log)
        if ERROR:
            self.fail("Test failed with following errors in demsg :  %s " % "\n".joing(ERROR))


if __name__ == "__main__":
    main()

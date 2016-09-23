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
#
# Copyright: 2016 IBM
# Author: Pavithra D P <pavithra@linux.vnet.ibm.com>

import os
import subprocess


class cpu_hotplug():
    count = 0

    def func_hot(self):
        cmd = "ls -1 /sys/devices/system/cpu/ | grep ^cpu[0-9][0-9]* |wc -l"
        cpu_list = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        (list, err) = cpu_list.communicate()
        for count in range(0, 100):
            for cpus in range(1, (int(list))):
                cpu = "cpu%s" % (cpus)
                cmd = 'echo 0 > /sys/devices/system/cpu/%s/online' % cpu
                status = os.system(cmd)
                if status != 0:
                    print "Error offline cpu %s" % (cpus)
                else:
                    print "offline'd CPU %s" % (cpus)
                cmd1 = 'echo 1 > /sys/devices/system/cpu/%s/online' % cpu
                status1 = os.system(cmd1)
                if status1 != 0:
                    print "Error online cpu %s" % (cpus)
                else:
                    print "Online'd CPU %s" % (cpus)

hotplug = cpu_hotplug()
hotplug.func_hot()

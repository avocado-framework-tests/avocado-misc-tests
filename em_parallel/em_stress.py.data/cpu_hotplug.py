#!/usr/bin/env python
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

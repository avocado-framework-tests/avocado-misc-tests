#!/bin/python
from random import randint
from time import sleep
import subprocess


def check_loaded():
    processA = subprocess.Popen("lsmod", stdout=subprocess.PIPE)
    processB = subprocess.Popen(["grep", "powernv_cpufreq"], stdin=processA.stdout, stdout=subprocess.PIPE)
    mod = processB.communicate()[0]
    if mod:
        return True
    else:
        return False


class load():
    mod_name = "powernv_cpufreq"
    count = 0
    version = 1

    def load_func(self):
        for count in range(0, 100):
            if not check_loaded():
                print "Module not loaded,Loading the module..."
                try:
                    subprocess.check_call("modprobe" + ' ' + 'powernv_cpufreq', shell=True)
                    sleep(randint(5, 15))
                except subprocess.CalledProcessError as e:
                    print "Could not load module "
            else:
                print "Module already Loaded,Removing the module"
                try:
                    subprocess.check_call("rmmod" + ' ' + 'powernv_cpufreq', shell=True)
                    sleep(randint(5, 15))
                except subprocess.CalledProcessError as e:
                    print "could not unload the module"


A = load()
A.load_func()

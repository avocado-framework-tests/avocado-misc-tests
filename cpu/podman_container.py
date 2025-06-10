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
# Copyright: 2024 IBM
# Author: Samir A Mulani <samir@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import process, build, archive, distro
from avocado.utils.software_manager.manager import SoftwareManager
import time


class podman(Test):
    def setUp(self):
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'patch']
        deps.extend(['podman'])
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        url = ("http://sourceforge.net/projects/ebizzy/files/ebizzy"
               "/0.3/ebizzy-0.3.tar.gz")

        tarball = self.fetch_asset(self.params.get("ebizy_url", default=url))
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])

        self.sourcedir = os.path.join(self.workdir, version)
        os.chdir(self.sourcedir)
        process.run('[ -x configure ] && ./configure', shell=True)
        build.make(self.sourcedir)
        self.cpu_quota = self.params.get("cpu_quota", default=50000)
        self.cpu_period = self.params.get("cpu_period", default=100000)
        self.workload_run_time = self.params.get("run_time", default=1000)

    def Generate_docker_file(self):
        """
        Generating the docker image with ebizzy binary attached
        """
        self.log.info("Inside the Generate_docker_file---")
        Docker_row_data = "FROM busybox\nCOPY ebizzy \
                /usr/local/bin/ebizzy\nRUN chmod +x /usr/local/bin/ebizzy"
        with open("Dockerfile", 'w') as file_obj:
            file_obj.write(Docker_row_data)

    def Build_docker_image(self):
        """
        Building the docker image with ebizzy workload so that the
        podman container will fetch the ebizzy image at run time
        """
        cmd = "podman build -t custom-busybox-ebizzy ."
        process.system(cmd,
                       ignore_status=True, shell=False, sudo=True)

    def run_container(self):
        """
        Running the podman container and attaching ebizzy workload
        """
        workload_path = "/usr/local/bin/ebizzy"
        cmd = "podman run --detach --cpu-period=%s --cpu-quota=%s \
                custom-busybox-ebizzy %s -S %s" % (self.cpu_period,
                                                   self.cpu_quota,
                                                   workload_path,
                                                   self.workload_run_time)

        process.system(cmd,
                       ignore_status=True, shell=False, sudo=True)

    def log_generater(self, smt_state):
        """
        Capture the podman stats
        :param smt_state: passing the smt state value to capture the logs
        for same state.
        """
        podman_dir = self.logdir + "/podman"
        if not os.path.isdir(podman_dir):
            os.mkdir(podman_dir)

        log_dir = podman_dir + "/" + str(smt_state) + ".txt"
        cmd = "nohup podman stats &> %s &" % (log_dir)
        process.run(cmd, shell=True)
        self.log.info("Waiting for some time dump the podman stats to file")
        time.sleep(30)
        self.log.info("Killing the podman stats command PID")
        cmd = 'pgrep -f "podman stats"'
        cmd_output = process.run(cmd, shell=True).stdout
        pid_decode = cmd_output.decode('utf-8')
        process_pid = pid_decode.strip("\n")
        cmd = "kill %s" % (process_pid)
        process.run(cmd, shell=True)

    def test(self):
        """
        Here we are performing below four operations,
        1. Generate_docker_file
        2. Build_docker_image
        3. run_container with ebizzy workload.
        4. Capturing the podman stats log
        """
        self.Generate_docker_file()
        self.Build_docker_image()
        self.run_container()
        cpu_controller = ["2", "4", "6", "on", "off"]
        for smt_mode in cpu_controller:
            cmd = "ppc64_cpu --smt={}".format(smt_mode)
            self.log.info("smt mode %s", smt_mode)
            self.log_generater(smt_mode)
            process.run(cmd, shell=True)
        self.log.info("Done with the test--------")

    def tearDown(self):
        """
        Sets back SMT to original value as was before the test.
        Sets back cpu states to online
        killing all the container [Podman]
        """
        cmd = "podman kill --all"
        process.run(cmd, shell=True)
        cmd = "ppc64_cpu --smt=on"
        process.run(cmd, shell=True)

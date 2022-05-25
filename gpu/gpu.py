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
# Copyright: 2021 IBM
# Author: Kalpana Shetty <kalshett@in.ibm.com>

import os
import shutil
from avocado import Test, skipUnless
from avocado.utils import build, process, distro, git
from avocado.utils.software_manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_POWER9 = 'POWER9' in open('/proc/cpuinfo', 'r').read()


class GPUTests(Test):
    """
    GPU test cases make use of sample test code provided by the
    CUDA toolkil and other generic test suites cover functional tests.
    Tester to download and setup CUDA stack which will take care of
    installing nvidia driver too.
    """
    @skipUnless(IS_POWER_NV & IS_POWER9,
                "GPU tests are supported only on PowerNV(POWER9)")
    def process_output(self, output):
        failed_tests = []
        for line in output.decode("utf-8").splitlines():
            if "fail" in line:
                failed_tests.append(line)
        if failed_tests:
            self.fail("%s" % failed_tests)

    def run_test(self, run_cmd):
        os.chdir(self.teststmpdir)
        output = process.system_output(run_cmd, ignore_status=True)
        self.process_output(output)

    def setUp(self):
        """
        Install pre-requisite packages, compile samples and xgemm test code
        """
        smg = SoftwareManager()
        self.dist = distro.detect()
        if self.dist.name not in ['rhel']:
            self.cancel('Unsupported OS %s' % self.dist.name)
        lspci_op = process.system_output(
            "lspci", ignore_status=True, shell=True)
        if "NVIDIA" not in lspci_op.decode():
            self.cancel("There is NO NVIDIA GPU in the system, tests are\
                        cancelled.")
        cuda_rpm_op = process.system_output(
            "rpm -qa", ignore_status=True, shell=True)
        if "cuda" not in cuda_rpm_op.decode():
            self.cancel("Please download and setup CUDA toolkit from NVIDIA")

        deps = ['gcc', 'make']
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % (package))
        cuda_sample = '/usr/local/cuda/samples/'
        cuda_exec = 'bin/ppc64le/linux/release/'
        os.chdir(cuda_sample)
        build.make(cuda_sample)
        self.testdir = os.path.join(cuda_sample, cuda_exec)

        for file_name in ['xgemm.c', 'Makefile']:
            shutil.copyfile(self.get_data(file_name),
                            os.path.join(self.teststmpdir, file_name))
        build.make(self.teststmpdir)

    def test_cuda_sample(self):
        '''
        GPU cuda sample tests
        '''
        self.log.info("test_cuda_sample: Sample cua tests running")
        os.chdir(self.testdir)
        for test in os.listdir(self.testdir):
            self.log.info("Running Sample: %s" % test)
            test_run = os.path.join(self.testdir, test)
            process.system(test_run, ignore_status=True, shell=True)

    def test_cuda_uvm(self):
        '''
        GPU Unified tests
        '''
        self.log.info("test_cuda_uvm: GPU Unified tests")

        self.ld_path = "LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64:\
                        /usr/local/cuda/extras/CUPTI/lib64"
        test_dir = "/usr/local/cuda/extras/CUPTI/samples/unified_memory/"
        exp_cmd = "export %s" % self.ld_path
        process.system(exp_cmd, ignore_status=True, shell=True)
        build.make(test_dir)
        os.chdir(test_dir)
        uvm_cmd = "/usr/local/cuda/extras/CUPTI/samples/unified_memory/unified_memory"
        output = process.system_output(uvm_cmd, ignore_status=True, shell=True)
        self.process_output(output)

    def test_gpu_burn(self):
        '''
        GPU burn tests
        '''
        self.log.info("test_gpu_burn: GPU Burn tests")

        git.get_repo('https://github.com/wilicc/gpu-burn.git',
                     destination_dir=self.workdir)
        os.chdir(self.workdir)
        build.make(self.workdir)
        output = process.system_output(
            './gpu_burn', ignore_status=True, shell=True)
        self.process_output(output)

    def test_xgemm_short(self):
        '''
        GPU single/double precision short xgemm tests
        '''
        self.log.info("test_xgemm_short:GPU single/double precision short\
                      xgemm tests")
        xgemm_short_tests = ['short_sg', 'short_dg']
        for test_name in xgemm_short_tests:
            run_cmd = "make %s" % test_name
            self.run_test(run_cmd)

    def test_xgemm_long(self):
        '''
        GPU single/double precision long xgemm tests
        '''
        self.log.info("test_xgemm_long: GPU single/double precision long\
                      xgemm tests")
        xgemm_long_tests = ['long_sg', 'long_dg']
        for test_name in xgemm_long_tests:
            run_cmd = "make %s" % test_name
            self.run_test(run_cmd)

    def test_xgemm_numa(self):
        '''
        GPU xgemm tests pinned to numa nodes tests
        '''
        self.log.info("test_xgemm_numa: GPU single/double precision\
                      xgemm numa tests")
        gpu_cmd = "nvidia-smi --list-gpus | awk '{print $2}' | cut -b 1"
        gpu_list = process.system_output(gpu_cmd, shell=True,
                                         ignore_status=True, sudo=True).decode().splitlines()
        self.log.info("test_xgemm_numa:GPU List=%s" % gpu_list)
        os.chdir(self.teststmpdir)
        # Baremeatl has 0, 8 as numa nodes
        for numa_node in [0, 8]:
            for gpu in gpu_list:
                self.log.info("test_xgemm_numa(sgemm): GPU=%s" % gpu)
                sgemm_numa = "numactl -N %s ./sgemm -d%s" % (numa_node, gpu)
                sgemm_proc = process.SubProcess(sgemm_numa, shell=True,
                                                sudo=True)
                sgemm_proc.start()

                self.log.info("test_xgemm_numa(dgemm): GPU=%s" % gpu)
                dgemm_numa = "numactl -N %s ./dgemm -d%s" % (numa_node, gpu)
                dgemm_proc = process.SubProcess(dgemm_numa, shell=True,
                                                sudo=True)
                dgemm_proc.start()

                sgemm_proc.wait()
                dgemm_proc.wait()

    def test_bandwidth(self):
        '''
        GPU bandwidth tests
        '''
        self.log.info("test_bandwidth: bandwidth tests with CPU binding")
        os.chdir(self.testdir)
        for numa_node in [0, 8]:
            bandwidth_cmd = "numactl --cpunodebind=%s ./bandwidthTest --csv \
                             --device=all --memory=pinned --mode=range\
                             --start=134217728 --end=134217728\
                             --increment=100" % numa_node
            bandwidth_proc = process.SubProcess(bandwidth_cmd, shell=True,
                                                sudo=True)
            bandwidth_proc.start()
            bandwidth_proc.wait()

    def test_nbody(self):
        '''
        GPU nBody benchmark tests
        '''
        self.log.info("test_nbody: GPU nBody benchmark tests")
        gpu_cmd = "nvidia-smi --list-gpus | awk '{print $2}' | cut -b 1"
        gpu_list = process.system_output(gpu_cmd, shell=True,
                                         ignore_status=True, sudo=True).decode().splitlines()
        self.log.info("test_nbody:Total GPUs=%s, GPU List=%s" %
                      (len(gpu_list), gpu_list))
        os.chdir(self.testdir)
        nbody_cmd = "./nbody -benchmark -numbodies=50331648 -numdevices=%s\
                     -fp64" % len(gpu_list)
        nbody_proc = process.SubProcess(nbody_cmd, shell=True, sudo=True)
        nbody_proc.start()
        nbody_proc.wait()

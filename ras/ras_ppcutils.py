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
# Copyright: 2016 IBM
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>
# Author: Sachin Sant <sachinp@linux.ibm.com>
# Author: Shirisha Ganta <shirisha.ganta1@ibm.com>

import os
import re
from avocado import Test
from avocado.utils import process, distro, build, archive, disk
from avocado import skipIf, skipUnless
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class RASToolsPpcutils(Test):

    """
    This test checks various RAS tools bundled with powerpc-utils
    package/repository.

    :avocado: tags=ras,ppc64le
    """
    fail_cmd = list()

    def run_cmd(self, cmd):
        cmd_result = process.run(cmd, ignore_status=True, sudo=True,
                                 shell=True)
        if cmd_result.exit_status != 0:
            self.fail_cmd.append(cmd)
        return

    def error_check(self):
        if len(self.fail_cmd) > 0:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s" % self.fail_cmd[cmd])
            self.fail("RAS: Failed commands are: %s" % self.fail_cmd)

    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    def setUp(self):
        """
        Ensure packages are installed
        """
        self.sm = SoftwareManager()
        self.run_type = self.params.get('type', default='distro')
        for package in ['ppc64-diag', 'powerpc-utils']:
            if not self.sm.check_installed(package) and not \
                    self.sm.install(package):
                self.cancel("Fail to install %s required for this test." %
                            package)

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True,
                                     sudo=True).decode("utf-8").strip()

    def test_build_upstream(self):
        """
        For upstream target download and compile source code
        Caution : This function will overwrite system installed
        lsvpd Tool binaries with upstream code.
        """
        if self.run_type == 'upstream':
            self.detected_distro = distro.detect()
            deps = ['gcc', 'make', 'automake', 'autoconf', 'bison', 'flex',
                    'libtool', 'zlib-devel', 'ncurses-devel', 'librtas-devel']
            if 'SuSE' in self.detected_distro.name:
                deps.extend(['libnuma-devel'])
            elif self.detected_distro.name in ['centos', 'fedora', 'rhel']:
                deps.extend(['numactl-devel'])
            else:
                self.cancel("Unsupported Linux distribution")
            for package in deps:
                if not self.sm.check_installed(package) and not \
                        self.sm.install(package):
                    self.cancel("Fail to install %s required for this test." %
                                package)
            url = self.params.get(
                'ppcutils_url', default='https://github.com/'
                'ibm-power-utilities/powerpc-utils/archive/refs/heads/'
                'master.zip')
            tarball = self.fetch_asset('ppcutils.zip', locations=[url],
                                       expire='7d')
            archive.extract(tarball, self.workdir)
            self.sourcedir = os.path.join(self.workdir, 'powerpc-utils-master')
            os.chdir(self.sourcedir)
            # TODO : For now only this test is marked as failed.
            # Additional logic should be added to skip all the remaining
            # test_() functions for upstream target if source code
            # compilation fails. This will require a way to share
            # variable/data across test_() functions.
            self.run_cmd('./autogen.sh')
            self.error_check()
            self.run_cmd('./configure --prefix=/usr')
            self.error_check()
            build.make(self.sourcedir)
            build.make(self.sourcedir, extra_args='install')
        else:
            self.cancel("This test is supported with upstream as target")

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_set_poweron_time(self):
        """
        set_poweron_time schedules the power on time
        """
        self.log.info("===============Executing set_poweron_time tool test===="
                      "===========")
        list = ['-m', '-h', '-d m2', '-t M6D15h12']
        for list_item in list:
            self.run_cmd('set_poweron_time %s' % list_item)
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_sys_ident_tool(self):
        """
        sys_ident provides unique system identification information
        """
        self.log.info("===============Executing sys_ident_tool test==========="
                      "====")
        self.run_cmd("sys_ident -p")
        self.run_cmd("sys_ident -s")
        self.error_check()

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_drmgr(self):
        """
        drmgr can be used for pci, cpu or memory hotplug
        """
        self.log.info("===============Executing drmgr tool test============="
                      "==")
        self.run_cmd("drmgr -h")
        self.run_cmd("drmgr -C")
        lcpu_count = self.run_cmd_out("lparstat -i | "
                                      "grep \"Online Virtual CPUs\" | "
                                      "cut -d':' -f2")
        if lcpu_count:
            lcpu_count = int(lcpu_count)
            if lcpu_count >= 2:
                self.run_cmd("drmgr -c cpu -r -q 1")
                self.run_cmd("lparstat")
                self.run_cmd("drmgr -c cpu -a -q 1")
                self.run_cmd("lparstat")
        self.error_check()

    def test_lsprop(self):
        """
        lsprop provides device tree information
        """
        self.log.info("===============Executing lsprop tool test============="
                      "==")
        self.run_cmd("lsprop")
        self.error_check()

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_lsslot(self):
        """
        lsslot lists the slots based on the option provided
        """
        self.log.info("===============Executing lsslot tool test============="
                      "==")
        self.run_cmd("lsslot")
        self.run_cmd("lsslot -c mem")
        if self.run_cmd_out("lspci"):
            self.run_cmd_out("lsslot -ac pci")
        if not IS_KVM_GUEST:
            self.run_cmd("lsslot -c cpu -b")
        self.run_cmd("lsslot -c pci -o")
        slot = self.run_cmd_out("lsslot | cut -d' ' -f1 | head -2"
                                " | tail -1")
        if slot:
            self.run_cmd("lsslot -s %s" % slot)
        self.error_check()

    def test_nvram(self):
        """
        nvram command retrieves and displays NVRAM data
        """
        self.log.info("===============Executing nvram tool test============="
                      "==")
        list = ['--help', '--partitions', '--print-config -p common',
                '--dump common --verbose']
        for list_item in list:
            self.run_cmd('nvram %s' % list_item)
        self.error_check()

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_ofpathname(self):
        """
        ofpathname translates the device name between logical name and Open
        Firmware name
        """
        self.log.info("===============Executing ofpathname tool test=========="
                      "=====")
        self.run_cmd("ofpathname -h")
        self.run_cmd("ofpathname -V")
        disk_name = self.run_cmd_out("df -h | egrep '(s|v)da[1-8]' | "
                                     "tail -1 | cut -d' ' -f1")
        if disk_name:
            self.run_cmd("ofpathname %s" % disk_name)
            of_name = self.run_cmd_out("ofpathname %s"
                                       % disk_name).split(':')[0]
            self.run_cmd("ofpathname -l %s" % of_name)
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_rtas_ibm_get_vpd(self):
        """
        rtas_ibm_get_vpd gives vpd data
        """
        self.log.info("===============Executing rtas_ibm_get_vpd tool test===="
                      "===========")
        output_file = os.path.join(self.outputdir, 'output')
        self.run_cmd("rtas_ibm_get_vpd >> %s 2>&1" % output_file)
        self.error_check()

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_rtas_errd_and_rtas_dump(self):
        """
        rtas_errd adds RTAS events to /var/log/platform and rtas_dump dumps
        RTAS events
        """
        self.log.info("===============Executing rtas_errd and rtas_dump tools"
                      " test===============")
        self.log.info("1 - Injecting event")
        rtas_file = self.get_data('rtas')
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s" % rtas_file)
        self.log.info("2 - Checking if the event was dumped to /var/log/"
                      "platform")
        self.run_cmd("cat /var/log/platform")
        myplatform_file = os.path.join(self.outputdir, 'myplatformfile')
        my_log = os.path.join(self.outputdir, 'mylog')
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s -p %s -l %s" %
                     (rtas_file, myplatform_file, my_log))
        self.run_cmd("cat %s" % myplatform_file)
        self.run_cmd("cat %s" % my_log)
        self.log.info("3 - Verifying rtas_dump command")
        self.run_cmd("rtas_dump -f %s" % rtas_file)
        self.log.info("4 - Verifying rtas_dump with event number 2302")
        self.run_cmd("rtas_dump -f %s -n 2302" % rtas_file)
        self.log.info("5 - Verifying rtas_dump with verbose option")
        self.run_cmd("rtas_dump -f %s -v" % rtas_file)
        self.log.info("6 - Verifying rtas_dump with width 20")
        self.run_cmd("rtas_dump -f %s -w 20" % rtas_file)
        self.error_check()

    @skipIf(IS_POWER_NV, "This test is not supported on PowerNV platform")
    def test_rtas_event_decode(self):
        """
        Decode RTAS events
        """
        self.log.info("==============Executing rtas_event_decode tool test===="
                      "===========")
        cmd = "rtas_event_decode -w 500 -dv -n 2302 < %s" % self.get_data(
            'rtas')
        cmd_result = process.run(
            cmd, ignore_status=True, sudo=True, shell=True)
        if cmd_result.exit_status not in [17, 13]:
            self.fail("rtas_event_decode tool: %s command failed in "
                      "verification" % cmd)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_uesensor(self):
        """
        View the state of system environmental sensors
        """
        self.log.info("===============Executing uesensor tool test===="
                      "===========")
        self.run_cmd("uesensor -l")
        self.run_cmd("uesensor -a")
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_serv_config(self):
        """
        View and configure system service policies and settings
        """
        self.log.info("===============Executing serv_config tool test===="
                      "===========")
        list = [
            '-l', '-b', '-s', '-r', '-m', '-d', '--remote-maint',
            '--surveillance', '--reboot-policy', '--remote-pon', '-d --force']
        for list_item in list:
            cmd = "serv_config %s" % list_item
            self.run_cmd(cmd)
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_ls_vscsi(self):
        """
        Provide information on Virtual devices
        """
        self.log.info("===============Executing ls-vscsi tool test===="
                      "===========")
        self.run_cmd("ls-vscsi")
        self.run_cmd("ls-vscsi -h")
        self.run_cmd("ls-vscsi -V")
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_ls_veth(self):
        """
        Provide information about Virtual Ethernet devices
        """
        self.log.info("===============Executing ls-veth tool test===="
                      "===========")
        self.run_cmd("ls-veth")
        self.run_cmd("ls-veth -h")
        self.run_cmd("ls-veth -V")
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_ls_vdev(self):
        """
        Provide information about Virtual SCSI adapters and devices
        """
        self.log.info("===============Executing ls-vdev tool test===="
                      "===========")
        self.is_fail = 0
        self.run_cmd("ls-vdev")
        self.run_cmd("ls-vdev -h")
        self.run_cmd("ls-vdev -V")
        dev_name = self.run_cmd_out("ls-vdev").split()[1]
        lsblk_disks = disk.get_disks()
        lsblk_dev_name = [i.replace('/dev/', '') for i in lsblk_disks]
        if dev_name.strip() not in lsblk_dev_name:
            self.is_fail += 1
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in ls-vdev tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_lsdevinfo(self):
        """
        Provide information on Virtual devices
        """
        self.log.info("===============Executing lsdevinfo tool test===="
                      "===========")
        self.run_cmd("lsdevinfo")
        list = ['-h', '-V', '-c', '-R', '-F name,type']
        for list_item in list:
            cmd = "lsdevinfo %s" % list_item
            self.run_cmd(cmd)
        interface = self.run_cmd_out(
            "ifconfig | head -1 | cut -d':' -f1")
        self.run_cmd("lsdevinfo -q name=%s" % interface)
        disk_name = self.run_cmd_out("df -h | egrep '(s|v)d[a-z][1-8]' | "
                                     "tail -1 | cut -d' ' -f1").strip("12345")
        self.run_cmd("lsdevinfo -q name=%s" % disk_name)
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_hvcsadmin(self):
        """
        Hypervisor virtual console server administration utility
        """
        self.log.info("===============Executing hvcsadmin tool test===="
                      "===========")
        list = ['--status', '--version', '-all', '-noisy', '-rescan']
        for list_item in list:
            cmd = "hvcsadmin %s" % list_item
            self.run_cmd(cmd)
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_bootlist(self):
        """
        Update and view information on bootable devices
        """
        self.log.info("===============Executing bootlist tool test===="
                      "===========")
        list = ['-m normal -r', '-m normal -o',
                '-m service -o', '-m both -o']
        for list_item in list:
            cmd = "bootlist %s" % list_item
            self.run_cmd(cmd)
        interface = self.run_cmd_out(
            "lsvio -e | cut -d' ' -f2")
        disk_name = self.run_cmd_out("df -h | egrep '(s|v)d[a-z][1-8]' | "
                                     "tail -1 | cut -d' ' -f1").strip("12345")
        file_path = os.path.join(self.workdir, 'file')
        process.run("echo %s > %s" %
                    (disk_name, file_path), ignore_status=True,
                    sudo=True, shell=True)
        process.run("echo %s >> %s" %
                    (interface, file_path), ignore_status=True,
                    sudo=True, shell=True)
        self.run_cmd("bootlist -r -m both -f %s" % file_path)
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_lparstat(self):
        """
        Test case to validate lparstat functionality. lparstat is a tool
        to display logical partition related information and statistics.
        And also validating lparstat -x output should match with the lpar
        security flavor
        And also validates laprstat -E output %busy and %idle
        should not be < 0 or > 100
        Normalized %busy + %idle should be equal to percentage under frequency
        And also checks for number of physical processors consumed
        on different smt levels
        """
        self.log.info("===============Executing lparstat tool test===="
                      "===========")
        lists = self.params.get('lparstat_list',
                                default=['-i', '-x', '-E', '-l', '1 2'])
        for list_item in lists:
            cmd = "lparstat %s" % list_item
            self.run_cmd(cmd)
        self.error_check()
        output = process.system_output("lparstat -x").decode("utf-8")
        value = re.search(r"\d+", output).group()
        output = process.system_output("grep security /proc/powerpc/lparcfg"
                                       ).decode("utf-8")
        security_flavor = output.split("=")[1]
        if value == security_flavor:
            self.log.info("Lpar security flavor is correct")
        else:
            self.fail("Lpar security flavor is incorrect")
        lists = self.params.get('lparstat_nlist',
                                default=['--nonexistingoption'])
        for list_item in lists:
            cmd = "lparstat %s" % list_item
            if not process.system(cmd, ignore_status=True, sudo=True):
                self.log.info("%s command passed" % cmd)
                self.fail("lparstat: Expected failure, %s command executed \
                          successfully." % cmd)
        output = process.system_output("lparstat -E 1 1").decode("utf-8")
        for line in output.splitlines():
            if 'GHz' in line:
                # Define the regular expression pattern
                pattern = (r'(\d+\.\d+)\s+(\d+\.\d+)\s+\d+\.\d+GHz\[\s*(\d+)%\]\s+'
                           r'(\d+\.\d+)\s+(\d+\.\d+)')
                # Find all matches in the input string
                matches = re.findall(pattern, line)
                for data in matches:
                    actual_busy = float(data[0])
                    actual_idle = float(data[1])
                    normal_idle = float(data[3])
                    normal_busy = float(data[4])
                    normal = normal_idle + normal_busy
                    freq_percentile = float(data[2])
        if (actual_busy > 0) and (actual_idle < 100):
            self.log.info("Busy and idle actual values are correct")
        else:
            self.fail("Busy and idle actual values are incorrect")
        if normal == freq_percentile:
            self.log.info("Normalised busy plus idle value match with \
                          Frequency percentage")
        else:
            self.fail("Normalised busy plus idle value does not match \
                        with Frequency percentage")
        list_physc = []
        for i in [2, 4, 8, "off"]:
            self.run_cmd("ppc64_cpu --smt=%s" % i)
            smt_initial = re.split(
                    r'=| is ', self.run_cmd_out("ppc64_cpu --smt"))[1]
            if smt_initial == str(i):
                output = process.system_output("lparstat 1 1").decode("utf-8")
                if output.strip() != "" and "\n" in output:
                    lines = output.splitlines()
                    last_line = lines[-1]
                    pattern = r'\b\d+\.\d+\b'
                    matches = re.findall(pattern, last_line)
                    physc_val = float(matches[4])
                    list_physc.append(physc_val)
        if len(set(list_physc)) == 1:
            self.log.info("Correctly displaying the number of physical \
                          processors consumed")
        else:
            self.fail("number of physical processors consumed are not \
                      displaying correct")

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test_lparnumascore(self):
        """
        lparnumascore displays the NUMA affinity score for the running LPAR.
        The score is a number between 0 and 100. A score of 100 means that
        all the resources are seen correctly, while a score of 0 means that
        all the resources have been moved to different nodes. There is a
        dedicated score for each resource type
        """
        self.log.info("===============Executing lparnumascore tool test===="
                      "===========")
        self.run_cmd('lparnumascore')
        lists = self.params.get('lparnumascore_list',
                                default=['-c cpu', '-c mem'])
        for list_item in lists:
            self.run_cmd('lparnumascore %s' % list_item)
        self.error_check()

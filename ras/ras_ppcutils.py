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
import pexpect
import sys
from avocado import Test
from avocado.utils import process, distro, build, archive, disk
from avocado import skipIf, skipUnless
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import pci

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
        # get the disk name
        self.disk_name = ''
        output = process.system_output(
            "df -h", shell=True).decode().splitlines()
        filtered_lines = [line for line in output if re.search(
            r'\b(sd[a-z]\d+|vd[a-z]\d+|nvme\d+n\d+p\d+)\b', line)]
        if filtered_lines:
            disk_entry = filtered_lines[-1].split()[0]
            # Strip partition number: for sdX or vdX it’s trailing digits, for nvme it’s after 'p'
            self.disk_name = re.sub(r'(\d+$|p\d+$)', '', disk_entry)
        if not self.disk_name:
            self.cancel("Couldn't get Disk name.")

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
        output = self.run_cmd_out("lparstat -i").splitlines()
        for line in output:
            if 'Online Virtual CPUs' in line:
                lcpu_count = line.split(':')[1].strip()
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

    def isAccelerator(self):
        for dev in os.listdir('/sys/bus/pci/devices'):
            try:
                if pci.get_pci_class_name(dev) == "accelerator":
                    return True
            except Exception:
                pass
        return False

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

        if self.isAccelerator():
            self.log.info("Accelerator detected, verifying Spyre card details")
            lsslot_output = self.run_cmd_out("lsslot -c pci")
            lspci_output = self.run_cmd_out("lspci")
            spyre_devices = []
            for line in lspci_output.strip().split('\n'):
                if 'spyre' in line.lower():
                    parts = line.split()
                    if parts:
                        spyre_devices.append(parts[0])
            if not spyre_devices or spyre_devices == ['']:
                self.fail("No Spyre devices found in system")
            for device in spyre_devices:
                if device and device not in lsslot_output:
                    self.fail(
                        f"Spyre device {device} not found in lsslot -c pci output")
            self.log.info("Spyre card details verified successfully")

        self.run_cmd("lsslot -c pci -o")
        slot = ''
        output = self.run_cmd_out("lsslot").splitlines()
        fields = [line.split()[0] for line in output if line]
        if len(fields) > 1:
            slot = fields[1]
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
        if self.disk_name:
            self.run_cmd("ofpathname %s" % self.disk_name)
            of_name = self.run_cmd_out("ofpathname %s"
                                       % self.disk_name).split(':')[0]
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
            child = pexpect.spawn(cmd, encoding='utf-8')
            child.logfile = sys.stdout  # Log output for debugging
            if list_item == '-b':
                try:
                    child.expect("Reboot Policy Settings:", timeout=5)
                    child.expect(
                        r"Auto Restart Partition \(1=Yes, 0=No\) \[1\]:", timeout=5)
                    child.sendline("1")
                    child.expect(
                        r"Are you certain you wish to update the system configuration\s*to the specified values\? \(yes/no\) \[no\]:", timeout=5)
                    child.sendline("yes")
                except pexpect.TIMEOUT:
                    self.fail("Timeout waiting for expected prompt")
            child.wait()
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
        output = self.run_cmd_out("ls-vdev").strip()
        if not output:
            self.cancel("No virtual SCSI devices found on this system")
        try:
            dev_name = output.split()[1]
        except IndexError:
            self.fail("Unable to parse ls-vdev output:\n%s" % output)
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
        output = process.system_output(
            "ip link ls up", shell=True).decode().strip()
        interface = ""
        for line in output.splitlines():
            # check if the line doesn't contain 'lo' or 'vir' and doesn't start
            # with a non-digit character
            if not re.search(r'lo|vir|^[^0-9]', line):
                fields = line.split(':')
                if fields[1]:
                    interface = fields[1]
            # For this test case we need only one active interface
            if interface:
                break
        self.run_cmd("lsdevinfo -q name=%s" % interface)
        self.run_cmd("lsdevinfo -q name=%s" % self.disk_name)
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
        output = self.run_cmd_out("lsvio -e").strip()
        if not output:
            self.cancel("No virtual I/O devices found (lsvio -e returned no output)")
        interface = None
        for line in output.splitlines():
            fields = line.split()
            if len(fields) > 1:
                interface = fields[1]
                break
        file_path = os.path.join(self.workdir, 'file')
        process.run("echo %s > %s" %
                    (self.disk_name, file_path), ignore_status=True,
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

        Test Coverage:
        - Validates lparstat -x output matches LPAR security flavor
        - Validates lparstat -E output: %busy and %idle should be 0-100
        - Normalized %busy + %idle should equal frequency percentage
        - Checks physical processors consumed on different SMT levels
        - Validates resource group information (new feature):
          * resource_group_number from /proc/powerpc/lparcfg
          * resource_group_active_processors from /proc/powerpc/lparcfg
          * Ensures lparstat output includes resource group data

        Resource Group Context:
        Systems can now be partitioned into resource groups. By default all
        systems are part of the default resource group (ID=0). Once a resource
        group is created and resources allocated, those resources are removed
        from the default group. LPARs in a resource group can only use resources
        within that group. The maximum processors allocatable to an LPAR equals
        or is less than the resources in its resource group.

        References:
        - Kernel changes: https://lore.kernel.org/all/20250716104600.59102-1-srikar@linux.ibm.com/t/#u
        - powerpc-utils changes: https://groups.google.com/g/powerpc-utils-devel/c/8b2Ixk8vk2w
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
        '''Multiple tests are there for lparstat, to continue the execution
        of whole code we can capture the error message and use that for fail
        condition at the end of code.'''
        error_messages = []
        if value == security_flavor:
            self.log.info("Lpar security flavor is correct")
        else:
            error_messages.append("Lpar security flavor is incorrect")
        lists = self.params.get('lparstat_nlist',
                                default=['--nonexistingoption'])
        for list_item in lists:
            cmd = "lparstat %s" % list_item
            if not process.system(cmd, ignore_status=True, sudo=True):
                self.log.info("%s command passed" % cmd)
                error_messages.append("lparstat: Expected failure, %s command \
                                      executed successfully." % cmd)
        output = process.system_output("lparstat -E 1 1").decode("utf-8")
        parsed = False
        for line in output.splitlines():
            line = line.strip()
            try:
                parts = line.split()
                if len(parts) < 5:
                    self.log.warning(f"skipping malformed line: {line}")
                    continue
                actual_busy = float(parts[0])
                actual_idle = float(parts[1])
                freq_field = [p for p in parts if "GHz" in p]
                if not freq_field:
                    self.log.warning(f"no frequency filed found: {line}")
                    continue
                freq_percentile = float(
                    freq_field[0].split('[')[1].strip(']%'))
                float_vals = []
                for p in parts:
                    try:
                        float_vals.append(float(p))
                    except ValueError:
                        continue
                if len(float_vals) < 4:
                    self.log.warning(f"not enough numeric values: {line}")
                    continue
                normal_busy = float_vals[-2]
                normal_idle = float_vals[-1]
                normal = normal_busy + normal_idle
                actual_sum = actual_busy + actual_idle
                parsed = True
                self.log.info(
                    f"Parsed → actual: {actual_busy} + {actual_idle} = {actual_sum}, "
                    f"normalized: {normal_busy} + {normal_idle} = {normal}, "
                    f"freq={freq_percentile}")
                if abs(actual_sum - 100.0) <= 1.0:
                    self.log.info("Actual busy + idle ≈ 100% ✔")
                else:
                    error_messages.append(
                        f"Actual values invalid: sum={actual_sum}")
                if abs(normal - freq_percentile) <= 2.0:
                    self.log.info("Normalized values match frequency")
                else:
                    error_messages.append(
                        f"Mismatch: normalized={normal}, freq={freq_percentile}")
            except Exception as e:
                self.log.warning(f"Parsing error in line: {line} → {str(e)}")
                continue
        if not parsed:
            error_messages.append("Failed to parse valid lparstat -E output")

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
            error_messages.append("number of physical processors consumed \
                                  are not displaying correct")

        # Validate resource group information (new feature)
        self.log.info("====Validating Resource Group Information====")
        lparcfg_path = "/proc/powerpc/lparcfg"

        # Check if resource group information is available in lparcfg
        try:
            lparcfg_content = process.system_output(
                f"cat {lparcfg_path}", shell=True).decode("utf-8")

            # Extract resource group number
            rg_number_match = re.search(
                r'resource_group_number=(\d+)', lparcfg_content)
            rg_processors_match = re.search(
                r'resource_group_active_processors=(\d+)', lparcfg_content)

            if rg_number_match and rg_processors_match:
                rg_number = rg_number_match.group(1)
                rg_processors = rg_processors_match.group(1)

                self.log.info(f"Resource Group Number: {rg_number}")
                self.log.info(
                    f"Resource Group Active Processors: {rg_processors}")

                # Validate resource group number is non-negative
                if int(rg_number) >= 0:
                    self.log.info("Resource group number is valid (>= 0)")
                else:
                    error_messages.append(
                        f"Invalid resource group number: {rg_number}")

                # Validate resource group active processors is positive
                if int(rg_processors) > 0:
                    self.log.info(
                        f"Resource group active processors is valid: {rg_processors}")
                else:
                    error_messages.append(
                        f"Invalid resource group active processors: {rg_processors}")

                # Check if lparstat -i output includes resource group info
                lparstat_i_output = process.system_output(
                    "lparstat -i", shell=True).decode("utf-8")

                # Verify resource group information is present
                # in lparstat output
                if "Resource Group" in lparstat_i_output or \
                   "resource_group" in lparstat_i_output.lower():
                    self.log.info(
                        "lparstat -i correctly displays resource group info")

                    # Additional validation: check if values match
                    if rg_number in lparstat_i_output:
                        self.log.info(
                            f"Found resource group number {rg_number} in o/p")
                    else:
                        self.log.warning(
                            f"Resource group # {rg_number} not found in o/p")
                        error_messages.append(
                            f"Resource group # {rg_number} not found in o/p")
                else:
                    self.log.info(
                        "Resource group information not displayed in "
                        "lparstat -i (may require updated powerpc-utils)")
                    error_messages.append(
                        "Resource group information not displayed in "
                        "lparstat -i (may require updated powerpc-utils)")

                # Log resource group context
                if int(rg_number) == 0:
                    self.log.info(
                        "LPAR is in default resource group (ID=0)")
                else:
                    self.log.info(
                        f"LPAR is in non-default group (ID={rg_number})")
                    self.log.info(
                        f"Maximum allocatable procs limited to {rg_processors}")

            else:
                self.log.info(
                    "Resource group information not available in lparcfg "
                    "(kernel may not support this feature)")
                self.log.info(
                    "Skipping resource group validation - feature not present")

        except Exception as e:
            self.log.warning(
                f"Could not validate resource group information: {str(e)}")
            self.log.info(
                "Continuing test execution - resource group validation skipped")

        if len(error_messages) != 0:
            self.fail(error_messages)
        else:
            self.log.info("no failures in lparstat command")

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

    def test_ppc64_cpu_cores_present(self):
        """
        Verify ppc64_cpu --cores-present reports the total number of cores.

        The output must contain at least one digit and be parseable as a
        positive integer (e.g. "Number of cores present = 16").
        """
        self.log.info("===============Executing ppc64_cpu --cores-present"
                      " test===============")
        output = self.run_cmd_out("ppc64_cpu --cores-present")
        match = re.search(r'\d+', output)
        if not match:
            self.fail("--cores-present did not return a numeric value: "
                      "%s" % output)
        if int(match.group()) < 1:
            self.fail("--cores-present returned an invalid value (< 1): "
                      "%s" % output)

    def test_ppc64_cpu_cores_on(self):
        """
        Verify ppc64_cpu --cores-on (query), --cores-on=1 (set) and
        --cores-on=all (restore all cores).

        Steps:
        1. Query current cores-on count and validate it is numeric.
        2. Set cores-on=1 and confirm the reported count is 1.
        3. Restore all cores with --cores-on=all and confirm the count
           equals --cores-present.
        """
        self.log.info("===============Executing ppc64_cpu --cores-on"
                      " test===============")
        # Step 1 - query
        output = self.run_cmd_out("ppc64_cpu --cores-on")
        if not re.search(r'\d+', output):
            self.fail("--cores-on did not return a numeric value: %s" % output)

        # Step 2 - set to 1
        self.run_cmd("ppc64_cpu --cores-on=1")
        output = self.run_cmd_out("ppc64_cpu --cores-on")
        match = re.search(r'\d+', output)
        if not match or int(match.group()) != 1:
            self.fail("Expected cores-on=1, got: %s" % output)

        # Step 3 - restore all
        self.run_cmd("ppc64_cpu --cores-on=all")
        output_on = self.run_cmd_out("ppc64_cpu --cores-on")
        output_present = self.run_cmd_out("ppc64_cpu --cores-present")
        m_on = re.search(r'\d+', output_on)
        m_present = re.search(r'\d+', output_present)
        if m_on and m_present:
            if int(m_on.group()) != int(m_present.group()):
                self.fail("After --cores-on=all, cores-on (%s) != "
                          "cores-present (%s)" % (m_on.group(),
                                                  m_present.group()))
        self.error_check()

    def test_ppc64_cpu_online_offline_cores(self):
        """
        Verify ppc64_cpu --offline-cores=X and --online-cores=X by
        offlining and onlining CPU core index 0.

        --offline-cores and --online-cores without an argument are write
        commands that require a core-index; online/offline counts are
        therefore derived from --cores-on and --cores-present.

        Steps:
        1. Ensure all cores are online; record baseline cores-on count.
        2. Offline core index 0 with --offline-cores=0 and confirm
           cores-on decreased by 1.
        3. Online core index 0 with --online-cores=0 and confirm
           cores-on is restored to baseline.
        """
        self.log.info("===============Executing ppc64_cpu online/offline"
                      " cores test===============")
        # Ensure all cores are online before starting.
        process.run("ppc64_cpu --cores-on=all", ignore_status=True,
                    sudo=True, shell=True)

        # Derive online baseline from --cores-on.
        online_out = self.run_cmd_out("ppc64_cpu --cores-on")
        m_online = re.search(r'\d+', online_out)
        if not m_online:
            self.cancel("Could not determine baseline online core count "
                        "from --cores-on: %s" % online_out)
        online_base = int(m_online.group())

        # Offline core index 0.
        self.run_cmd("ppc64_cpu --offline-cores=0")
        online_after_off = re.search(
            r'\d+', self.run_cmd_out("ppc64_cpu --cores-on"))
        if online_after_off:
            online_after_off = int(online_after_off.group())
                          % online_after_off)
            if online_after_off != online_base - 1:
                self.fail("Expected cores-on=%d after offline, got %d"
                          % (online_base - 1, online_after_off))

        # Online core index 0.
        self.run_cmd("ppc64_cpu --online-cores=0")
        online_restored = re.search(
            r'\d+', self.run_cmd_out("ppc64_cpu --cores-on"))
        if online_restored:
            online_restored = int(online_restored.group())
            if online_restored != online_base:
                self.fail("Expected cores-on=%d after online, got %d"
                          % (online_base, online_restored))
        # Restore all cores regardless.
        process.run("ppc64_cpu --cores-on=all", ignore_status=True,
                    sudo=True, shell=True)
        self.error_check()

    def test_ppc64_cpu_dscr(self):
        """
        Verify ppc64_cpu --dscr (query), --dscr=1 (set) and --dscr=0 (reset).

        The initial DSCR value may be any non-negative integer (e.g. 23).
        After setting to 1 the tool must report 1; after setting to 0 it
        must report 0.  The original value is restored at the end.
        """
        self.log.info("===============Executing ppc64_cpu --dscr"
                      " test===============")
        # Query - value must be numeric.
        output = self.run_cmd_out("ppc64_cpu --dscr")
        initial_match = re.search(r'\d+', output)
        if not initial_match:
            self.fail("--dscr did not return a numeric value: %s" % output)
        initial_dscr = int(initial_match.group())

        # Set DSCR=1 and verify.
        self.run_cmd("ppc64_cpu --dscr=1")
        output = self.run_cmd_out("ppc64_cpu --dscr")
        match = re.search(r'\d+', output)
        if not match or int(match.group()) != 1:
            self.fail("Expected DSCR=1, got: %s" % output)

        # Set DSCR=0 and verify.
        self.run_cmd("ppc64_cpu --dscr=0")
        output = self.run_cmd_out("ppc64_cpu --dscr")
        match = re.search(r'\d+', output)
        if not match:
            self.fail("--dscr returned no numeric value after --dscr=0: "
                      "%s" % output)
        if int(match.group()) != 0:
            self.fail("Expected DSCR=0, got: %s" % output)

        # Restore original DSCR value.
        process.run("ppc64_cpu --dscr=%d" % initial_dscr,
                    ignore_status=True, sudo=True, shell=True)
        self.error_check()

    def test_ppc64_cpu_smt_snooze_delay(self):
        """
        Verify ppc64_cpu --smt-snooze-delay (query) and set operations.

        If the machine does not support --smt-snooze-delay the command
        prints a usage/error message; the test is cancelled in that case.

        Steps (when supported):
        1. Query current value and confirm it is numeric.
        2. Set to 200 and verify.
        3. Set to 100 and verify.
        4. Restore the original value.
        """
        self.log.info("===============Executing ppc64_cpu --smt-snooze-delay"
                      " test===============")
        output = self.run_cmd_out("ppc64_cpu --smt-snooze-delay")

        # If the output is a usage/help block the feature is unsupported.
        if "Usage:" in output or "not supported" in output.lower() \
                or not re.search(r'\d+', output):
            self.cancel("--smt-snooze-delay is not supported on this "
                        "machine: %s" % output)

        initial_delay = int(re.search(r'\d+', output).group())

        for value in [200, 100]:
            self.run_cmd("ppc64_cpu --smt-snooze-delay=%d" % value)
            output = self.run_cmd_out("ppc64_cpu --smt-snooze-delay")
            match = re.search(r'\d+', output)
            if not match or int(match.group()) != value:
                self.fail("Expected smt-snooze-delay=%d, got: %s"
                          % (value, output))

        # Restore original value.
        process.run("ppc64_cpu --smt-snooze-delay=%d" % initial_delay,
                    ignore_status=True, sudo=True, shell=True)
        self.error_check()

    def test_ppc64_cpu_run_mode(self):
        """
        Verify ppc64_cpu --run-mode (query) and --run-mode=1 (set).

        If the machine reports "does not support diagnostic run mode" the
        test is cancelled (the feature is hardware-dependent).
        """
        self.log.info("===============Executing ppc64_cpu --run-mode"
                      " test===============")
        output = self.run_cmd_out("ppc64_cpu --run-mode")

        if not output or "not support" in output.lower():
            self.cancel("--run-mode is not supported on this machine: "
                        "%s" % output)

        self.run_cmd("ppc64_cpu --run-mode=1")
        output = self.run_cmd_out("ppc64_cpu --run-mode")
        self.error_check()

    def test_ppc64_cpu_frequency(self):
        """
        Verify ppc64_cpu --frequency (instant) and --frequency -t <N>
        (timed average).

        The output contains lines such as "avg  :  3.247 GHz", so the
        check looks for a GHz/MHz pattern rather than a bare integer.
        """
        self.log.info("===============Executing ppc64_cpu --frequency"
                      " test===============")
        output = self.run_cmd_out("ppc64_cpu --frequency")
        if not re.search(r'\d+\.\d+\s*GHz|\d+\s*MHz', output,
                         re.IGNORECASE):
            self.fail("--frequency output did not contain a frequency "
                      "value (GHz/MHz): %s" % output)

        timeout = self.params.get('frequency_timeout', default=5)
        output = self.run_cmd_out(
            "ppc64_cpu --frequency -t %d" % timeout)
        if not re.search(r'\d+\.\d+\s*GHz|\d+\s*MHz', output,
                         re.IGNORECASE):
            self.fail("--frequency -t %d output did not contain a "
                      "frequency value (GHz/MHz): %s" % (timeout, output))
        self.error_check()

    def test_ppc64_cpu_subcores_per_core(self):
        """
        Verify ppc64_cpu --subcores-per-core.

        If the machine is not subcore-capable the command exits non-zero
        with "Machine is not subcore capable"; the test is cancelled in
        that case.  On capable machines the reported value must be numeric.
        """
        self.log.info("===============Executing ppc64_cpu --subcores-per-core"
                      " test===============")
        result = process.run("ppc64_cpu --subcores-per-core",
                             ignore_status=True, sudo=True, shell=True)
        output = (result.stdout + result.stderr).decode("utf-8").strip()

        if "not subcore capable" in output.lower():
            self.cancel("--subcores-per-core: machine is not subcore "
                        "capable — skipping")

        if result.exit_status != 0:
            self.fail("--subcores-per-core failed unexpectedly: %s" % output)

        if not re.search(r'\d+', output):
            self.fail("--subcores-per-core did not return a numeric value: "
                      "%s" % output)

    def test_ppc64_cpu_threads_per_core(self):
        """
        Verify ppc64_cpu --threads-per-core returns a positive integer.
        """
        self.log.info("===============Executing ppc64_cpu --threads-per-core"
                      " test===============")
        output = self.run_cmd_out("ppc64_cpu --threads-per-core")
        match = re.search(r'\d+', output)
        if not match:
            self.fail("--threads-per-core did not return a numeric value: "
                      "%s" % output)
        if int(match.group()) < 1:
            self.fail("--threads-per-core returned an invalid value "
                      "(< 1): %s" % output)

    def test_ppc64_cpu_info(self):
        """
        Verify ppc64_cpu --info prints a comprehensive CPU information
        summary containing per-core thread layout lines such as
        "Core   0:    0*    1* ...".
        """
        self.log.info("===============Executing ppc64_cpu --info"
                      " test===============")
        output = self.run_cmd_out("ppc64_cpu --info")
        if not output:
            self.fail("--info returned empty output")
        if not re.search(r'Core\s+\d+', output, re.IGNORECASE):
            self.fail("--info output does not contain expected 'Core N:' "
                      "layout lines: %s" % output)

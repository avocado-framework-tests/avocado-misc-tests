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
# Copyright: 2017 IBM
# Author: Naresh Bannoth<nbannoth@in.ibm.com>
# this script run IO stress on block devices for give time.

"""
HTX Test
"""

import os
import time
import shutil
import re

from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import build
from avocado.utils import disk
from avocado.utils import multipath
from avocado.utils import process, archive
from avocado.utils import distro


class HtxTest(Test):

    """
    HTX [Hardware Test eXecutive] is a test tool suite. The goal of HTX is to
    stress test the system by exercising all hardware components concurrently
    in order to uncover any hardware design flaws and hardware hardware or
    hardware-software interaction issues.
    :see:https://github.com/open-power/HTX.git
    :param block_devices: names of block_devices on which you want to run HTX
    :param mdt_file: mdt file used to trigger HTX
    :param time_limit: how much time(hours) you want to run this stress
    :param all: if all disks in selected mdt needs to be used for HTX run
    """

    def setUp(self):
        """
        Setup
        """
        if "ppc64" not in distro.detect().arch:
            self.cancel("Platform does not supports")

        self.mdt_file = self.params.get("mdt_file", default="mdt.hd")
        self.time_limit = int(self.params.get("time_limit", default=1)) * 60
        self.block_devices = self.params.get("htx_disks", default=None)
        self.all = self.params.get("all", default=False)
        self.run_type = self.params.get("run_type", default="")

        self.detected_distro = distro.detect()
        self.dist_name = self.detected_distro.name
        self.dist_version = self.detected_distro.version
        if not self.all and self.block_devices is None:
            self.cancel("Needs the block devices to run the HTX")
        if self.all:
            self.block_device = ""
        else:
            self.block_device = []
            for dev in self.block_devices.split():
                dev_path = disk.get_absolute_disk_path(dev)
                dev_base = os.path.basename(os.path.realpath(dev_path))
                if 'dm' in dev_base:
                    dev_base = multipath.get_mpath_from_dm(dev_base)
                self.block_device.append(dev_base)
            self.block_device = " ".join(self.block_device)

    def setup_htx(self):
        """
        Builds HTX
        """
        packages = ["git", "gcc", "make"]
        if self.dist_name in ["centos", "fedora", "rhel", "redhat"]:
            packages.extend(["gcc-c++", "ncurses-devel", "tar"])
        elif self.dist_name == "Ubuntu":
            packages.extend(["libncurses5", "g++", "ncurses-dev",
                             "libncurses-dev", "tar"])
        elif self.dist_name == "SuSE":
            packages.extend(["libncurses5", "gcc-c++", "ncurses-devel", "tar"])
        else:
            self.cancel(f"Test not supported in {self.detected_distro}")

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(f"Can not install {pkg}")

        if self.run_type == "git":
            url = "https://github.com/open-power/HTX/archive/master.zip"
            tarball = self.fetch_asset("htx.zip", locations=[url], expire="7d")
            archive.extract(tarball, self.teststmpdir)
            htx_path = os.path.join(self.teststmpdir, "HTX-master")
            os.chdir(htx_path)

            exercisers = ["hxecapi_afu_dir", "hxedapl", "hxecapi", "hxeocapi"]
            for exerciser in exercisers:
                process.run(
                    f"sed -i 's/{exerciser,}//g' {htx_path}/bin/Makefile")
            build.make(htx_path, extra_args="all")
            build.make(htx_path, extra_args="tar")
            process.run("tar --touch -xvzf htx_package.tar.gz")
            os.chdir("htx_package")
            if process.system("./installer.sh -f"):
                self.fail("Installation of htx fails:please refer job.log")
        else:
            if self.dist_name.lower() == "suse":
                self.dist_name = "sles"
            rpm_check = f"htx{self.dist_name}{self.dist_version}"
            skip_install = False
            ins_htx = process.system_output(
                "rpm -qa | grep htx", shell=True, ignore_status=True).decode()

            if ins_htx:
                if not smm.check_installed(rpm_check):
                    self.log.info("Clearing existing HTX rpm")
                    process.system(f"rpm -e {ins_htx}",
                                   shell=True, ignore_status=True)
                    if os.path.exists("/usr/lpp/htx"):
                        shutil.rmtree("/usr/lpp/htx")
                else:
                    self.log.info("Using existing HTX")
                    skip_install = True
            if not skip_install:
                self.rpm_link = self.params.get("htx_rpm_link", default=None)
                if self.rpm_link:
                    self.install_htx_rpm()

    def install_htx_rpm(self):
        """
        Search for the latest htx-version for the intended distro and
        install the same.
        """
        distro_pattern = f"{self.dist_name}{self.dist_version}"
        temp_string = process.getoutput(
            f"curl --silent {self.rpm_link}",
            verbose=False, shell=True, ignore_status=True)
        matching_htx_versions = re.findall(
            r"(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*", str(temp_string))
        distro_specific_htx_versions = [
            htx_rpm for htx_rpm in matching_htx_versions
            if distro_pattern in htx_rpm]
        distro_specific_htx_versions.sort(reverse=True)
        self.latest_htx_rpm = distro_specific_htx_versions[0]

        if process.system(f"rpm -ivh --nodeps {self.rpm_link}{self.latest_htx_rpm} --force",
                          shell=True, ignore_status=True):
            self.cancel("Installation of htx rpm failed")

    def test_start(self):
        """
        Execute 'HTX' with appropriate parameters.
        """
        self.setup_htx()
        self.log.info("Stopping existing HXE process")
        hxe_pid = process.getoutput("pgrep -f hxe")
        if hxe_pid:
            self.log.info("HXE is already running with PID: %s. Killing it.", hxe_pid)
            process.run("hcl -shutdown", ignore_status=True)
            time.sleep(20)
        self.log.info("Creating the HTX mdt files")
        process.run("htxcmdline -createmdt")

        if not os.path.exists(f"/usr/lpp/htx/mdt/{self.mdt_file}"):
            self.fail(f"MDT file {self.mdt_file} not found")

        self.log.info("selecting the mdt file ")
        cmd = f"htxcmdline -select -mdt {self.mdt_file}"
        process.system(cmd, ignore_status=True)

        if not self.all:
            if self.is_block_device_in_mdt() is False:
                self.fail(f"Block devices {self.block_device} are not available"
                          f"in {self.mdt_file}")

        self.suspend_all_block_device()

        self.log.info(f"Activating the {self.block_device}")
        cmd = f"htxcmdline -activate {self.block_device} -mdt {self.mdt_file}"
        process.system(cmd, ignore_status=True)
        if not self.all:
            if self.is_block_device_active() is False:
                self.fail("Block devices failed to activate")

        self.log.info(f"Running the HTX on {self.block_device}")
        cmd = f"htxcmdline -run -mdt {self.mdt_file}"
        process.system(cmd, ignore_status=True)

    def test_check(self):
        """
        Checks if HTX is running, and if no errors.
        """
        for _ in range(0, self.time_limit, 60):
            self.log.info("HTX Error logs")
            process.run("htxcmdline -geterrlog")
            if os.stat("/tmp/htxerr").st_size != 0:
                self.fail("check errorlogs for exact error and failure")
            self.log.info("status of block devices after every 60 sec")
            cmd = f"htxcmdline -query {self.block_device} -mdt {self.mdt_file}"
            process.system(cmd, ignore_status=True)
            time.sleep(60)

    def is_block_device_in_mdt(self):
        """
        verifies the presence of given block devices in selected mdt file
        """
        self.log.info(
            f"checking if the given block_devices are present in {self.mdt_file}")
        cmd = f"htxcmdline -query -mdt {self.mdt_file}"
        output = process.system_output(cmd).decode("utf-8")
        device = []
        for dev in self.block_device.split(" "):
            if dev not in output:
                device.append(dev)
        if device:
            self.log.info(
                f"block_devices {device} are not avalable in {self.mdt_file} ")
        self.log.info(
            f"BLOCK DEVICES {self.block_device} ARE AVAILABLE {self.mdt_file}")
        return True

    def suspend_all_block_device(self):
        """
        Suspend the Block devices, if active.
        """
        self.log.info("suspending block_devices if any running")
        cmd = f"htxcmdline -suspend all  -mdt {self.mdt_file}"
        process.system(cmd, ignore_status=True)

    def is_block_device_active(self):
        """
        Verifies whether the block devices are active or not
        """
        self.log.info("checking whether all block_devices are active ot not")
        cmd = f"htxcmdline -query {self.block_device} -mdt {self.mdt_file}"
        output = process.system_output(cmd).decode("utf-8").split("\n")
        device_list = self.block_device.split(" ")
        active_devices = []
        for line in output:
            for dev in device_list:
                if dev in line and "ACTIVE" in line:
                    active_devices.append(dev)
        non_active_device = list(set(device_list) - set(active_devices))
        if non_active_device:
            return False
        self.log.info(f"BLOCK DEVICES {self.block_device} ARE ACTIVE")
        return True

    def test_stop(self):
        """
        Shutdown the mdt file and the htx daemon and set SMT to original value
        """
        self.stop_htx()

    def stop_htx(self):
        """
        Stop the HTX Run
        """
        if self.is_block_device_active() is True:
            self.log.info("suspending active block_devices")
            self.suspend_all_block_device()
            self.log.info(f"shutting down the {self.mdt_file} ")
            cmd = f"htxcmdline -shutdown -mdt {self.mdt_file}"
            process.system(cmd, timeout=120, ignore_status=True)

        cmd = "/usr/lpp/htx/etc/scripts/htx.d status"
        daemon_state = process.system_output(cmd)
        if daemon_state.decode("utf-8").split(" ")[-1] == "running":
            process.system("/usr/lpp/htx/etc/scripts/htxd_shutdown")

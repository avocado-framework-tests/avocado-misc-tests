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

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Hwinfo(Test):


    is_fail = 0

    def run_cmd(self, cmd):
        print ("executing ============== %s =================" % cmd)
        cmd_result = process.run(cmd, ignore_status=True, sudo=True)
        if cmd_result.exit_status != 0:
            self.is_fail += 1
        return

    def setUp(self):
        dist = distro.detect()
        architecture = os.uname()[4]
        if "ppc" not in architecture:
            self.skip("supported only on Power platform")
        if dist.name == 'redhat':
            self.skip('Hwinfo not supported on RHEL')
        sm = SoftwareManager()
        if not sm.check_installed("hwinfo") and not sm.install("hwinfo"):
            self.error("Fail to install hwinfo required for this test.")

    def test(self):
        self.log.info("===============Executing hwinfo tool test===============")
        self.run_cmd("hwinfo --all")
        self.run_cmd("hwinfo --arch")
        self.run_cmd("hwinfo --bios")
        self.run_cmd("hwinfo --block")
        self.run_cmd("hwinfo --bluetooth")
        self.run_cmd("hwinfo --braille")
        self.run_cmd("hwinfo --bridge")
        self.run_cmd("hwinfo --camera")
        self.run_cmd("hwinfo --cdrom")
        self.run_cmd("hwinfo --chipcard")
        self.run_cmd("hwinfo --cpu")
        self.run_cmd("hwinfo --disk")
        self.run_cmd("hwinfo --dsl")
        self.run_cmd("hwinfo --dvb")
        self.run_cmd("hwinfo --fingerprint")
        self.run_cmd("hwinfo --floppy")
        self.run_cmd("hwinfo --framebuffer")
        self.run_cmd("hwinfo --gfxcard")
        self.run_cmd("hwinfo --hub")
        self.run_cmd("hwinfo --ide")
        self.run_cmd("hwinfo --isapnp")
        self.run_cmd("hwinfo --isdn")
        self.run_cmd("hwinfo --joystick")
        self.run_cmd("hwinfo --keyboard")
        self.run_cmd("hwinfo --memory")
        self.run_cmd("hwinfo --modem")
        self.run_cmd("hwinfo --monitor")
        self.run_cmd("hwinfo --mouse")
        self.run_cmd("hwinfo --netcard")
        self.run_cmd("hwinfo --network")
        self.run_cmd("hwinfo --partition")
        self.run_cmd("hwinfo --pci")
        self.run_cmd("hwinfo --pcmcia")
        self.run_cmd("hwinfo --pcmcia-ctrl")
        self.run_cmd("hwinfo --pppoe")
        self.run_cmd("hwinfo --printer")
        self.run_cmd("hwinfo --redasd")
        self.run_cmd("hwinfo --reallyall")
        self.run_cmd("hwinfo --scanner")
        self.run_cmd("hwinfo --scsi")
        self.run_cmd("hwinfo --smp")
        self.run_cmd("hwinfo --sound")
        self.run_cmd("hwinfo --storage-ctrl")
        self.run_cmd("hwinfo --sys")
        self.run_cmd("hwinfo --tape")
        self.run_cmd("hwinfo --tv")
        self.run_cmd("hwinfo --uml")
        self.run_cmd("hwinfo --usb")
        self.run_cmd("hwinfo --usb-ctrl")
        self.run_cmd("hwinfo --vbe")
        self.run_cmd("hwinfo --wlan")
        self.run_cmd("hwinfo --xen")
        self.run_cmd("hwinfo --zip")
        self.run_cmd("hwinfo --short")
        self.run_cmd("hwinfo --listmd")
        disk_name = process.system_output("df -h | egrep '(s|v)d[a-z][1-8]' | "
                                          "tail -1 | cut -d' ' -f1",
                                          shell=True).strip("12345")
        self.run_cmd("hwinfo --disk --only %s" % disk_name)
        Unique_Id = process.system_output("hwinfo --disk --only /dev/sdb | "
                                          "grep 'Unique' | head -1 | "
                                          "cut -d':' -f2", shell=True)
        self.run_cmd("hwinfo --disk --save-config %s" % Unique_Id)
        self.run_cmd("hwinfo --disk --show-config %s" % Unique_Id)
        self.run_cmd("hwinfo --verbose --map")
        self.run_cmd("hwinfo --all --log FILE")
        if (not os.path.exists('./FILE')) or (os.stat("FILE").st_size == 0):
            print "--log option failed"
            self.is_fail += 1
        self.run_cmd("hwinfo --dump-db 0")
        self.run_cmd("hwinfo --dump-db 1")
        self.run_cmd("hwinfo --version")
        self.run_cmd("hwinfo --help")
        self.run_cmd("hwinfo --debug 0 --disk --log=-")
        self.run_cmd("hwinfo --short --block")
        self.run_cmd("hwinfo --disk --save-config=all")
        if "failed" in process.system_output("hwinfo --disk --save-config=all | "
                                             "grep failed | tail -1", shell=True):
            self.is_fail += 1
            print "--save-config option failed"
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in hwinfo tool verification" % self.is_fail)


if __name__ == "__main__":
    main()

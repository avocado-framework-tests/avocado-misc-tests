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
# Copyright: 2018 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
NVM Express over Fabrics defines a common architecture that supports a
range of storage networking fabrics for NVMe block storage protocol over
a storage networking fabric.
"""

import os
import json
import copy
import time
from avocado import Test
from avocado.utils import process, linux_modules, genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session
from avocado.utils.process import CmdError
import yaml


class NVMfTest(Test):
    """
    NVM-Express over Fabrics using nvme-cli.
    """

    def setUp(self):
        """
        Sets up NVMf configuration
        """
        self.nss = self.params.get('namespaces', default='')
        self.peer_ips = self.params.get('peer_ips', default='')
        if not self.nss or not self.peer_ips:
            self.cancel("No inputs provided")
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", default=None)
        self.nss = self.nss.split(' ')
        self.peer_ips = self.peer_ips.split(' ')
        self.ids = range(1, len(self.peer_ips) + 1)
        if len(self.nss) != len(self.peer_ips):
            self.cancel("Count of namespace and peer ips mismatch")
        smm = SoftwareManager()
        if not smm.check_installed("nvme-cli") and not \
                smm.install("nvme-cli"):
            self.cancel('nvme-cli is needed for the test to be run')
        try:
            if not linux_modules.module_is_loaded("nvme-rdma"):
                linux_modules.load_module("nvme-rdma")
        except CmdError:
            self.cancel("nvme-rdma module not loadable")
        self.cfg_tmpl = self.get_data("nvmf_template.cfg")
        dirname = os.path.dirname(os.path.abspath(self.cfg_tmpl))
        self.cfg_file = os.path.join(dirname, "nvmf.cfg")
        self.nvmf_discovery_file = "/etc/nvme/discovery.conf"

    def create_cfg_file(self):
        """
        Creates the config file for nvmetcli to use in the target
        """
        with open(self.cfg_tmpl, "r") as cfg_fp:
            cfg = yaml.safe_load(cfg_fp)

        subsys_template = list(cfg["subsystems"])
        ports_template = list(cfg["ports"])
        del cfg["subsystems"][0]
        del cfg["ports"][0]
        for i in range(len(self.ids)):
            cfg["subsystems"].append(copy.deepcopy(subsys_template[0]))
            cfg["ports"].append(copy.deepcopy(ports_template[0]))

            cfg_namespace = cfg["subsystems"][i]["namespaces"][0]
            cfg_namespace["device"]["nguid"] = str(i + 1).zfill(32)
            cfg_namespace["device"]["path"] = self.nss[i]
            cfg_namespace["nsid"] = str(i + 1)

            cfg["subsystems"][i]["nqn"] = "mysubsys%s" % str(i + 1)
            cfg["ports"][i]["addr"]["traddr"] = self.peer_ips[i]
            cfg["ports"][i]["subsystems"][0] = "mysubsys%s" % str(i + 1)
            cfg["ports"][i]["portid"] = str(i + 1)

        with open(self.cfg_file, "w") as cfg_fp:
            json.dump(cfg, cfg_fp, indent=2)

    @staticmethod
    def nvme_devs_count():
        """
        Returns count of nvme devices in the system
        """
        cmd = "nvme list"
        output = process.system_output(cmd, shell=True, ignore_status=True)
        count = max(len(output.splitlines()) - 2, 0)
        return count

    def test_targetconfig(self):
        """
        Configures the peer NVMf.
        """
        self.session = Session(self.peer_ips[0], user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.fail("failed connecting to peer")
        self.create_cfg_file()
        destination = "%s:/tmp/" % self.peer_ips[0]
        output = self.session.copy_files(self.cfg_file, destination)
        if not output:
            self.cancel("unable to copy the NVMf cfg file into peer machine")
        for mdl in ["nvmet", "nvmet-rdma"]:
            cmd = "modprobe %s" % mdl
            output = self.session.cmd(cmd)
            if output.exit_status:
                self.cancel("%s is not loadable on the peer" % mdl)
        msg = "which nvmetcli"
        output = self.session.cmd(msg)
        if output.exit_status:
            self.cancel("nvmetcli is not installed on the peer")
        msg = "nvmetcli restore /tmp/nvmf.cfg"
        output = self.session.cmd(msg)
        if output.exit_status:
            self.fail("nvmetcli setup config fails on peer")

    def test_nvmfdiscover(self):
        """
        Discovers NVMf subsystems on the initiator
        """
        for i in range(len(self.ids)):
            cmd = "nvme discover -t rdma -a %s -s 4420 -q mysubsys%s" % (
                self.peer_ips[i], str(i + 1))
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("Discover of mysubsys%s fails" % str(i + 1))

    def test_nvmfconnect(self):
        """
        Connects to NVMf subsystems on the initiator
        """
        pre_count = self.nvme_devs_count()
        for i in range(len(self.ids)):
            cmd = "nvme connect -t rdma -n mysubsys%s -a %s -s 4420" % (
                str(i + 1), self.peer_ips[i])
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("Connect to mysubsys%s fails" % str(i + 1))
            # Time needed to populate the device in nvme list command
            time.sleep(1)
        if (self.nvme_devs_count() - pre_count) != len(self.ids):
            self.fail("%d new nvme devices not added" % len(self.ids))

    def test_nvmfdisconnect(self):
        """
        Disconnects to NVMf subsystems on the initiator
        """
        pre_count = self.nvme_devs_count()
        for i in range(len(self.ids)):
            cmd = "nvme disconnect -n mysubsys%s" % str(i + 1)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("Disconnect to mysubsys%s fails" % str(i + 1))
        if (pre_count - self.nvme_devs_count()) != len(self.ids):
            self.fail("%d new nvme devices not removed" % len(self.ids))

    def test_nvmfconnectcfg(self):
        """
        Connects to allNVMf subsystems in /etc/nvme/discovery.conf
        """
        if not os.path.exists(os.path.dirname(self.nvmf_discovery_file)):
            os.makedirs(os.path.dirname(self.nvmf_discovery_file))
        msg = []
        for i in range(len(self.ids)):
            msg.append("-t rdma -a %s -s 4420 -q mysubsys%s" %
                       (self.peer_ips[i], str(i + 1)))
        genio.write_file(self.nvmf_discovery_file, "\n".join(msg))
        process.system("cat %s" % self.nvmf_discovery_file)
        pre_count = self.nvme_devs_count()
        cmd = "nvme connect-all"
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("connect-all fails")
        if (self.nvme_devs_count() - pre_count) != len(self.ids):
            self.fail("%d new nvme devices not added" % len(self.ids))

    def test_nvmfdisconnectcfg(self):
        """
        Disconnects to NVMf subsystems on the initiator
        """
        pre_count = self.nvme_devs_count()
        for i in range(len(self.ids)):
            cmd = "nvme disconnect -n mysubsys%s" % str(i + 1)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("Disconnect to mysubsys%s fails" % str(i + 1))
        genio.write_file(self.nvmf_discovery_file, "")
        if (pre_count - self.nvme_devs_count()) != len(self.ids):
            self.fail("%d new nvme devices not removed" % len(self.ids))

    def test_cleartargetconfig(self):
        """
        Clears the peer NVMf
        """
        self.session = Session(self.peer_ips[0], user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.fail("failed connecting to peer")
        msg = "nvmetcli clear"
        output = self.session.cmd(msg)
        if output.exit_status:
            self.fail("nvmetcli clear config remove on peer")
        msg = "rm -rf /tmp/nvmf.cfg"
        output = self.session.cmd(msg)
        if output.exit_status:
            self.log.warn("removing config file on peer failed")

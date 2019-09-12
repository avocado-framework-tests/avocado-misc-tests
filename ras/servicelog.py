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
# Authors: Rafael Camarda Silva Folco (rfolco@br.ibm.com) (Original author)
#          Lucas Meneghel Rodrigues (lucasmr@br.ibm.com)
#          Hariharan T.S. <hari@linux.vnet.ibm.com> (ported to avocado)
#          Pavithra <pavrampu@linux.vnet.ibm.com> (Added test_servicelog)

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.service import ServiceManager
from avocado.utils.software_manager import SoftwareManager


class servicelog(Test):

    is_fail = 0
    events_path = os.path.join(
        os.path.dirname(__file__), "servicelog.py.data", "rtas_events")

    def run_cmd(self, cmd):
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.log.info("%s command failed", cmd)
        return

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def setUp(self):
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.cancel("servicelog: is not supported on the PowerNV platform")
        smm = SoftwareManager()
        for package in ("servicelog", "ppc64-diag"):
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Fail to install %s required for this"
                            " test." % package)

    def test_servicelog(self):
        """
        The test checks servicelog commands.
        """
        self.log.info("1 - Cleaning servicelog...")
        self.run_cmd("servicelog_manage --truncate notify --force")
        rtas_events = [
            "v6_fru_replacement", "v6_memory_info", "v6_power_error",
            "v6_power_error2", "v6_fw_predictive_error", "v3_fan_failure",
            "v6_dump_notification", "v6_platform_error2", "v6_eeh_info",
            "v6_cpu_guard", "v6_platform_info", "v6_surv_error"]
        for event in rtas_events:
            self.log.info("Starting test scenario for %s" % event)
            self.log.info("2 - Injecting event %s" % event)
            self.run_cmd("rtas_errd -d -f %s/%s" % (self.events_path, event))
            self.log.info(
                "3 - Checking if service log does return ppc64_rtas events")
            self.run_cmd("servicelog --type=ppc64_rtas")
            self.log.info(
                "4 - Checking if the event was dumped to /var/log/platform")
            self.run_cmd("cat /var/log/platform")
        service_log_cmds = ["--help", "--version", "--query='id=1'", "--id=1",
                            "--query='severity>=$WARNING AND closed=0'", "--serviceable=yes",
                            "--serviceable=no", "--serviceable=all", "--query='serviceable=1 AND closed=0'",
                            "--repair_action=yes", "--repair_action=no", "--repair_action=all",
                            "--verbose --repair_action=no", "--event_repaired=no", "--severity=4"]
        for cmd in service_log_cmds:
            self.run_cmd("servicelog %s" % cmd)
        self.run_cmd("servicelog_manage --truncate notify --force")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in servicelog"
                      "verification" % self.is_fail)

    def test_servicelog_notify(self):
        """
        The test checks servicelog_notify command of servicelog.
        """
        event = "v6_power_error"
        # Stopping rtas_errd daemon so we can work
        Manageservice = ServiceManager()
        Manageservice.stop("rtas_errd")
        self.log.info("===============1. Creating notification tool ===="
                      "===========")
        notify_script = self.get_data("notify_script.sh")
        cmd = "chmod 777 %s" % notify_script
        process.run(cmd, ignore_status=True, sudo=True, shell=True)
        self.log.info("=======2 - Adding notification tool to servicelog ="
                      "======")
        self.run_cmd("servicelog_notify --add --command=%s --type=all "
                     "--repair_action=all --serviceable=all" % notify_script)
        self.log.info("===========3 - Injecting serviceable event ==="
                      "======")
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s/%s" %
                     (self.events_path, event))
        self.log.info("========4 - Checking registered notification tools =="
                      "======")
        self.run_cmd("servicelog_notify --list")
        self.log.info("=====5 - Check for notify_script.sh registered "
                      "successfully  =======")
        self.run_cmd("servicelog_notify --list | grep notify_script")
        ids = self.run_cmd_out("servicelog_notify --list --command=%s | "
                               "grep \"Servicelog ID:\" | cut -d\":\" -f2 | sed 's/^ *//'" %
                               notify_script)
        self.log.info("=====6 - Checking if servicelog_notify --list, "
                      "lists the command just added  =======")
        for id in ids:
            if id:
                self.run_cmd("servicelog_notify --list --id=%s" % id)
        self.log.info("=====7 - Checking if servicelog_notify --query, lists "
                      "the command just added =======")
        self.run_cmd("servicelog_notify --query --command=%s" % notify_script)
        self.log.info("=====8 - Checking servicelog_notify --remove =======")
        for id in ids:
            if id:
                self.run_cmd("servicelog_notify --remove --id=%s" % id)
        self.log.info("=====9 -  Cleaning events from the servicelog "
                      "database =======")
        self.run_cmd("servicelog_manage --truncate notify --force")
        self.log.info("=====10 - Checking if the notification tools were "
                      "cleared out =======")
        process.run("servicelog_notify --list", ignore_status=True)
        # Start the service stopped earlier
        Manageservice.start("rtas_errd")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in servicelog_notify "
                      "verification" % self.is_fail)

    def test_servicelog_manage(self):
        """
        The test checks servicelog_manage command of servicelog.
        """
        self.is_fail = 0
        event = "v6_fru_replacement"
        tmp_dir = "/var/tmp/ras/"
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)
        os.path.join(tmp_dir, "notify_script.sh")

        # Stopping rtas_errd daemon so we can work
        Manageservice = ServiceManager()
        Manageservice.stop("rtas_errd")
        self.log.info("=====0 -  Cleaning events from the servicelog "
                      "database =======")
        self.run_cmd("servicelog_manage --truncate events --force")
        self.run_cmd("rm -f /var/log/platform")
        self.run_cmd("rm -f /var/spool/mail/root")
        self.log.info("===========1 - Injecting serviceable event ==="
                      "======")
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s/%s" %
                     (self.events_path, event))
        self.log.info("===========2 - Checking if the event shows up"
                      " on servicelog_manage =========")
        self.run_cmd("servicelog --dump")
        cmd_num_records = "servicelog --dump | grep \"Power Platform (RTAS) Event\" | wc -l"
        NoofRecords = self.run_cmd_out(cmd_num_records)
        if int(NoofRecords) == 0:
            self.is_fail += 1
            self.log.info("servicelog --dump does have recored any "
                          "RTAS Event")
        self.log.info("=====3 -  Cleaning events from the servicelog "
                      "database =======")
        self.run_cmd("servicelog_manage --truncate events --force")
        NoofRecords = 0
        self.log.info("======4 - Checking if the events database was"
                      " really cleaned up=========")
        NoofRecords = self.run_cmd_out(cmd_num_records)
        if int(NoofRecords):
            self.is_fail += 1
            self.log.info("servicelog not trucated")
        # Start of the service stopped earlier
        Manageservice.start("rtas_errd")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in servicelog_manage"
                      "verification" % self.is_fail)

    def test_servicelog_repair_action(self):
        """
        The test checks servicelog_log_repair_action command
        of servicelog.
        """
        event = "v6_power_error"
        # Stopping rtas_errd daemon so we can work
        Manageservice = ServiceManager()
        Manageservice.stop("rtas_errd")
        self.log.info("=====0 -  Cleaning events from the servicelog "
                      "database =======")
        self.run_cmd("servicelog_manage --truncate events --force")
        self.run_cmd("rm -f /var/log/platform")
        self.run_cmd("rm -f /var/spool/mail/root")
        self.log.info("===========1 - Injecting event ==="
                      "======")
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s/%s" %
                     (self.events_path, event))
        self.log.info("===========2 - Checking servicelog before the "
                      "repair action =========")
        self.run_cmd("servicelog --type=ppc64_rtas -v")
        location = self.run_cmd_out("servicelog --type=ppc64_rtas"
                                    " -v | grep Location | "
                                    "cut -d\":\" -f2 | sed 's/^ *//'")
        """
        The log_repair_action command creates an entry in the error log
        to indicate that the device at the specified location code has
        been repaired.  When  viewing  a  list  of platform  errors,
        all  errors on the device at the specified location code priorI
        to the specified date will be considered closed (fixed).
        """
        self.log.info("===========3 - Introducing the repair action "
                      "=========")
        self.run_cmd("log_repair_action -q -t ppc64_rtas -l %s" % location)
        self.log.info("===========4 - Checking servicelog after the "
                      "repair action =========")
        self.run_cmd("servicelog --type=ppc64_rtas -v")
        # Checking if we have a repair action on servicelog
        repair_event = self.run_cmd_out("servicelog "
                                        "--type=ppc64_rtas | grep \"Repair Action\" | "
                                        "cut -d\":\" -f1")
        if repair_event != "Repair Action":
            self.is_fail += 1
            self.log.debug("Warning: Repair Action not found!")
        # Checking if the event was repaired indeed
        repaired = self.run_cmd_out("servicelog "
                                    "--type=ppc64_rtas | grep \"Event Repaired\" | cat -b "
                                    "| grep 2 | cut -d\":\" -f2 | sed 's/^ *//'")
        if repaired != "Yes":
            self.is_fail += 1
            self.log.debug("Warning: Event not repaired!")

        # Start of the service stopped earlier
        Manageservice.start("rtas_errd")

        if self.is_fail >= 1:
            self.fail("%s command(s) failed in servicelog_repair_action"
                      "verification" % self.is_fail)


if __name__ == "__main__":
    main()

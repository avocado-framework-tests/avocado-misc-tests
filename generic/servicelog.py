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
# Copyright: 2016 IBM
# Authors: Rafael Camarda Silva Folco (rfolco@br.ibm.com) (Original author)
#          Lucas Meneghel Rodrigues (lucasmr@br.ibm.com)
#          Hariharan T.S. <hari@linux.vnet.ibm.com> (ported to avocado)
#          Pavithra <pavrampu@linux.vnet.ibm.com> (Added test_servicelog)

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import genio
from avocado.utils.service import ServiceManager
from avocado.utils.software_manager import SoftwareManager


class servicelog(Test):

    is_fail = 0
    EVENTS_PATH = os.path.join(os.path.dirname(__file__), "servicelog.py.data", "rtas_events")

    def run_cmd(self, cmd):
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
        return

    def setUp(self):
        if "ppc" not in os.uname()[4]:
            self.skip("supported only on Power platform")
        sm = SoftwareManager()
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.skip("servicelog: is not supported on the PowerNV platform")
        for package in ("servicelog", "ppc64-diag"):
            if not sm.check_installed(package) and not sm.install(package):
                self.skip("Fail to install %s required for this"
                          " test." % package)

    def test_servicelog(self):
        """
        The test checks servicelog commands.
        """
        rtas_events = ["v6_fru_replacement", "v6_memory_info", "v6_power_error",
                       "v6_power_error2", "v3_predictive_cpu_failure",
                       "v6_predictive_cpu_failure", "v6_fw_predictive_error",
                       "v4_io_bus_failure", "v6_io_sub_error"]
        for event in rtas_events:
            self.log.info("Starting test scenario for %s" % event)
            self.log.info("1 - Cleaning servicelog...")
            self.run_cmd("servicelog_manage --truncate notify --force")
            self.log.info("2 - Injecting event %s" % event)
            self.run_cmd("rtas_errd -d -f %s/%s" % (self.EVENTS_PATH, event))
            self.log.info("3 - Checking if service log does return ppc64_rtas events")
            self.run_cmd("servicelog --type=ppc64_rtas")
            inject = process.system_output("servicelog --type=all | "
                                           "grep 'PPC64 Platform Event' | cut -d':' -f1", shell=True)
            if "PPC64 Platform Event" == inject:
                self.is_fail += 1
                self.log.info("Event %s error: Event generated is not a "
                              "'PPC64 Platform Event'" % event)
            self.log.info("5 - Checking if the event was dumped to /var/log/platform")
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
            self.fail("%s command(s) failed in servicelog_notify "
                      "verification" % self.is_fail)

    def test_servicelog_notify(self):
        """
        The test checks servicelog_notify command of servicelog.
        """
        EVENT = "v6_power_error"
        TMP_DIR = "/var/tmp/ras/"
        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)
        NOTIFY_SCRIPT = os.path.join(TMP_DIR, "notify_script.sh")
        # Stopping rtas_errd daemon so we can work
        Manageservice = ServiceManager()
        Manageservice.stop("rtas_errd")
        self.log.info("===============1. Creating notification tool ===="
                      "===========")
        NS_Data = """
        #!/bin/bash
        echo 'Executing notification tool script'
        tail /var/log/platform
        echo 'If you see this message, this means that the script was
        triggered properly'
        """
        genio.write_file(NOTIFY_SCRIPT, NS_Data)
        cmd = "chmod 777 %s" % NOTIFY_SCRIPT
        process.run(cmd, ignore_status=True, sudo=True, shell=True)
        self.log.info("=======2 - Adding notification tool to servicelog ="
                      "======")
        self.run_cmd("servicelog_notify --add --command=%s --type=all "
                     "--repair_action=all --serviceable=all" % NOTIFY_SCRIPT)
        self.log.info("===========3 - Injecting serviceable event ==="
                      "======")
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s/%s" % (self.EVENTS_PATH, EVENT))
        self.log.info("========4 - Checking registered notification tools =="
                      "======")
        self.run_cmd("servicelog_notify --list")
        self.log.info("=====5 - Check for notify_script.sh registered "
                      "successfully  =======")
        self.run_cmd("servicelog_notify --list | grep notify_script")
        IDs = process.system_output("servicelog_notify --list --command=%s | "
                                    "grep \"Servicelog ID:\" | cut -d\":\" -f2 | sed 's/^ *//'" %
                                    NOTIFY_SCRIPT, shell=True)
        self.log.info("=====6 - Checking if servicelog_notify --list, "
                      "lists the command just added  =======")
        for ID in IDs:
            if ID.strip():
                self.run_cmd("servicelog_notify --list --id=%s" % ID.strip())
        self.log.info("=====7 - Checking if servicelog_notify --query, lists "
                      "the command just added =======")
        self.run_cmd("servicelog_notify --query --command=%s" % NOTIFY_SCRIPT)
        self.log.info("=====8 - Checking servicelog_notify --remove =======")
        for ID in IDs:
            if ID.strip():
                self.run_cmd("servicelog_notify --remove --id=%s" % ID.strip())
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
        EVENT = "v6_fru_replacement"
        TMP_DIR = "/var/tmp/ras/"
        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)
        os.path.join(TMP_DIR, "notify_script.sh")

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
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s/%s" % (self.EVENTS_PATH, EVENT))
        self.log.info("===========2 - Checking if the event shows up"
                      " on servicelog_manage =========")
        self.run_cmd("servicelog --dump")
        NoofRecords = process.system_output("servicelog --dump |"
                                            " grep \"Power Platform (RTAS) Event\" | wc -l", shell=True)
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
        NoofRecords = process.system_output("servicelog --dump |"
                                            " grep \"Power Platform (RTAS) Event\" | wc -l", shell=True)
        if int(NoofRecords):
            self.is_fail += 1
            self.log.info("servicelog not trucated")

        # Start of the service stopped earlier
        Manageservice.start("rtas_errd")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in servicelog_notify "
                      "verification" % self.is_fail)

    def test_servicelog_repair_action(self):
        """
        The test checks servicelog_log_repair_action command
    of servicelog.
        """
        self.is_fail = 0
        EVENT = "v6_power_error"
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
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s/%s" % (self.EVENTS_PATH, EVENT))
        self.log.info("===========2 - Checking servicelog before the "
                      "repair action =========")
        self.run_cmd("servicelog --type=ppc64_rtas -v")

        """
        The output of servicelog shows the location code of the
        device repaired. Parse this output and get the location string.
        """
        LOCATION = process.system_output("servicelog --type=ppc64_rtas"
                                         " -v | grep Location | cut -d\":\" -f2 | sed 's/^ *//'",
                                         shell=True)
        """
        The log_repair_action command creates an entry in the error log
        to indicate that the device at the specified location code has
        been repaired.  When  viewing  a  list  of platform  errors,
        all  errors on the device at the specified location code priorI
        to the specified date will be considered closed (fixed).
        """
        self.log.info("===========3 - Introducing the repair action "
                      "=========")
        self.run_cmd("log_repair_action -q -t ppc64_rtas -l %s" % LOCATION)
        self.log.info("===========4 - Checking servicelog after the "
                      "repair action =========")
        self.run_cmd("servicelog --type=ppc64_rtas -v")

        """
        Checking if we have a repair action on servicelog
        """
        REPAIR_EVENT = process.system_output("servicelog "
                                             "--type=ppc64_rtas | grep \"Repair Action\" | "
                                             "cut -d\":\" -f1", shell=True)
        if REPAIR_EVENT != "Repair Action":
            self.is_fail += 1
            self.log.info("Warning: Repair Action not found!")
        """
        Checking if the event was repaired indeed
        """
        REPAIRED = process.system_output("servicelog "
                                         "--type=ppc64_rtas | grep \"Event Repaired\" | cat -b "
                                         "| grep 2 | cut -d\":\" -f2 | sed 's/^ *//'", shell=True)
        if REPAIRED != "Yes":
            self.is_fail += 1
            self.log.info("Warning: Event not repaired!")

        # Start of the service stopped earlier
        Manageservice.start("rtas_errd")

        if self.is_fail >= 1:
            self.fail("%s command(s) failed in servicelog_notify "
                      "verification" % self.is_fail)


if __name__ == "__main__":
    main()

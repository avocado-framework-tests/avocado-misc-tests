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
# Copyright: 2023 IBM
# Author: Gautam Menghani <gautam@linux.ibm.com>

import os

from avocado import Test
from avocado.utils import process, cpu, distro
from avocado.utils.service import ServiceManager
from avocado.utils.software_manager.manager import SoftwareManager


class Pgbench(Test):

    """
    This module will run the pgbench benchmark. Pgbench is a benchmark for
    measuring the throughput achieved by executing database transactions on
    PostgresSQL database.
    """
    sm = SoftwareManager()
    scaling_factor = worker_threads = db_clients = protocol = \
        benchmark_duration = transaction_count = 0
    already_installed = True

    def run_cmd(self, cmd, ignore_failure):
        command = process.run(cmd, ignore_status=True)

        if command.exit_status and ignore_failure:
            self.log.info(f"Command '{cmd}' returned '{command.exit_status}' "
                          f"with the text '{command.stderr_text}'")
            return [command.exit_status, command.stderr_text]
        elif command.exit_status:
            self.cancel(f"Command '{cmd}' returned '{command.exit_status}' "
                        f"with the text '{command.stderr_text}'")
        else:
            return [command.exit_status, command.stdout_text]

    def get_distro_name(self):
        distro_name = distro.detect().name
        if distro_name in ['debian', 'fedora', 'rhel', 'SuSE']:
            return distro_name
        return None

    def install_and_initialize_postgres(self, distro_name):
        packages = ["postgresql", "postgresql-contrib"]
        for package in packages:
            self.sm.install(package)

        # rhel/fedora need an extra pkg and initialization
        if distro_name in ['fedora', 'rhel']:
            self.sm.install('postgresql-server')
            output = self.run_cmd("postgresql-setup --initdb", True)
            if output[0] and "not empty" not in output[1]:
                self.cancel(f"Failed to initialize postgres - {output[1]}")

    def setUp(self):
        '''
        Install Pgbench
        '''
        # check root privileges ($USER should be able to run commands
        # as another user without requiring a password)
        if os.geteuid() != 0:
            self.cancel("This script requires root privileges, "
                        "Please try again with 'sudo' or as 'root'")

        # check if pgbench is installed
        if (self.sm.check_installed("pgbench")):
            self.log.info("Pgbench is already installed")
        else:
            distro_name = self.get_distro_name()
            if distro_name:
                self.install_and_initialize_postgres(distro_name)
                self.already_installed = False
            else:
                self.cancel("Unsupported Linux distribution")

        # restart postgres service
        ManagerService = ServiceManager()
        ManagerService.restart("postgresql")

        # add current user to db
        output = self.run_cmd(f"sudo -u postgres createuser --superuser {os.getlogin()}", True)
        if output[0] and "already exists" not in output[1]:
            self.cancel(f"Could not create role {os.getlogin()}")

        # Setup the params
        self.scaling_factor = self.params.get("scaling_factor", default=100)
        self.worker_threads = self.params.get("worker_threads", default=cpu.online_count())
        self.db_clients = self.params.get("db_clients", default=cpu.online_count())
        self.protocol = self.params.get("protocol", default="prepared")
        self.benchmark_duration = self.params.get("benchmark_duration", default=0)
        self.transaction_count = self.params.get("transaction_count", default=0)

        # validation: pgbench cannot accept both transaction count and duration
        if self.benchmark_duration > 0 and self.transaction_count > 0:
            self.log.warn("Pgbench cannot accept both max transaction count and duration of the test, proceeding with specified time limit")
        elif self.benchmark_duration == 0 and self.transaction_count == 0:
            self.log.warn("Transaction count / duration of the test not specified, defaulting to time limit of 120 secs")
            self.benchmark_duration = 120

        # create the db
        self.run_cmd("createdb pgbench", False)

        # setup tables
        self.run_cmd(f"pgbench -i -s {self.scaling_factor} -n pgbench", False)

    def test(self):

        # run the benchmark
        if self.benchmark_duration > 0:
            result = self.run_cmd(f"pgbench --protocol={self.protocol} --jobs={self.worker_threads} --scale={self.scaling_factor} --client={self.db_clients}  -n --time={self.benchmark_duration} -r pgbench", False)
        else:
            result = self.run_cmd(f"pgbench --protocol={self.protocol} --jobs={self.worker_threads} --scale={self.scaling_factor} --client={self.db_clients}  -n --transactions={self.transaction_count} -r pgbench", False)
        self.log.info("===== Pgbench benchmark results ======")
        if not result[0]:
            self.log.info(result[1])

    def tearDown(self):
        # destory the db
        self.run_cmd("dropdb pgbench", True)

        # reset things if we set them up
        if not self.already_installed:
            packages = ["postgresql", "postgresql-contrib"]
            for package in packages:
                self.sm.remove(package)

            distro_name = self.get_distro_name()
            if distro_name in ['fedora', 'rhel']:
                self.sm.remove('postgresql-server')

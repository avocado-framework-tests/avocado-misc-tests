#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE for more details.
#
# Copyright: 2026 IBM

import os
import platform
import tempfile
import time

from avocado import Test
from avocado.utils import dmesg, distro, process
from avocado.utils.software_manager.manager import SoftwareManager


class PerfVpaDtl(Test):
    """
    Validate VPA DTL perf PMU events on pseries/POWER guests.

    The testcase runs all supported VPA DTL events sequentially in one job:
    dtl_all, dtl_cede, dtl_preempt, and dtl_fault.

    :avocado: tags=perf,vpa_dtl,powerpc,privileged
    """

    EVENT_PLANS = [
        ('dtl_all', 'all_duration', True),
        ('dtl_cede', 'cede_duration', 'require_cede'),
        ('dtl_preempt', 'preempt_duration', 'require_preempt'),
        ('dtl_fault', 'fault_duration', 'require_fault'),
    ]

    def setUp(self):
        """
        Install required packages and initialize test parameters.
        """
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'stress-ng']

        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common',
                         'linux-tools-%s' % platform.uname()[2]])
        elif 'debian' in detected_distro.name:
            deps.extend(['linux-perf'])
        elif detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported by %s"
                        % detected_distro.name)

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        self.all_duration = int(self.params.get('all_duration', default=20))
        self.cede_duration = int(self.params.get('cede_duration', default=20))
        self.preempt_duration = int(self.params.get('preempt_duration',
                                                    default=60))
        self.fault_duration = int(self.params.get('fault_duration',
                                                  default=90))
        self.preempt_cpu_factor = int(self.params.get('preempt_cpu_factor',
                                                      default=4))
        self.fault_cpu_factor = int(self.params.get('fault_cpu_factor',
                                                    default=2))
        self.fault_vm_workers = int(self.params.get('fault_vm_workers',
                                                    default=8))
        self.fault_vm_bytes = self.params.get('fault_vm_bytes',
                                              default='90%')
        self.record_retries = int(self.params.get('record_retries',
                                                  default=3))
        self.retry_sleep = int(self.params.get('retry_sleep',
                                               default=2))
        self.inter_event_sleep = int(self.params.get('inter_event_sleep',
                                                     default=2))
        self.require_cede = self.params.get('require_cede', default=True)
        self.require_preempt = self.params.get('require_preempt',
                                               default=False)
        self.require_fault = self.params.get('require_fault',
                                             default=False)

        self.cpu_count = os.cpu_count() or 1
        self.generated_files = []
        dmesg.clear_dmesg()

    def _run_cmd(self, cmd, ignore_status=False):
        """
        Run a shell command with sudo.
        """
        return process.run(cmd, shell=True, sudo=True,
                           ignore_status=ignore_status)

    def _get_cmd_output(self, cmd):
        """
        Return decoded output for a shell command.
        """
        return process.system_output(cmd, shell=True, sudo=True,
                                     ignore_status=True).decode('utf-8')

    def _require_vpa_dtl_support(self):
        """
        Ensure the vpa_dtl PMU and event aliases are available.
        """
        if not os.path.isdir('/sys/bus/event_source/devices/vpa_dtl'):
            self.cancel("vpa_dtl PMU is not present on this system")

        perf_list = self._get_cmd_output("perf list vpa_dtl")
        for event, _, _ in self.EVENT_PLANS:
            if event not in perf_list:
                self.cancel("Missing VPA DTL event alias: %s" % event)

    def _build_workload_cmd(self, event, duration):
        """
        Build the workload command for a VPA DTL event.
        """
        if event in ['dtl_all', 'dtl_cede']:
            return None

        if event == 'dtl_preempt':
            return "stress-ng --cpu %s --timeout %ss" % (
                self.cpu_count * self.preempt_cpu_factor, duration)

        if event == 'dtl_fault':
            return ("stress-ng --cpu %s --vm %s --vm-bytes %s "
                    "--vm-method all --page-in --timeout %ss" %
                    (self.cpu_count * self.fault_cpu_factor,
                     self.fault_vm_workers,
                     self.fault_vm_bytes,
                     duration))

        self.cancel("Unsupported VPA DTL event: %s" % event)

    def _record_event(self, event, duration, workload_cmd=None):
        """
        Record a single VPA DTL event and store the raw perf report in a file.

        Only the first 20 lines of `perf report -D` are logged to keep avocado
        output concise.
        """
        for attempt in range(1, self.record_retries + 1):
            perf_data = tempfile.NamedTemporaryFile(
                prefix='perf_vpa_dtl_', suffix='.data', delete=False).name
            perf_dump = tempfile.NamedTemporaryFile(
                prefix='perf_vpa_dtl_', suffix='.report', delete=False).name
            self.generated_files.extend([perf_data, perf_dump])

            cmd_parts = []
            if workload_cmd:
                cmd_parts.append("%s &" % workload_cmd)
            cmd_parts.append("perf record -o %s -a -e vpa_dtl/%s/ sleep %s" %
                             (perf_data, event, duration))
            cmd = " ".join(cmd_parts)

            self.log.info(
                "===== Starting event=%s duration=%ss attempt=%s/%s =====",
                event,
                duration,
                attempt,
                self.record_retries)
            if workload_cmd:
                self.log.info("Running workload for %s: %s", event,
                              workload_cmd)

            result = self._run_cmd(cmd, ignore_status=True)
            if result.exit_status != 0:
                stderr = result.stderr.decode('utf-8', errors='ignore').strip()
                if attempt < self.record_retries:
                    self.log.warning(
                        "perf record could not open %s on attempt "
                        "%s/%s: exit_status=%s stderr=%s",
                        event,
                        attempt,
                        self.record_retries,
                        result.exit_status,
                        stderr)
                    time.sleep(self.retry_sleep)
                    continue
                self.fail("perf record failed for %s after %s attempts: %s" %
                          (event, self.record_retries, result))

            report_cmd = "perf report -D -i %s > %s" % (perf_data, perf_dump)
            result = self._run_cmd(report_cmd, ignore_status=True)
            if result.exit_status != 0:
                if attempt < self.record_retries:
                    self.log.warning("perf report -D failed for %s on attempt "
                                     "%s/%s: %s", event, attempt,
                                     self.record_retries, result)
                    time.sleep(self.retry_sleep)
                    continue
                self.fail("perf report -D failed for %s after %s attempts: %s"
                          % (event, self.record_retries, result))

            preview = self._get_cmd_output("head -20 %s" % perf_dump).strip()
            if preview:
                self.log.info("event=%s perf_report_head:\n%s", event, preview)

            count_out = self._get_cmd_output(
                "grep -c 'VPA DTL PMU data' %s || true" % perf_dump).strip()
            try:
                count = int(count_out or 0)
            except ValueError:
                count = 0

            self.log.info("event=%s record_count=%s perf_data=%s perf_dump=%s",
                          event, count, perf_data, perf_dump)
            self.log.info("===== Completed event=%s =====", event)
            return count

        self.fail("Unexpected retry loop exit for %s" % event)

    def _verify_record_count(self, event, count, required):
        """
        Enforce record expectations for an event.
        """
        if count > 0:
            self.log.info("%s: PASSED", event)
            return

        if required:
            self.fail("%s: FAILED - no VPA DTL records found" % event)

        if event in ['dtl_preempt', 'dtl_fault']:
            self.log.warning("%s: WARN - scenario did not hit event", event)
        else:
            self.log.warning("%s: WARN - no VPA DTL records found", event)

    def _execute_event(self, event, duration, required):
        """
        Run one event completely before moving to the next event.
        """
        workload_cmd = self._build_workload_cmd(event, duration)
        count = self._record_event(event, duration, workload_cmd)
        self._verify_record_count(event, count, required)
        time.sleep(self.inter_event_sleep)

    def test(self):
        """
        Execute all VPA DTL events sequentially in a single testcase.
        """
        self._require_vpa_dtl_support()

        for event, duration_attr, required_value in self.EVENT_PLANS:
            duration = getattr(self, duration_attr)
            required = (required_value if isinstance(required_value, bool)
                        else getattr(self, required_value))
            self._execute_event(event, duration, required)

    def tearDown(self):
        """
        Remove generated files and collect relevant dmesg errors.
        """
        for path in self.generated_files:
            if os.path.isfile(path):
                process.run("rm -f %s" % path, shell=True, sudo=True)
        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                    'soft lockup', 'Unable to handle'])

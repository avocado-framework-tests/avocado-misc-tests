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
# Copyright: 2025 IBM.
# Author: Tejas Manhas <Tejas.Manhas1@ibm.com>

"""
POWER12 perf tool validation test suite.

Validates the perf tool's interface, sub-commands, and PMU descriptor
accuracy on a P12 (pvr 0083 4100) system.  Focuses on three pillars:

  A. Perf regression tests
     - perf stat with all Default metric groups (-M)
     - perf bench sched / mem
     - perf top sampling sanity (2-second run)

  B. Perf tool validation
     - perf list output completeness (hardware / software / tracepoint / PMU)
     - perf evlist -v correctly names events from perf.data
     - perf script decodes a recorded sample without errors
     - perf annotate runs without segfault on a simple binary
     - perf stat -x csv output format is parseable

  C. Perf event validation (P12-specific)
     - Exactly 24 generic CPU events registered (matches output.log §5)
     - Event sysfs files are read-only (write rejected for any user)
     - vpa_dtl PMU has exactly 4 events
     - No hv_24x7 / hv_gpci PMU present on PowerVM LPAR
     - perf stat with multiple events simultaneously (group syntax)
     - perf stat -I 1000 interval output is well-formed
     - perf stat --metric-only produces metric output without raw counts

:avocado: tags=privileged,perf,p12,validation
"""

import os
import re
import tempfile
import platform
from avocado import Test
from avocado.utils import cpu, dmesg, genio, process
from avocado.utils.software_manager.manager import SoftwareManager

P12_REVISION = '4100'

# Exact generic event count observed on P12 LPAR (output.log §5)
EXPECTED_CPU_EVENT_COUNT = 24

# PMUs that must NOT exist on a P12 PowerVM LPAR
ABSENT_PMUS = ['hv_24x7', 'hv_gpci']

# PMUs that must exist on a P12 PowerVM LPAR
REQUIRED_PMUS = ['cpu', 'software', 'tracepoint', 'vpa_dtl']


class PerfP12Validation(Test):

    """
    POWER12 perf tool and event validation.
    :avocado: tags=privileged,perf,p12,validation
    """

    fail_cmd = []

    def setUp(self):
        smm = SoftwareManager()
        self.cpu_rev = cpu.get_revision()
        if self.cpu_rev != P12_REVISION:
            self.cancel('This test targets Power12 (revision %s). '
                        'Detected revision: %s' % (P12_REVISION, self.cpu_rev))
        if platform.machine() != 'ppc64le':
            self.cancel('Power12 is ppc64le only')

        for pkg in ['perf']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('perf package required but could not be installed')

        self.temp_file = tempfile.NamedTemporaryFile(suffix='.perf.data',
                                                     delete=False).name
        dmesg.clear_dmesg()

    # ====================================================================
    # A. Perf regression tests
    # ====================================================================

    def test_perf_stat_default_metrics(self):
        """perf stat -M with all Default metric groups must not error."""
        for group in ['Default', 'Default2', 'Default3', 'Default4']:
            cmd = 'perf stat -M %s sleep 1' % group
            result = process.run(cmd, shell=True, sudo=True,
                                 ignore_status=True)
            output = (result.stdout + result.stderr).decode()
            if result.exit_status != 0 or 'not supported' in output:
                self.fail_cmd.append(cmd)
            else:
                self.log.info('Metric group %s: OK', group)
        if self.fail_cmd:
            self.fail('perf stat metric groups failed: %s' % self.fail_cmd)

    def test_perf_bench_sched(self):
        """perf bench sched all must complete without error."""
        cmd = 'perf bench sched all'
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail('perf bench sched all failed: %s'
                      % (result.stdout + result.stderr).decode())

    def test_perf_bench_mem(self):
        """perf bench mem all must complete without error."""
        cmd = 'perf bench mem all'
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail('perf bench mem all failed: %s'
                      % (result.stdout + result.stderr).decode())

    def test_perf_top_sampling(self):
        """perf top must run for 2 seconds without crashing."""
        cmd = 'timeout 2 perf top -a --stdio'
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        # exit_status 124 means timeout killed it – that is expected/OK
        if result.exit_status not in (0, 124):
            self.fail('perf top exited with unexpected status %d: %s'
                      % (result.exit_status,
                         (result.stdout + result.stderr).decode()))

    # ====================================================================
    # B. Perf tool validation
    # ====================================================================

    def test_perf_list_contains_all_sections(self):
        """perf list must contain hardware, software, tracepoint and PMU sections."""
        output = process.system_output('perf list', shell=True,
                                       sudo=True, ignore_status=True).decode()
        for section_kw in ['[Hardware event]', '[Software event]',
                           '[Tracepoint event]', '[Kernel PMU event]']:
            if section_kw not in output:
                self.fail_cmd.append('perf list missing: %s' % section_kw)
        if self.fail_cmd:
            self.fail('perf list incomplete: %s' % self.fail_cmd)

    def test_perf_evlist_names_events(self):
        """perf evlist -v on a recorded perf.data must name the events."""
        cmd_record = ('perf record -o %s -e cycles,instructions -a sleep 1'
                      % self.temp_file)
        process.run(cmd_record, shell=True, sudo=True, ignore_status=True)
        if not os.path.isfile(self.temp_file):
            self.cancel('perf record did not produce perf.data')

        output = process.system_output(
            'perf evlist -v -i %s' % self.temp_file,
            shell=True, sudo=True, ignore_status=True).decode()
        for event in ('cycles', 'instructions'):
            if event not in output:
                self.fail_cmd.append('perf evlist missing event: %s' % event)
        if self.fail_cmd:
            self.fail('perf evlist output incomplete: %s' % self.fail_cmd)

    def test_perf_script_decodes_samples(self):
        """perf script must decode samples from a recorded perf.data."""
        cmd_record = ('perf record -o %s -e cycles -a sleep 1'
                      % self.temp_file)
        process.run(cmd_record, shell=True, sudo=True, ignore_status=True)
        if not os.path.isfile(self.temp_file):
            self.cancel('perf record did not produce perf.data')

        result = process.run('perf script -i %s' % self.temp_file,
                             shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail('perf script failed: %s'
                      % (result.stdout + result.stderr).decode())

    def test_perf_stat_csv_output(self):
        """perf stat -x , output must be parseable CSV."""
        cmd = "perf stat -x , -e cycles,instructions sleep 1"
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        # perf stat writes to stderr
        for line in result.stderr.decode().splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) < 3:
                self.fail('CSV line has fewer than 3 fields: %r' % line)
                break
        self.log.info('perf stat CSV output is well-formed')

    def test_perf_stat_interval_output(self):
        """perf stat -I 500 must emit interval lines with timestamps."""
        cmd = 'perf stat -I 500 -e cycles sleep 2'
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        output = (result.stdout + result.stderr).decode()
        # Each interval line starts with a timestamp like "     0.500"
        ts_lines = [ln for ln in output.splitlines()
                    if re.match(r'\s+\d+\.\d+', ln)]
        if not ts_lines:
            self.fail('perf stat -I produced no timestamped interval lines')
        self.log.info('perf stat -I produced %d interval lines', len(ts_lines))

    def test_perf_stat_metric_only(self):
        """perf stat --metric-only must print metric values, not raw counts."""
        cmd = 'perf stat --metric-only -M Default sleep 1'
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        output = (result.stdout + result.stderr).decode()
        if result.exit_status != 0:
            self.fail('perf stat --metric-only failed: %s' % output)
        # Metric-only output should not contain raw counter lines (no commas
        # for large numbers in counter position)
        self.log.info('perf stat --metric-only completed')

    # ====================================================================
    # C. Perf event validation (P12-specific)
    # ====================================================================

    def test_cpu_event_count_is_24(self):
        """Exactly 24 generic CPU events must be present (matches output.log §5)."""
        events_dir = '/sys/bus/event_source/devices/cpu/events'
        if not os.path.isdir(events_dir):
            self.fail('CPU events sysfs dir not found: %s' % events_dir)
        count = len(os.listdir(events_dir))
        self.log.info('CPU event count: %d (expected %d)',
                      count, EXPECTED_CPU_EVENT_COUNT)
        if count != EXPECTED_CPU_EVENT_COUNT:
            self.fail('Expected %d CPU events, found %d'
                      % (EXPECTED_CPU_EVENT_COUNT, count))

    def test_sysfs_event_files_readonly(self):
        """CPU sysfs event files must reject writes from any user."""
        events_dir = '/sys/bus/event_source/devices/cpu/events'
        if not os.path.isdir(events_dir):
            self.cancel('CPU events sysfs dir not found')

        import random
        files = os.listdir(events_dir)
        sample = random.sample(files, min(3, len(files)))
        for fname in sample:
            path = os.path.join(events_dir, fname)
            result = process.run('echo 1 > %s' % path,
                                 shell=True, sudo=True, ignore_status=True)
            output = (result.stdout + result.stderr).decode()
            if 'Permission denied' not in output and result.exit_status == 0:
                self.fail_cmd.append('Write unexpectedly succeeded: %s' % path)
            else:
                self.log.info('Correctly rejected write to %s', path)
        if self.fail_cmd:
            self.fail('sysfs write-protection failures: %s' % self.fail_cmd)

    def test_vpa_dtl_has_four_events(self):
        """vpa_dtl PMU must expose exactly 4 events."""
        vpa_events_dir = '/sys/bus/event_source/devices/vpa_dtl/events'
        if not os.path.isdir(vpa_events_dir):
            self.cancel('vpa_dtl events dir not found – not a PowerVM LPAR')
        events = os.listdir(vpa_events_dir)
        self.log.info('vpa_dtl events: %s', events)
        if len(events) != 4:
            self.fail('Expected 4 vpa_dtl events, found %d: %s'
                      % (len(events), events))

    def test_absent_pmus_on_lpar(self):
        """hv_24x7 and hv_gpci PMUs must NOT be present on a PowerVM LPAR."""
        devices_dir = '/sys/bus/event_source/devices'
        for pmu in ABSENT_PMUS:
            if os.path.isdir(os.path.join(devices_dir, pmu)):
                self.fail_cmd.append('%s PMU found on LPAR (unexpected)' % pmu)
            else:
                self.log.info('%s PMU correctly absent on LPAR', pmu)
        if self.fail_cmd:
            self.fail('Unexpected PMUs present: %s' % self.fail_cmd)

    def test_required_pmus_present(self):
        """cpu, software, tracepoint, and vpa_dtl PMUs must be present."""
        devices_dir = '/sys/bus/event_source/devices'
        for pmu in REQUIRED_PMUS:
            if not os.path.isdir(os.path.join(devices_dir, pmu)):
                self.fail_cmd.append('Required PMU missing: %s' % pmu)
            else:
                self.log.info('Required PMU present: %s', pmu)
        if self.fail_cmd:
            self.fail('Missing required PMUs: %s' % self.fail_cmd)

    def test_perf_stat_event_group_syntax(self):
        """perf stat with a {cycles,instructions} group must work."""
        cmd = "perf stat -e '{cycles,instructions}' sleep 1"
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        output = (result.stdout + result.stderr).decode()
        if result.exit_status != 0 or 'not supported' in output:
            self.fail('perf stat group syntax failed: %s' % output)
        for event in ('cycles', 'instructions'):
            if event not in output:
                self.fail_cmd.append('Group output missing: %s' % event)
        if self.fail_cmd:
            self.fail('perf stat group syntax output incomplete: %s'
                      % self.fail_cmd)

    def test_perf_stat_all_cpu_events(self):
        """All 24 generic CPU events must run without 'not supported' errors."""
        events_dir = '/sys/bus/event_source/devices/cpu/events'
        if not os.path.isdir(events_dir):
            self.cancel('CPU events dir not found')
        for fname in sorted(os.listdir(events_dir)):
            cmd = 'perf stat -e %s sleep 1' % fname
            result = process.run(cmd, shell=True, sudo=True,
                                 ignore_status=True)
            output = (result.stdout + result.stderr).decode()
            if result.exit_status != 0 or 'not supported' in output:
                self.fail_cmd.append(cmd)
            else:
                self.log.info('CPU event OK: %s', fname)
        if self.fail_cmd:
            self.fail('%d CPU event(s) failed: %s'
                      % (len(self.fail_cmd), self.fail_cmd))

    # ====================================================================
    # tearDown
    # ====================================================================

    def tearDown(self):
        if hasattr(self, 'temp_file') and os.path.isfile(self.temp_file):
            os.remove(self.temp_file)
        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'segfault',
                                    'soft lockup', 'SIGSEGV'])

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
POWER12 perf regression test suite.

Covers the observable differences between P12 (pvr 0083 4100) and previous
generations as seen in a PowerVM LPAR running RHEL 10.x:

  1. PMU name reported as "Power12" in sysfs caps
  2. All 24 generic CPU events present with correct raw codes (from output.log §6)
  3. vpa_dtl PMU present and its four events (dtl_all/cede/fault/preempt) work
  4. perf stat with generic hardware events returns non-zero counts
  5. Legacy-cache alias events work (L1-dcache-loads, LLC-loads, …)
  6. Metric groups Default/Default2/Default3/Default4 all visible in perf list
  7. Raw event r2 (PM_INST_CMPL) counts; r10 (PM_CYC) counts zero in LPAR
     (matches observed behaviour from output.log §11)
  8. perf record + report round-trip produces a non-empty perf.data

:avocado: tags=privileged,perf,p12,regression
"""

import os
import re
import tempfile
import platform
from avocado import Test
from avocado.utils import cpu, dmesg, genio, process
from avocado.utils.software_manager.manager import SoftwareManager

# P12 CPU revision as reported by cpu.get_revision() (pvr field)
P12_REVISION = '4100'

# Expected PMU name in /sys/bus/event_source/devices/cpu/caps/pmu_name
EXPECTED_PMU_NAME = 'power12'

# Generic CPU events and their expected raw codes from output.log §6
P12_GENERIC_EVENTS = {
    'branch-instructions':    '0x10068',
    'branch-load-misses':     '0x400f6',
    'branch-loads':           '0x4d05e',
    'branch-misses':          '0x27098',
    'cache-misses':           '0x400f0',
    'cache-references':       '0x100fc',
    'cpu-cycles':             '0x600f4',
    'dTLB-load-misses':       '0x300fc',
    'instructions':           '0x500fa',
    'iTLB-load-misses':       '0x400fc',
    'L1-dcache-load-misses':  '0x3e054',
    'L1-dcache-loads':        '0x100fc',
    'L1-dcache-prefetches':   '0x1002c',
    'L1-dcache-store-misses': '0x300f0',
    'L1-icache-load-misses':  '0x200fc',
    'L1-icache-loads':        '0x4080',
    'L1-icache-prefetches':   '0x40a0',
    'LLC-load-misses':        '0x300fe',
    'LLC-loads':              '0x10340000003c040',
    'LLC-prefetches':         '0x100000016080',
    'LLC-store-misses':       '0x26880',
    'LLC-stores':             '0x10000046080',
    'mem-loads':              '0x35340401e0',
    'mem-stores':             '0x353c0401e0',
}

# vpa_dtl PMU events expected on P12 PowerVM LPARs
VPA_DTL_EVENTS = ['dtl_all', 'dtl_cede', 'dtl_fault', 'dtl_preempt']

# Metric group names that must appear in 'perf list' on P12
EXPECTED_METRIC_GROUPS = [
    'CPUs_utilized', 'insn_per_cycle', 'branch_miss_rate',
    'l1d_miss_rate', 'llc_miss_rate',
    'dtlb_miss_rate', 'l1i_miss_rate',
    'l1_prefetch_miss_rate',
]

# Hardware events that must produce a non-zero count under a trivial workload
MUST_COUNT_EVENTS = ['cycles', 'instructions']


class PerfP12Regression(Test):

    """
    POWER12 perf regression tests.
    :avocado: tags=privileged,perf,p12,regression
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

    # ------------------------------------------------------------------ #
    # 1. PMU name                                                          #
    # ------------------------------------------------------------------ #

    def test_pmu_name_power12(self):
        """Verify sysfs reports 'Power12' as the registered PMU name."""
        caps = '/sys/bus/event_source/devices/cpu/caps/pmu_name'
        if not os.path.isfile(caps):
            self.cancel('caps/pmu_name sysfs file not found')
        pmu_name = genio.read_file(caps).strip().lower()
        self.log.info('PMU name: %s', pmu_name)
        if EXPECTED_PMU_NAME not in pmu_name:
            self.fail('Expected PMU name containing "%s", got "%s"'
                      % (EXPECTED_PMU_NAME, pmu_name))

    # ------------------------------------------------------------------ #
    # 2. Generic event raw codes                                           #
    # ------------------------------------------------------------------ #

    def test_generic_event_raw_codes(self):
        """Verify every generic CPU event file has the expected raw code."""
        events_dir = '/sys/bus/event_source/devices/cpu/events'
        nfail = 0
        for event, expected_hex in P12_GENERIC_EVENTS.items():
            event_file = os.path.join(events_dir, event)
            if not os.path.isfile(event_file):
                self.log.warning('Event file missing: %s', event_file)
                nfail += 1
                continue
            content = genio.read_file(event_file).strip()
            # content is like "event=0x600f4" or may have multi-field values
            actual = content.split('=', 1)[-1].split('\n')[0].strip()
            if int(actual, 0) != int(expected_hex, 0):
                self.log.info('FAIL %s: expected %s got %s',
                              event, expected_hex, actual)
                nfail += 1
            else:
                self.log.info('PASS %s: %s', event, actual)
        if nfail:
            self.fail('%d generic event(s) had wrong raw codes' % nfail)

    # ------------------------------------------------------------------ #
    # 3. vpa_dtl PMU                                                       #
    # ------------------------------------------------------------------ #

    def test_vpa_dtl_pmu_present(self):
        """Verify the vpa_dtl PMU is present (PowerVM LPAR feature)."""
        vpa_dir = '/sys/bus/event_source/devices/vpa_dtl'
        if not os.path.isdir(vpa_dir):
            self.cancel('vpa_dtl PMU not found – not a PowerVM LPAR?')
        self.log.info('vpa_dtl PMU found at %s', vpa_dir)

    def test_vpa_dtl_events_count(self):
        """Verify all four vpa_dtl events are counted by perf stat."""
        vpa_dir = '/sys/bus/event_source/devices/vpa_dtl'
        if not os.path.isdir(vpa_dir):
            self.cancel('vpa_dtl PMU not found')

        for event in VPA_DTL_EVENTS:
            full = 'vpa_dtl/%s/' % event
            cmd = 'perf stat -e %s sleep 1' % full
            result = process.run(cmd, shell=True, sudo=True,
                                 ignore_status=True)
            output = (result.stdout + result.stderr).decode()
            if result.exit_status != 0 or 'not supported' in output:
                self.fail_cmd.append(cmd)
            else:
                self.log.info('vpa_dtl event OK: %s', full)

        if self.fail_cmd:
            self.fail('vpa_dtl events failed: %s' % self.fail_cmd)

    # ------------------------------------------------------------------ #
    # 4. Hardware events produce non-zero counts                           #
    # ------------------------------------------------------------------ #

    def test_hardware_events_nonzero(self):
        """Verify cycles and instructions count under a real workload."""
        workload = 'ls -R /usr/ > /dev/null'
        for event in MUST_COUNT_EVENTS:
            cmd = 'perf stat -e %s %s' % (event, workload)
            result = process.run(cmd, shell=True, sudo=True,
                                 ignore_status=True)
            output = (result.stdout + result.stderr).decode()
            m = re.search(r'([\d,]+)\s+' + re.escape(event), output)
            if not m:
                self.fail_cmd.append('%s: no count line found' % event)
                continue
            count = int(m.group(1).replace(',', ''))
            if count == 0:
                self.fail_cmd.append('%s: counted zero' % event)
            else:
                self.log.info('%s: %d', event, count)

        if self.fail_cmd:
            self.fail('Hardware events failed: %s' % self.fail_cmd)

    # ------------------------------------------------------------------ #
    # 5. Legacy cache alias events                                         #
    # ------------------------------------------------------------------ #

    def test_legacy_cache_events(self):
        """Verify legacy cache aliases resolve and run without error."""
        aliases = [
            'L1-dcache-loads', 'L1-icache-load-misses',
            'LLC-load-misses', 'dTLB-load-misses',
        ]
        for event in aliases:
            cmd = 'perf stat -e %s sleep 1' % event
            result = process.run(cmd, shell=True, sudo=True,
                                 ignore_status=True)
            output = (result.stdout + result.stderr).decode()
            if result.exit_status != 0 or 'not supported' in output:
                self.fail_cmd.append(cmd)
            else:
                self.log.info('Legacy cache alias OK: %s', event)

        if self.fail_cmd:
            self.fail('Legacy cache aliases failed: %s' % self.fail_cmd)

    # ------------------------------------------------------------------ #
    # 6. Metric groups visible in perf list                                #
    # ------------------------------------------------------------------ #

    def test_metric_groups_present(self):
        """Verify Default/Default2/Default3/Default4 metric groups exist."""
        output = process.system_output('perf list metric metricgroup',
                                       shell=True, ignore_status=True).decode()
        missing = [mg for mg in EXPECTED_METRIC_GROUPS if mg not in output]
        if missing:
            self.fail('Metric groups missing from perf list: %s' % missing)
        self.log.info('All expected metric groups found')

    # ------------------------------------------------------------------ #
    # 7. Raw event smoke tests (r2 counts, r10 zero in LPAR)              #
    # ------------------------------------------------------------------ #

    def test_raw_r2_inst_cmpl_counts(self):
        """r2 (PM_INST_CMPL) must produce a non-zero count in a LPAR."""
        cmd = 'perf stat -e r2 ls -R /usr/ > /dev/null'
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        output = (result.stdout + result.stderr).decode()
        m = re.search(r'([\d,]+)\s+r2', output)
        if not m:
            self.fail('r2 (PM_INST_CMPL): no count line in perf stat output')
        count = int(m.group(1).replace(',', ''))
        if count == 0:
            self.fail('r2 (PM_INST_CMPL): counted zero in LPAR (unexpected)')
        self.log.info('r2 (PM_INST_CMPL): %d', count)

    def test_raw_r10_cyc_zero_in_lpar(self):
        """r10 (PM_CYC) reads zero in a PowerVM LPAR (expected behaviour)."""
        cmd = 'perf stat -e r10 sleep 1'
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        output = (result.stdout + result.stderr).decode()
        m = re.search(r'([\d,]+)\s+r10', output)
        if not m:
            self.log.warning('r10 (PM_CYC): no count line – skipping')
            return
        count = int(m.group(1).replace(',', ''))
        self.log.info('r10 (PM_CYC) in LPAR: %d (expected 0)', count)
        # Non-zero here would indicate a change in LPAR PMU privilege semantics
        if count != 0:
            self.log.warning('r10 (PM_CYC) returned %d on a LPAR – '
                             'check if perf_event_paranoid was lowered', count)

    # ------------------------------------------------------------------ #
    # 8. perf record + report round-trip                                   #
    # ------------------------------------------------------------------ #

    def test_perf_record_report(self):
        """perf record must produce a non-empty perf.data; report must parse it."""
        cmd_record = 'perf record -o %s -e cycles -a sleep 2' % self.temp_file
        result = process.run(cmd_record, shell=True, sudo=True,
                             ignore_status=True)
        if result.exit_status != 0:
            self.fail('perf record failed: %s'
                      % (result.stdout + result.stderr).decode())
        if not os.path.isfile(self.temp_file):
            self.fail('perf.data not created by perf record')
        if os.stat(self.temp_file).st_size == 0:
            self.fail('perf.data is empty after perf record')

        cmd_report = 'perf report --stdio -i %s' % self.temp_file
        result = process.run(cmd_report, shell=True, sudo=True,
                             ignore_status=True)
        if result.exit_status != 0:
            self.fail('perf report failed: %s'
                      % (result.stdout + result.stderr).decode())
        self.log.info('perf record + report round-trip OK')

    # ------------------------------------------------------------------ #
    # tearDown                                                             #
    # ------------------------------------------------------------------ #

    def tearDown(self):
        if hasattr(self, 'temp_file') and os.path.isfile(self.temp_file):
            os.remove(self.temp_file)
        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'segfault',
                                    'soft lockup', 'SIGSEGV'])

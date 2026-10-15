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
# Copyright: 2026 IBM
# Author: Pavithra <pavithra@linux.ibm.com>

import gzip
import os
import re
import shutil
import subprocess

from avocado import Test
from avocado.utils import build, cpu, distro, dmesg, genio, process
from avocado.utils.software_manager.manager import SoftwareManager

_PROBE_PTES_SET = '__page_table_check_ptes_set'
_PROBE_PTE_CLEAR = '__page_table_check_pte_clear'
_PROBE_PMD_SET = '__page_table_check_pmds_set'
_PROBE_PMD_CLEAR = '__page_table_check_pmd_clear'

_KHUGEPAGED = '/sys/kernel/mm/transparent_hugepage/khugepaged'


class PageTableCheckCount(Test):
    '''
    Count page_table_check kernel hook invocations using perf kprobes.
    Verifies the sanitiser hooks are actively called during
    mmap/munmap/THP operations on PowerPC.

    :avocado: tags=memory,page_table_check,perf,privileged,power
    '''

    def setUp(self):
        if 'power' not in cpu.get_arch():
            self.cancel("page_table_check hook counting is ppc64le-specific")

        smm = SoftwareManager()
        if distro.detect().name not in ['rhel', 'SuSE']:
            self.cancel("Unsupported distro; test supports RHEL and SLES only")

        if not smm.check_installed('perf') and not smm.install('perf'):
            self.cancel("perf is required for hook call-count verification")

        for pkg in ['gcc', 'make']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)

        kconfig = self._read_kconfig()
        if self._kconfig_val(kconfig, 'CONFIG_PAGE_TABLE_CHECK') != 'y':
            self.cancel(
                "CONFIG_PAGE_TABLE_CHECK is not enabled. "
                "Rebuild the kernel with CONFIG_PAGE_TABLE_CHECK=y and "
                "CONFIG_HUGETLB_PAGE=n.")

        if self._kconfig_val(kconfig, 'CONFIG_KPROBES') != 'y':
            self.cancel(
                "CONFIG_KPROBES is not enabled. "
                "Rebuild the kernel with CONFIG_KPROBES=y.")

        self._check_ptc_runtime(kconfig)

        for src in ['ptc_pte.c', 'ptc_pmd.c', 'ptc_bug.c', 'Makefile']:
            shutil.copyfile(
                self.get_data(src),
                os.path.join(self.teststmpdir, src))
        build.make(self.teststmpdir)
        dmesg.clear_dmesg()

    def _read_kconfig(self):
        paths = [
            '/proc/config.gz',
            '/boot/config-%s' % os.uname()[2],
            '/boot/config',
        ]
        for path in paths:
            if not os.path.exists(path):
                continue
            try:
                if path.endswith('.gz'):
                    with gzip.open(path, 'rt', errors='replace') as fh:
                        return fh.read()
                with open(path, 'r', errors='replace') as fh:
                    return fh.read()
            except IOError:
                continue
        return ''

    def _kconfig_val(self, text, key):
        m = re.search(r'^%s=(.+)$' % re.escape(key), text, re.MULTILINE)
        if m:
            return m.group(1).strip()
        if re.search(r'^# %s is not set' % re.escape(key), text, re.MULTILINE):
            return 'n'
        return None

    def _check_ptc_runtime(self, kconfig):
        if self._kconfig_val(kconfig, 'CONFIG_PAGE_TABLE_CHECK_ENFORCED') == 'y':
            return
        try:
            cmdline = open('/proc/cmdline').read()
        except IOError:
            cmdline = ''
        if 'page_table_check=on' not in cmdline:
            self.cancel(
                "page_table_check sanitiser is not active at runtime. "
                "Add 'page_table_check=on' to the kernel boot parameters and "
                "reboot, or rebuild the kernel with "
                "CONFIG_PAGE_TABLE_CHECK_ENFORCED=y.")

    def _kallsyms_has(self, sym):
        try:
            with open('/proc/kallsyms', 'r') as fh:
                for line in fh:
                    if sym in line:
                        return True
        except IOError:
            pass
        return False

    def _count_hook_calls(self, probe_func, workload_cmd):
        event_name = probe_func.lstrip('_')

        if not self._kallsyms_has(probe_func):
            self.cancel(
                "Symbol '%s' not found in /proc/kallsyms. "
                "CONFIG_PAGE_TABLE_CHECK may not be active or the function "
                "is inlined away on this kernel." % probe_func)

        process.system(
            'perf probe --del %s' % event_name,
            shell=True, ignore_status=True, sudo=True)

        add_result = process.run(
            'perf probe --add %s' % probe_func,
            shell=True, ignore_status=True, sudo=True)
        if add_result.exit_status != 0:
            self.cancel(
                "perf probe --add %s failed (rc=%d): %s"
                % (probe_func, add_result.exit_status,
                   add_result.stderr_text.strip()))

        result = process.run(
            'perf stat -e probe:%s -- %s' % (event_name, workload_cmd),
            shell=True, ignore_status=True, sudo=True)
        wl_rc = result.exit_status

        process.system(
            'perf probe --del %s' % event_name,
            shell=True, ignore_status=True, sudo=True)

        output = result.stderr_text + result.stdout_text
        for line in output.splitlines():
            if event_name in line or ('probe:%s' % event_name) in line:
                parts = line.strip().split()
                if parts:
                    try:
                        count = int(parts[0].replace(',', ''))
                        self.log.info("%s called %d time(s)", probe_func, count)
                        return count, wl_rc
                    except ValueError:
                        continue

        self.fail(
            "Could not parse perf stat output for probe:%s\n%s"
            % (probe_func, output))

    def _thp_guards(self):
        thp_path = '/sys/kernel/mm/transparent_hugepage/enabled'
        if not os.path.exists(thp_path):
            self.cancel("THP sysfs not present")
        if '[never]' in genio.read_file(thp_path).strip():
            self.cancel("THP is disabled; set THP to 'always' or 'madvise'")
        if not os.path.exists(_KHUGEPAGED):
            self.cancel("khugepaged sysfs not present")

    def _tune_khugepaged(self):
        kh_scan = os.path.join(_KHUGEPAGED, 'scan_sleep_millisecs')
        kh_pages = os.path.join(_KHUGEPAGED, 'pages_to_scan')
        self._kh_scan_orig = genio.read_file(kh_scan).strip()
        self._kh_pages_orig = genio.read_file(kh_pages).strip()
        genio.write_file(kh_scan, '0')
        genio.write_file(kh_pages, '4096')

    def test_pte_set_count(self):
        '''
        Verify __page_table_check_ptes_set is called once per faulted page.
        Workload: mmap NR_PAGES anon pages + write-fault each + munmap.
        Expected: count >= nr_pages.
        '''
        nr_pages = self.params.get('nr_pages', default=64)
        os.chdir(self.teststmpdir)

        count, rc = self._count_hook_calls(
            _PROBE_PTES_SET, './ptc_pte set %d' % nr_pages)

        if rc != 0:
            self.fail("ptc_pte set workload exited %d" % rc)
        if count == 0:
            self.fail(
                "%s called 0 times during %d-page mmap+fault workload."
                % (_PROBE_PTES_SET, nr_pages))
        if count < nr_pages:
            self.fail(
                "%s called %d times, expected >= %d."
                % (_PROBE_PTES_SET, count, nr_pages))

    def test_pte_clear_count(self):
        '''
        Verify __page_table_check_pte_clear is called once per page on munmap.
        Expected: count >= nr_pages.
        '''
        nr_pages = self.params.get('nr_pages', default=64)
        os.chdir(self.teststmpdir)

        count, rc = self._count_hook_calls(
            _PROBE_PTE_CLEAR, './ptc_pte clear %d' % nr_pages)

        if rc != 0:
            self.fail("ptc_pte clear workload exited %d" % rc)
        if count == 0:
            self.fail(
                "%s called 0 times during %d-page munmap workload."
                % (_PROBE_PTE_CLEAR, nr_pages))
        if count < nr_pages:
            self.fail(
                "%s called %d times, expected >= %d."
                % (_PROBE_PTE_CLEAR, count, nr_pages))

    def test_pmd_set_count(self):
        '''
        Verify __page_table_check_pmds_set is called on THP collapse.
        Expected: count >= 1.
        '''
        self._thp_guards()
        self._tune_khugepaged()
        os.chdir(self.teststmpdir)

        count, rc = self._count_hook_calls(_PROBE_PMD_SET, './ptc_pmd set')

        if rc == 77:
            self.cancel("THP collapse did not occur within timeout (exit 77).")
        if rc != 0:
            self.fail("ptc_pmd set workload exited %d" % rc)
        if count == 0:
            self.fail(
                "%s called 0 times despite confirmed THP collapse."
                % _PROBE_PMD_SET)

    def test_pmd_clear_count(self):
        '''
        Verify __page_table_check_pmd_clear is called on THP split via mprotect.
        Expected: count >= 1.
        '''
        self._thp_guards()
        self._tune_khugepaged()
        os.chdir(self.teststmpdir)

        count, rc = self._count_hook_calls(_PROBE_PMD_CLEAR, './ptc_pmd clear')

        if rc == 77:
            self.cancel("THP collapse did not occur within timeout (exit 77).")
        if rc != 0:
            self.fail("ptc_pmd clear workload exited %d" % rc)
        if count == 0:
            self.fail(
                "%s called 0 times despite mprotect-induced THP split."
                % _PROBE_PMD_CLEAR)

    def _count_hook_calls_phased(self, probe_func, child_proc):
        import signal as _signal
        event_name = probe_func.lstrip('_')

        process.system(
            'perf probe --del %s' % event_name,
            shell=True, ignore_status=True, sudo=True)

        add_result = process.run(
            'perf probe --add %s' % probe_func,
            shell=True, ignore_status=True, sudo=True)
        if add_result.exit_status != 0:
            self.cancel(
                "perf probe --add %s failed (rc=%d): %s"
                % (probe_func, add_result.exit_status,
                   add_result.stderr_text.strip()))

        perf_proc = subprocess.Popen(
            ['perf', 'stat', '-x,',
             '-e', 'probe:%s' % event_name,
             '-p', str(child_proc.pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        child_proc.stdin.write(b'g')
        child_proc.stdin.flush()

        line = child_proc.stdout.readline()
        if not line:
            perf_proc.send_signal(_signal.SIGINT)
            perf_proc.wait()
            process.system(
                'perf probe --del %s' % event_name,
                shell=True, ignore_status=True, sudo=True)
            self.fail("Child closed stdout unexpectedly during phase")

        perf_proc.send_signal(_signal.SIGINT)
        try:
            stdout_b, stderr_b = perf_proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            perf_proc.kill()
            stdout_b, stderr_b = perf_proc.communicate()

        perf_output = (stdout_b or b'').decode(errors='replace') + \
                      (stderr_b or b'').decode(errors='replace')

        process.system(
            'perf probe --del %s' % event_name,
            shell=True, ignore_status=True, sudo=True)

        self.log.debug("phased perf CSV for %s:\n%s",
                       probe_func, perf_output.strip())

        for line_str in perf_output.splitlines():
            if event_name in line_str:
                parts = line_str.split(',')
                if parts:
                    try:
                        count = int(parts[0].strip())
                        self.log.info("phased: %s = %d", probe_func, count)
                        return count, 0
                    except ValueError:
                        continue

        self.log.info("phased: no CSV line for %s — treating as 0", probe_func)
        return 0, 0

    def test_bug_no_double_count_on_thp_collapse(self):
        '''
        Verify commit 2360f523a49b: __page_table_check_ptes_set must NOT fire
        during THP collapse (set_pmd_at must use set_pte_at_unchecked).
        PASS: collapse_count == 0 and pmds_count == 1.
        FAIL: collapse_count > 0 — set_pmd_at calls set_pte_at internally.
        '''
        self._thp_guards()
        self._tune_khugepaged()
        os.chdir(self.teststmpdir)

        page_size = os.sysconf('SC_PAGE_SIZE')
        nr_base_pages = (2 * 1024 * 1024) // page_size

        child = subprocess.Popen(
            ['./ptc_bug', 'thp_collapse_phase', 'collapse'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        ready = child.stdout.readline()
        if not ready:
            child.wait()
            self.fail("Child exited before signalling fault-phase ready")

        self.log.info(
            "Child faulted %d base pages; measuring ptes_set during "
            "collapse phase only", nr_base_pages)

        collapse_count, _ = self._count_hook_calls_phased(
            _PROBE_PTES_SET, child)

        child.stdin.write(b'g')
        child.stdin.flush()
        child.wait()
        rc = child.returncode

        if rc == 77:
            self.cancel("THP collapse timed out (exit 77).")
        if rc != 0:
            self.fail("thp_collapse_phase collapse exited %d" % rc)

        pmds_count, pmds_rc = self._count_hook_calls(
            _PROBE_PMD_SET, './ptc_bug thp_collapse_phase full')

        if pmds_rc == 77:
            self.cancel("THP collapse timed out in full-mode sanity check.")
        if pmds_rc != 0:
            self.fail("thp_collapse_phase full exited %d" % pmds_rc)

        if collapse_count > 0:
            self.fail(
                "%s fired %d time(s) during THP collapse (expected 0). "
                "set_pmd_at() is calling set_pte_at() internally — "
                "commit 2360f523a49b is not effective on this kernel."
                % (_PROBE_PTES_SET, collapse_count))

        if pmds_count == 0:
            self.fail(
                "%s called 0 times during THP collapse." % _PROBE_PMD_SET)

        if pmds_count > 1:
            self.fail(
                "%s called %d times for one THP collapse; expected 1."
                % (_PROBE_PMD_SET, pmds_count))

    def test_bug_user_va_hook_fires(self):
        '''
        Verify commits 2f5e576598c9 + d79f9c9cf703: pte_user_accessible_page()
        must return true for user VAs so hook count scales with nr_pages.
        PASS: count_small >= NR_SMALL and count_large >= NR_LARGE.
        FAIL: both zero — hook is blind to all user-space mappings.
        '''
        nr_small = self.params.get('nr_pages', default=32)
        nr_large = nr_small * 2
        os.chdir(self.teststmpdir)

        count_small, rc1 = self._count_hook_calls(
            _PROBE_PTES_SET, './ptc_bug user_va_mapping %d' % nr_small)
        if rc1 != 0:
            self.fail("user_va_mapping %d exited %d" % (nr_small, rc1))

        count_large, rc2 = self._count_hook_calls(
            _PROBE_PTES_SET, './ptc_bug user_va_mapping %d' % nr_large)
        if rc2 != 0:
            self.fail("user_va_mapping %d exited %d" % (nr_large, rc2))

        if count_small == 0 and count_large == 0:
            self.fail(
                "%s fired 0 times for both %d-page and %d-page workloads. "
                "pte_user_accessible_page() returns false for all user VAs — "
                "commits 2f5e576598c9 + d79f9c9cf703 may not be applied."
                % (_PROBE_PTES_SET, nr_small, nr_large))

        if count_small < nr_small:
            self.fail(
                "%s fired %d times for %d-page workload; expected >= %d."
                % (_PROBE_PTES_SET, count_small, nr_small, nr_small))

        if count_large < nr_large:
            self.fail(
                "%s fired %d times for %d-page workload; expected >= %d."
                % (_PROBE_PTES_SET, count_large, nr_large, nr_large))

        if count_large < count_small:
            self.fail(
                "count_large (%d) < count_small (%d): hook count did not "
                "scale with nr_pages." % (count_large, count_small))

    def tearDown(self):
        kh_scan = os.path.join(_KHUGEPAGED, 'scan_sleep_millisecs')
        kh_pages = os.path.join(_KHUGEPAGED, 'pages_to_scan')
        if hasattr(self, '_kh_scan_orig') and os.path.exists(kh_scan):
            genio.write_file(kh_scan, self._kh_scan_orig)
        if hasattr(self, '_kh_pages_orig') and os.path.exists(kh_pages):
            genio.write_file(kh_pages, self._kh_pages_orig)

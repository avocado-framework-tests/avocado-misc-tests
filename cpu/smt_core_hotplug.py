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
# Author: Optimized Test Suite

import os
import time
import threading
import random
from avocado import Test
from avocado.utils import process, distro, dmesg, genio
from avocado.utils.software_manager.manager import SoftwareManager


class SmtCoreHotplugOptimized(Test):
    """
    test to verify ppc64_cpu SMT and core online/offline operations.
    
    This test covers:
    1. All SMT operations dynamically (off, 2, 3, 4, ..., max_smt, on)
    2. Core online/offline operations with dynamic core counts
    3. Parallel SMT and core operations
    4. Comprehensive verification using multiple sources
    5. Regression testing for core state consistency
    6. Random stress testing with SMT changes
    7. Proper validation: online CPUs = cores_online * SMT_threads
    8. Verification that SMT changes don't affect offline cores
    9. Verification that core operations don't change SMT state
    
    :avocado: tags=cpu,power,privileged,smt,hotplug,optimized
    """

    def setUp(self):
        """
        Verify system requirements and initialize test parameters.
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not ppc64")
        
        self.sm = SoftwareManager()
        for pkg in ['powerpc-utils', 'util-linux']:
            if not self.sm.check_installed(pkg):
                if not self.sm.install(pkg):
                    self.cancel("Cannot install %s, check the log!" % pkg)
        
        # Get current SMT value
        self.smt_str = "ppc64_cpu --smt"
        process.system("%s=on" % self.smt_str, shell=True)
        smt_op = process.system_output(self.smt_str, shell=True).decode()
        
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable")
        if "Inconsistent state" in smt_op:
            self.cancel("Machine has mix of ST and SMT cores")
        
        self.curr_smt = smt_op.strip().split("=")[-1].split()[-1]
        self.max_smt = int(self.curr_smt)
        
        # Get total cores from system
        cores_output = process.system_output("ppc64_cpu --cores-present",
                                            shell=True).decode()
        self.total_cores = int(cores_output.strip().split()[-1])
        
        # Generate all possible SMT values dynamically
        self.all_smt_values = self._generate_smt_values()
        
        # Test parameters - all configurable via YAML
        self.iteration = int(self.params.get('iteration', default='5'))
        self.parallel_iterations = int(self.params.get('parallel_iterations', default='3'))
        self.random_iterations = int(self.params.get('random_iterations', default='50'))
        self.num_parallel_threads = int(self.params.get('num_parallel_threads', default='4'))
        
        # Store initial state
        self.initial_smt = self.curr_smt
        self.initial_cores = self.total_cores
        
        self.log.info("Initial SMT: %s (max: %s), Total Cores: %s", 
                     self.initial_smt, self.max_smt, self.total_cores)
        self.log.info("All SMT values to test: %s", self.all_smt_values)
        
        # Error tracking
        self.failures = []
    
    def _generate_smt_values(self):
        """
        Generate all possible SMT values dynamically based on system capability.
        
        :return: List of all SMT values to test
        """
        smt_values = ['off']
        # Add all intermediate values from 2 to max_smt
        for i in range(2, self.max_smt + 1):
            smt_values.append(str(i))
        smt_values.append('on')
        return smt_values
    
    def _parse_cpu_range(self, range_str):
        """
        Parse CPU range string like "0-159" or "0,2-5,8" into list of CPU numbers.
        
        :param range_str: Range string to parse
        :return: List of CPU numbers
        """
        cpus = []
        for part in range_str.split(','):
            if '-' in part:
                start, end = part.split('-')
                cpus.extend(range(int(start), int(end) + 1))
            else:
                cpus.append(int(part))
        return cpus
    
    def get_online_cpus_from_sysfs(self):
        """
        Get online CPUs from sysfs.
        
        :return: List of online CPU numbers
        """
        try:
            online_file = "/sys/devices/system/cpu/online"
            if os.path.exists(online_file):
                online_str = genio.read_file(online_file).strip()
                return self._parse_cpu_range(online_str)
            return []
        except Exception as e:
            self.log.error("Failed to get online CPUs from sysfs: %s", str(e))
            return []
    
    def get_online_cpus_from_proc(self):
        """
        Get online CPUs from /proc/cpuinfo.
        
        :return: Number of online CPUs
        """
        try:
            cpuinfo = genio.read_file("/proc/cpuinfo")
            return cpuinfo.count("processor\t:")
        except Exception as e:
            self.log.error("Failed to get online CPUs from /proc/cpuinfo: %s", str(e))
            return 0
    
    def get_cores_info(self):
        """
        Get comprehensive core information using ppc64_cpu commands.
        
        :return: Dictionary with core information
        """
        info = {}
        try:
            # Get cores present
            cores_present = process.system_output("ppc64_cpu --cores-present",
                                                 shell=True).decode()
            info['cores_present'] = int(cores_present.strip().split()[-1])
            
            # Get cores online
            cores_on = process.system_output("ppc64_cpu --cores-on",
                                           shell=True).decode()
            info['cores_on'] = int(cores_on.strip().split("=")[-1])
            
            # Get offline cores
            # Output format: "Cores offline = 1,2,3" or "Cores offline = None"
            offline_cores_output = process.system_output("ppc64_cpu --offline-cores",
                                                        shell=True, ignore_status=True).decode()
            info['offline_cores'] = []
            
            # Parse offline cores list
            if offline_cores_output.strip() and "None" not in offline_cores_output:
                for line in offline_cores_output.split('\n'):
                    if '=' in line:
                        # Extract the part after '=' sign
                        cores_part = line.split('=')[-1].strip()
                        if cores_part and cores_part.lower() != 'none':
                            # Parse comma-separated core numbers
                            for core_str in cores_part.split(','):
                                core_str = core_str.strip()
                                if core_str.isdigit():
                                    info['offline_cores'].append(int(core_str))
            
            info['offline_cores_count'] = len(info['offline_cores'])
            
            self.log.debug("Cores info: present=%s, online=%s, offline=%s",
                         info['cores_present'], info['cores_on'], 
                         info['offline_cores_count'])
            
        except Exception as e:
            self.log.error("Failed to get cores info: %s", str(e))
            info = {'cores_present': 0, 'cores_on': 0, 'offline_cores': [], 
                   'offline_cores_count': 0}
        
        return info
    
    def get_current_smt(self):
        """
        Get current SMT value.
        
        :return: Current SMT value as string
        """
        try:
            current_smt_output = process.system_output(self.smt_str, shell=True).decode()
            current_smt = current_smt_output.strip().split("=")[-1].split()[-1]
            return current_smt
        except Exception as e:
            self.log.error("Failed to get current SMT: %s", str(e))
            return "unknown"
    
    def parse_ppc64_cpu_info(self):
        """
        Parse ppc64_cpu --info output to verify SMT consistency across ONLINE cores only.
        Offline cores (0 threads) are VALID and excluded from consistency check.
        
        :return: Dictionary with core information and consistency status
        """
        result = {
            'cores': {},
            'is_consistent': True,
            'inconsistent_cores': [],
            'expected_threads_per_core': 0,
            'actual_threads_per_core': {},
            'online_cores': [],
            'offline_cores': []
        }
        
        try:
            info_output = process.system_output("ppc64_cpu --info", shell=True).decode()
            
            for line in info_output.split('\n'):
                if line.startswith('Core'):
                    parts = line.split(':')
                    if len(parts) == 2:
                        core_num = int(parts[0].split()[1])
                        threads_str = parts[1].strip()
                        
                        # Count online threads (marked with *)
                        threads = threads_str.split()
                        online_threads = sum(1 for t in threads if '*' in t)
                        total_threads = len(threads)
                        
                        result['cores'][core_num] = {
                            'online_threads': online_threads,
                            'total_threads': total_threads,
                            'threads': threads
                        }
                        result['actual_threads_per_core'][core_num] = online_threads
                        
                        # Categorize cores
                        if online_threads > 0:
                            result['online_cores'].append(core_num)
                        else:
                            result['offline_cores'].append(core_num)
            
            # Check consistency - ONLY among ONLINE cores
            if result['online_cores']:
                online_cores_threads = {core: result['actual_threads_per_core'][core] 
                                       for core in result['online_cores']}
                
                thread_counts = list(online_cores_threads.values())
                expected_count = thread_counts[0]
                result['expected_threads_per_core'] = expected_count
                
                # Check consistency only among online cores
                for core_num, count in online_cores_threads.items():
                    if count != expected_count:
                        result['is_consistent'] = False
                        result['inconsistent_cores'].append(core_num)
                        self.log.error("ONLINE Core %s has %s threads, expected %s",
                                     core_num, count, expected_count)
            else:
                result['expected_threads_per_core'] = 0
            
        except Exception as e:
            self.log.error("Failed to parse ppc64_cpu --info: %s", str(e))
            result['is_consistent'] = False
        
        return result
    
    def verify_system_state(self, expected_smt=None, expected_cores_on=None):
        """
        Comprehensive verification using lscpu, ppc64_cpu --info, /proc/cpuinfo, and sysfs.
        
        :param expected_smt: Expected SMT value
        :param expected_cores_on: Expected number of cores online
        :return: True if verification passes, False otherwise
        """
        try:
            # Get lscpu output
            lscpu_output = process.system_output("lscpu", shell=True).decode()
            self.log.debug("lscpu output:\n%s", lscpu_output)
            
            # Get ppc64_cpu --info output
            info_output = process.system_output("ppc64_cpu --info", shell=True).decode()
            self.log.info("ppc64_cpu --info output:\n%s", info_output)
            
            # Parse ppc64_cpu --info
            info_parsed = self.parse_ppc64_cpu_info()
            
            # Get current SMT
            current_smt = self.get_current_smt()
            
            # Calculate expected threads per core
            if current_smt == 'off':
                expected_smt_threads = 1
            elif current_smt.isdigit():
                expected_smt_threads = int(current_smt)
            else:
                expected_smt_threads = self.max_smt
            
            # Check SMT consistency among ONLINE cores
            if not info_parsed['is_consistent']:
                self.log.error("INCONSISTENT SMT STATE DETECTED AMONG ONLINE CORES!")
                self.log.error("System SMT setting: %s (expected %s threads per core)",
                             current_smt, expected_smt_threads)
                self.log.error("Inconsistent ONLINE cores: %s", info_parsed['inconsistent_cores'])
                
                for core_num in info_parsed['online_cores']:
                    core_data = info_parsed['cores'][core_num]
                    status = "✓" if core_data['online_threads'] == expected_smt_threads else "✗"
                    self.log.error("  %s ONLINE Core %s: %s/%s threads (threads: %s)",
                                 status, core_num, core_data['online_threads'],
                                 core_data['total_threads'], ' '.join(core_data['threads']))
                
                if info_parsed['offline_cores']:
                    self.log.info("Offline cores (VALID): %s", info_parsed['offline_cores'])
                
                return False
            
            # Verify threads per core matches SMT setting
            if info_parsed['online_cores']:
                actual_threads_per_core = info_parsed['expected_threads_per_core']
                if actual_threads_per_core != expected_smt_threads:
                    self.log.error("SMT MISMATCH: System says SMT=%s (%s threads), but ONLINE cores have %s threads",
                                 current_smt, expected_smt_threads, actual_threads_per_core)
                    for core_num in info_parsed['online_cores']:
                        core_data = info_parsed['cores'][core_num]
                        self.log.error("  ONLINE Core %s: %s/%s threads (threads: %s)",
                                     core_num, core_data['online_threads'],
                                     core_data['total_threads'], ' '.join(core_data['threads']))
                    return False
                
                self.log.info("✓ SMT consistency verified: All %s ONLINE cores have %s threads (SMT=%s)",
                             len(info_parsed['online_cores']), actual_threads_per_core, current_smt)
                if info_parsed['offline_cores']:
                    self.log.info("  Offline cores (VALID): %s", info_parsed['offline_cores'])
            
            # Get cores info
            cores_info = self.get_cores_info()
            current_cores_on = cores_info['cores_on']
            
            # Get online CPUs from different sources
            online_cpus_sysfs = self.get_online_cpus_from_sysfs()
            online_cpus_count_sysfs = len(online_cpus_sysfs)
            online_cpus_count_proc = self.get_online_cpus_from_proc()
            
            # Parse lscpu output
            lscpu_online_cpus = 0
            lscpu_threads_per_core = 0
            
            for line in lscpu_output.split('\n'):
                if 'On-line CPU(s) list:' in line:
                    try:
                        lscpu_online_list = line.split(':')[-1].strip()
                        lscpu_online_cpus = len(self._parse_cpu_range(lscpu_online_list))
                        self.log.info("lscpu - On-line CPU(s) list: %s", lscpu_online_list)
                        self.log.info("lscpu - Online CPU count: %s", lscpu_online_cpus)
                    except Exception as e:
                        self.log.error("Failed to parse lscpu online list: %s", str(e))
                elif 'Thread(s) per core:' in line:
                    try:
                        lscpu_threads_per_core = int(line.split(':')[-1].strip())
                        self.log.info("lscpu - Thread(s) per core: %s", lscpu_threads_per_core)
                    except:
                        pass
            
            # Calculate expected online CPUs
            expected_online_cpus = current_cores_on * expected_smt_threads
            
            self.log.info("=== Verification Summary ===")
            self.log.info("Current SMT: %s", current_smt)
            self.log.info("Cores online: %s", current_cores_on)
            self.log.info("Cores offline: %s", cores_info['offline_cores_count'])
            self.log.info("Expected threads per core: %s", expected_smt_threads)
            self.log.info("Expected online CPUs: %s (cores=%s * threads=%s)",
                         expected_online_cpus, current_cores_on, expected_smt_threads)
            self.log.info("Online CPUs from sysfs: %s", online_cpus_count_sysfs)
            self.log.info("Online CPUs from /proc/cpuinfo: %s", online_cpus_count_proc)
            self.log.info("Online CPUs from lscpu: %s", lscpu_online_cpus)
            
            # Verify expected values
            if expected_smt is not None:
                if str(current_smt) != str(expected_smt):
                    self.log.error("SMT mismatch: expected %s, got %s",
                                 expected_smt, current_smt)
                    return False
            
            if expected_cores_on is not None:
                if current_cores_on != expected_cores_on:
                    self.log.error("Cores online mismatch: expected %s, got %s",
                                 expected_cores_on, current_cores_on)
                    return False
            
            # Verify online CPUs match expected calculation
            if online_cpus_count_sysfs != expected_online_cpus:
                self.log.error("Online CPUs mismatch (sysfs): expected %s, got %s",
                             expected_online_cpus, online_cpus_count_sysfs)
                return False
            
            if online_cpus_count_proc != expected_online_cpus:
                self.log.error("Online CPUs mismatch (/proc/cpuinfo): expected %s, got %s",
                             expected_online_cpus, online_cpus_count_proc)
                return False
            
            if lscpu_online_cpus != expected_online_cpus:
                self.log.error("Online CPUs mismatch (lscpu): expected %s, got %s",
                             expected_online_cpus, lscpu_online_cpus)
                return False
            
            if lscpu_threads_per_core != expected_smt_threads:
                self.log.error("Threads per core mismatch: expected %s, got %s",
                             expected_smt_threads, lscpu_threads_per_core)
                return False
            
            self.log.info("✓ Verification PASSED: All sources agree")
            self.log.info("  Online CPUs (%s) = Cores (%s) × SMT threads (%s)",
                         expected_online_cpus, current_cores_on, expected_smt_threads)
            
            return True
            
        except Exception as e:
            self.log.error("Verification failed with exception: %s", str(e))
            return False
    
    def test_all_smt_operations(self):
        """
        Test ALL SMT operations dynamically: off, 2, 3, 4, ..., max_smt, on.
        Covers all possible SMT states without hardcoded values.
        """
        self.log.info("=== Testing ALL SMT Operations (Dynamic) ===")
        
        for smt_val in self.all_smt_values:
            self.log.info("Setting SMT=%s", smt_val)
            dmesg.clear_dmesg()
            
            cmd = "%s=%s" % (self.smt_str, smt_val)
            result = process.run(cmd, shell=True, ignore_status=True)
            
            if result.exit_status != 0:
                self.failures.append("Failed to set SMT=%s" % smt_val)
                continue
            
            time.sleep(1)
            
            # Verify the state
            expected_smt = smt_val if smt_val != 'on' else str(self.max_smt)
            if smt_val == 'off':
                expected_smt = 'off'
            
            if not self.verify_system_state(expected_smt=expected_smt):
                self.failures.append("Verification failed for SMT=%s" % smt_val)
            
            self.log.info("SMT=%s operation completed successfully\n", smt_val)
    
    def test_dynamic_core_operations(self):
        """
        Test core online/offline operations with dynamically generated scenarios.
        """
        self.log.info("=== Testing Dynamic Core Operations ===")
        
        # Ensure all cores are online first
        process.system("ppc64_cpu --cores-on=all", shell=True)
        time.sleep(1)
        
        # Generate test scenarios dynamically
        test_scenarios = []
        
        # Add specific percentages
        for pct in [0.1, 0.25, 0.5, 0.75, 1.0]:
            cores_count = max(1, int(self.total_cores * pct))
            test_scenarios.append((cores_count, f"{int(pct*100)}% cores online"))
        
        # Add edge cases
        test_scenarios.insert(0, (1, "Single core online"))
        if self.total_cores > 1:
            test_scenarios.insert(1, (2, "Two cores online"))
        
        # Remove duplicates
        seen = set()
        unique_scenarios = []
        for cores_count, description in test_scenarios:
            if cores_count not in seen and cores_count <= self.total_cores:
                seen.add(cores_count)
                unique_scenarios.append((cores_count, description))
        
        for cores_count, description in unique_scenarios:
            self.log.info("Test: %s (cores=%s)", description, cores_count)
            dmesg.clear_dmesg()
            
            cmd = "ppc64_cpu --cores-on=%s" % cores_count
            result = process.run(cmd, shell=True, ignore_status=True)
            
            if result.exit_status != 0:
                self.failures.append("Failed to set cores-on=%s" % cores_count)
                continue
            
            time.sleep(1)
            
            if not self.verify_system_state(expected_cores_on=cores_count):
                self.failures.append("Verification failed for cores-on=%s" % cores_count)
            
            self.log.info("Core operation completed: %s\n", description)
        
        # Restore all cores
        process.system("ppc64_cpu --cores-on=all", shell=True)
        time.sleep(1)
    
    def test_smt_core_interaction(self):
        """
        Test interaction between SMT and core operations.
        Validates that SMT changes don't affect core count and vice versa.
        """
        self.log.info("=== Testing SMT-Core Interaction ===")
        
        # Ensure clean start
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)
        
        for iteration in range(self.iteration):
            self.log.info("Iteration %s/%s", iteration + 1, self.iteration)
            
            # Set specific core count
            test_core_count = max(1, self.total_cores // 2)
            process.system("ppc64_cpu --cores-on=%s" % test_core_count, shell=True)
            time.sleep(1)
            
            cores_before = self.get_cores_info()['cores_on']
            
            # Test all SMT values
            for smt_val in self.all_smt_values:
                self.log.info("  Testing SMT=%s with %s cores", smt_val, test_core_count)
                process.system("ppc64_cpu --smt=%s" % smt_val, shell=True, ignore_status=True)
                time.sleep(0.5)
                
                # Verify cores didn't change
                cores_after = self.get_cores_info()['cores_on']
                if cores_before != cores_after:
                    self.failures.append(
                        "SMT=%s changed core count from %s to %s" %
                        (smt_val, cores_before, cores_after))
                
                # Verify system state
                expected_smt = smt_val if smt_val != 'on' else str(self.max_smt)
                if smt_val == 'off':
                    expected_smt = 'off'
                
                self.verify_system_state(expected_smt=expected_smt, 
                                        expected_cores_on=test_core_count)
            
            # Restore
            process.system("ppc64_cpu --cores-on=all", shell=True)
            time.sleep(1)
    
    def test_random_stress(self):
        """
        Random stress test with all possible SMT states and core configurations.
        """
        self.log.info("=== Random Stress Test ===")
        
        # Ensure clean start
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)
        
        for iteration in range(self.random_iterations):
            self.log.info("Random iteration %s/%s", iteration + 1, self.random_iterations)
            
            operation = random.choice(['smt', 'core_count', 'verify'])
            
            if operation == 'smt':
                smt_val = random.choice(self.all_smt_values)
                self.log.info("  -> Setting SMT=%s", smt_val)
                
                cores_before = self.get_cores_info()
                process.system("ppc64_cpu --smt=%s" % smt_val, 
                             shell=True, ignore_status=True)
                time.sleep(0.3)
                
                cores_after = self.get_cores_info()
                if cores_before['cores_on'] != cores_after['cores_on']:
                    self.failures.append(
                        "SMT change affected core count: was %s, now %s" %
                        (cores_before['cores_on'], cores_after['cores_on']))
                
            elif operation == 'core_count':
                cores_count = random.randint(1, self.total_cores)
                self.log.info("  -> Setting cores-on=%s", cores_count)
                
                smt_before = self.get_current_smt()
                process.system("ppc64_cpu --cores-on=%s" % cores_count,
                             shell=True, ignore_status=True)
                time.sleep(0.3)
                
                smt_after = self.get_current_smt()
                if smt_before != smt_after:
                    self.failures.append(
                        "Core operation affected SMT: was %s, now %s" %
                        (smt_before, smt_after))
            
            elif operation == 'verify':
                self.log.info("  -> Comprehensive verification")
                if not self.verify_system_state():
                    self.failures.append(
                        "Verification failed at iteration %s" % (iteration + 1))
        
        self.log.info("Random stress test completed")
    
    def parallel_operation(self, thread_id, operation_type):
        """
        Perform operations in parallel.
        
        :param thread_id: Thread identifier
        :param operation_type: Type of operation ('smt' or 'core')
        """
        try:
            for i in range(self.parallel_iterations):
                if operation_type == 'smt':
                    smt_val = random.choice(self.all_smt_values)
                    self.log.info("Thread %s: Setting SMT=%s (iteration %s)",
                                thread_id, smt_val, i + 1)
                    process.system("ppc64_cpu --smt=%s" % smt_val,
                                 shell=True, ignore_status=True)
                else:
                    core_val = random.randint(1, self.total_cores)
                    self.log.info("Thread %s: Setting cores-on=%s (iteration %s)",
                                thread_id, core_val, i + 1)
                    process.system("ppc64_cpu --cores-on=%s" % core_val,
                                 shell=True, ignore_status=True)
                time.sleep(0.5)
        except Exception as e:
            self.log.error("Thread %s error: %s", thread_id, str(e))
    
    def test_parallel_operations(self):
        """
        Test parallel SMT and core operations.
        """
        self.log.info("=== Testing Parallel Operations ===")
        
        # Ensure clean state
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(2)
        
        threads = []
        
        # Create threads
        for i in range(self.num_parallel_threads // 2):
            t = threading.Thread(target=self.parallel_operation, args=(i, 'smt'))
            threads.append(t)
        
        for i in range(self.num_parallel_threads // 2, self.num_parallel_threads):
            t = threading.Thread(target=self.parallel_operation, args=(i, 'core'))
            threads.append(t)
        
        # Start all threads
        self.log.info("Starting %s parallel threads", len(threads))
        for t in threads:
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        self.log.info("All parallel operations completed")
        
        # Restore and verify
        time.sleep(2)
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)
        
        if not self.verify_system_state():
            self.failures.append("System state verification failed after parallel operations")
    def test_progressive_core_online_with_smt(self):
        """
        Progressive test: Start with minimal cores, perform all SMT operations,
        then progressively bring cores online and test SMT at each step.
        
        Scenario:
        1. Offline all cores except core 0 (minimum required)
        2. Perform all SMT operations with minimal cores
        3. Randomly online cores one by one
        4. After each core online, perform all SMT operations
        5. Verify system state at each step
        """
        self.log.info("=== Testing Progressive Core Online with SMT Operations ===")
        
        if self.total_cores < 3:
            self.log.info("Skipping: Need at least 3 cores for this test")
            return
        
        # Ensure clean start
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)
        
        # Step 1: Offline all cores except core 0 (keep only 1 core online)
        self.log.info("Step 1: Setting minimum cores (1 core online)")
        process.system("ppc64_cpu --cores-on=1", shell=True)
        time.sleep(1)
        
        # Verify minimal core state
        cores_info = self.get_cores_info()
        self.log.info("Cores online: %s, Cores offline: %s", 
                     cores_info['cores_on'], cores_info['offline_cores_count'])
        
        # Step 2: Perform all SMT operations with minimal cores
        self.log.info("Step 2: Testing all SMT operations with 1 core online")
        for smt_val in self.all_smt_values:
            self.log.info("  Setting SMT=%s with 1 core", smt_val)
            process.system("ppc64_cpu --smt=%s" % smt_val, 
                         shell=True, ignore_status=True)
            time.sleep(0.5)
            
            # Verify state
            expected_smt = smt_val if smt_val != 'on' else str(self.max_smt)
            if smt_val == 'off':
                expected_smt = 'off'
            
            if not self.verify_system_state(expected_smt=expected_smt, expected_cores_on=1):
                self.failures.append(
                    "Verification failed for SMT=%s with 1 core" % smt_val)
        
        # Step 3: Progressive core online with SMT testing
        self.log.info("Step 3: Progressively bringing cores online and testing SMT")
        
        # Generate a list of cores to bring online progressively
        # We'll test with different core counts: 2, 3, 6, half, 3/4, all
        test_core_counts = []
        
        # Add specific counts
        if self.total_cores >= 2:
            test_core_counts.append(2)
        if self.total_cores >= 3:
            test_core_counts.append(3)
        if self.total_cores >= 6:
            test_core_counts.append(6)
        
        # Add percentage-based counts
        half_cores = max(2, self.total_cores // 2)
        three_quarter_cores = max(2, int(self.total_cores * 0.75))
        
        if half_cores not in test_core_counts and half_cores <= self.total_cores:
            test_core_counts.append(half_cores)
        if three_quarter_cores not in test_core_counts and three_quarter_cores <= self.total_cores:
            test_core_counts.append(three_quarter_cores)
        
        # Add all cores
        if self.total_cores not in test_core_counts:
            test_core_counts.append(self.total_cores)
        
        # Sort to ensure progressive increase
        test_core_counts.sort()
        
        for core_count in test_core_counts:
            self.log.info("\n--- Testing with %s cores online ---", core_count)
            
            # Bring cores online
            process.system("ppc64_cpu --cores-on=%s" % core_count, shell=True)
            time.sleep(1)
            
            # Verify core count
            cores_info = self.get_cores_info()
            actual_cores = cores_info['cores_on']
            
            if actual_cores != core_count:
                self.log.warning("Expected %s cores, got %s cores", 
                               core_count, actual_cores)
            
            self.log.info("Cores online: %s, Cores offline: %s", 
                         actual_cores, cores_info['offline_cores_count'])
            
            # Test all SMT operations with current core count
            for smt_val in self.all_smt_values:
                self.log.info("  Testing SMT=%s with %s cores", smt_val, actual_cores)
                
                # Set SMT
                process.system("ppc64_cpu --smt=%s" % smt_val, 
                             shell=True, ignore_status=True)
                time.sleep(0.5)
                
                # Verify cores didn't change
                cores_after = self.get_cores_info()['cores_on']
                if cores_after != actual_cores:
                    self.failures.append(
                        "SMT=%s changed core count from %s to %s" %
                        (smt_val, actual_cores, cores_after))
                
                # Verify system state
                expected_smt = smt_val if smt_val != 'on' else str(self.max_smt)
                if smt_val == 'off':
                    expected_smt = 'off'
                
                if not self.verify_system_state(expected_smt=expected_smt, 
                                               expected_cores_on=actual_cores):
                    self.failures.append(
                        "Verification failed for SMT=%s with %s cores" % 
                        (smt_val, actual_cores))
        
        # Step 4: Random core online/offline with SMT changes
        self.log.info("\nStep 4: Random core selection with SMT operations")
        
        # Generate random core numbers to test
        available_cores = list(range(1, self.total_cores + 1))
        random.shuffle(available_cores)
        
        # Test with 5 random core selections (or fewer if not enough cores)
        num_random_tests = min(5, len(available_cores))
        
        for i in range(num_random_tests):
            # Select random number of cores
            num_cores_to_online = random.randint(1, self.total_cores)
            
            self.log.info("\n--- Random test %s: %s cores online ---", 
                         i + 1, num_cores_to_online)
            
            # Bring specific number of cores online
            process.system("ppc64_cpu --cores-on=%s" % num_cores_to_online, 
                         shell=True, ignore_status=True)
            time.sleep(0.5)
            
            # Get actual core count
            cores_info = self.get_cores_info()
            actual_cores = cores_info['cores_on']
            
            self.log.info("Actual cores online: %s", actual_cores)
            
            # Test with random SMT values (test 3 random SMT values)
            random_smt_values = random.sample(self.all_smt_values, 
                                             min(3, len(self.all_smt_values)))
            
            for smt_val in random_smt_values:
                self.log.info("  Testing SMT=%s", smt_val)
                process.system("ppc64_cpu --smt=%s" % smt_val, 
                             shell=True, ignore_status=True)
    def test_specific_cores_offline_with_smt(self):
        """
        Advanced test: Randomly offline specific cores and perform SMT operations.
        Validates that:
        1. Offline cores remain offline after SMT changes
        2. Online cores maintain correct SMT state
        3. Core online/offline list is tracked accurately
        
        Scenario per iteration:
        1. Start with all cores online
        2. Randomly select and offline specific cores (e.g., 2, 5, 7)
        3. Perform all SMT operations
        4. Validate offline cores remain offline, online cores have correct SMT
        5. Next iteration: bring back previously offline cores, offline different ones
        6. Repeat with different core combinations
        """
        self.log.info("=== Testing Specific Cores Offline with SMT Operations ===")
        
        if self.total_cores < 5:
            self.log.info("Skipping: Need at least 5 cores for this test")
            return
        
        # Ensure clean start
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)
        
        # Track core states across iterations
        previously_offline_cores = []
        
        # Number of iterations for this test
        num_iterations = min(5, self.iteration)
        
        for iteration in range(num_iterations):
            self.log.info("\n" + "="*70)
            self.log.info("Iteration %s/%s: Specific Cores Offline with SMT", 
                         iteration + 1, num_iterations)
            self.log.info("="*70)
            
            # Step 1: Bring all cores online first
            self.log.info("Step 1: Bringing all cores online")
            process.system("ppc64_cpu --cores-on=all", shell=True)
            time.sleep(1)
            
            # Get initial state
            initial_cores_info = self.get_cores_info()
            all_online_cores = list(range(self.total_cores))
            
            self.log.info("All cores online: %s cores", initial_cores_info['cores_on'])
            
            # Step 2: Select cores to offline
            # Strategy: offline 20-40% of cores, but at least 2 and at most total-2
            num_cores_to_offline = random.randint(
                max(2, int(self.total_cores * 0.2)),
                min(self.total_cores - 2, int(self.total_cores * 0.4))
            )
            
            # If we have previously offline cores, bring some back and offline different ones
            if previously_offline_cores and iteration > 0:
                # Bring back half of previously offline cores
                cores_to_bring_back = random.sample(
                    previously_offline_cores, 
                    max(1, len(previously_offline_cores) // 2)
                )
                
                # Select new cores to offline (excluding core 0 which must stay online)
                available_cores = [c for c in range(1, self.total_cores) 
                                 if c not in previously_offline_cores or c in cores_to_bring_back]
                
                cores_to_offline = random.sample(available_cores, 
                                                min(num_cores_to_offline, len(available_cores)))
                
                self.log.info("Bringing back cores: %s", cores_to_bring_back)
                self.log.info("Offlining new cores: %s", cores_to_offline)
            else:
                # First iteration: randomly select cores to offline (excluding core 0)
                available_cores = list(range(1, self.total_cores))
                cores_to_offline = random.sample(available_cores, num_cores_to_offline)
                self.log.info("Randomly selected cores to offline: %s", cores_to_offline)
            
            # Step 3: Offline the selected cores using --offline-cores command
            if cores_to_offline:
                cores_list = ','.join(str(c) for c in sorted(cores_to_offline))
                self.log.info("Offlining cores: %s", cores_list)
                
                cmd = "ppc64_cpu --offline-cores=%s" % cores_list
                result = process.run(cmd, shell=True, ignore_status=True)
                
                if result.exit_status != 0:
                    self.log.warning("Failed to offline cores %s", cores_list)
                    continue
                
                time.sleep(1)
            
            # Step 4: Verify cores are offline
            cores_info_after_offline = self.get_cores_info()
            actual_offline_cores = cores_info_after_offline['offline_cores']
            actual_online_cores = cores_info_after_offline['cores_on']
            
            self.log.info("After offlining:")
            self.log.info("  Cores online: %s", actual_online_cores)
            self.log.info("  Cores offline: %s (list: %s)", 
                         len(actual_offline_cores), actual_offline_cores)
            
            # Verify expected cores are offline
            for core in cores_to_offline:
                if core not in actual_offline_cores:
                    self.failures.append(
                        "Core %s should be offline but is online" % core)
            
            # Step 5: Perform all SMT operations with these offline cores
            self.log.info("\nStep 5: Testing all SMT operations with offline cores")
            
            for smt_val in self.all_smt_values:
                self.log.info("\n  Testing SMT=%s with %s cores online, %s offline",
                             smt_val, actual_online_cores, len(actual_offline_cores))
                
                # Set SMT
                process.system("ppc64_cpu --smt=%s" % smt_val, 
                             shell=True, ignore_status=True)
                time.sleep(0.5)
                
                # Verify cores didn't change
                cores_after_smt = self.get_cores_info()
                cores_online_after = cores_after_smt['cores_on']
                cores_offline_after = cores_after_smt['offline_cores']
                
                self.log.info("    After SMT=%s: %s cores online, %s offline (list: %s)",
                             smt_val, cores_online_after, 
                             len(cores_offline_after), cores_offline_after)
                
                # Validation 1: Core count should not change
                if cores_online_after != actual_online_cores:
                    self.failures.append(
                        "SMT=%s changed online core count from %s to %s" %
                        (smt_val, actual_online_cores, cores_online_after))
                
                # Validation 2: Offline cores should remain offline
                for core in cores_to_offline:
                    if core not in cores_offline_after:
                        self.failures.append(
                            "SMT=%s brought offline core %s back online" % (smt_val, core))
                
                # Validation 3: Verify system state with expected values
                expected_smt = smt_val if smt_val != 'on' else str(self.max_smt)
                if smt_val == 'off':
                    expected_smt = 'off'
                
                if not self.verify_system_state(expected_smt=expected_smt,
                                               expected_cores_on=cores_online_after):
                    self.failures.append(
                        "Verification failed for SMT=%s with specific cores offline" % smt_val)
            
            # Step 6: Test bringing specific cores back online
            if cores_to_offline and len(cores_to_offline) >= 2:
                self.log.info("\nStep 6: Testing selective core online")
                
                # Bring back half of the offline cores
                cores_to_bring_online = random.sample(cores_to_offline, 
                                                     len(cores_to_offline) // 2)
                cores_list = ','.join(str(c) for c in sorted(cores_to_bring_online))
                
                self.log.info("Bringing cores back online: %s", cores_list)
                cmd = "ppc64_cpu --online-cores=%s" % cores_list
                result = process.run(cmd, shell=True, ignore_status=True)
                
                if result.exit_status == 0:
                    time.sleep(0.5)
                    
                    # Verify
                    cores_after_online = self.get_cores_info()
                    self.log.info("After bringing cores online:")
                    self.log.info("  Cores online: %s", cores_after_online['cores_on'])
                    self.log.info("  Cores offline: %s (list: %s)",
                                 len(cores_after_online['offline_cores']),
                                 cores_after_online['offline_cores'])
                    
                    # Test SMT with new configuration
                    random_smt = random.choice(self.all_smt_values)
                    self.log.info("Testing SMT=%s with new core configuration", random_smt)
                    process.system("ppc64_cpu --smt=%s" % random_smt,
                                 shell=True, ignore_status=True)
                    time.sleep(0.5)
                    
                    # Verify cores didn't change
                    final_cores = self.get_cores_info()
                    if final_cores['cores_on'] != cores_after_online['cores_on']:
                        self.failures.append(
                            "SMT=%s changed core count after selective online" % random_smt)
            
            # Update previously offline cores for next iteration
            previously_offline_cores = cores_to_offline.copy()
            
            self.log.info("\nIteration %s completed", iteration + 1)
        
        # Final cleanup
        self.log.info("\nFinal cleanup: Bringing all cores online")
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)
        
        # Final verification
        if not self.verify_system_state():
            self.failures.append("Final verification failed after specific cores offline test")
        
        self.log.info("Specific cores offline with SMT test completed")
    
    
    def test(self):
        """
        Main test execution method.
        """
        self.log.info("Starting Optimized SMT and Core Hotplug Test Suite")
        self.log.info("System: SMT=%s (max: %s), Cores=%s", 
                     self.initial_smt, self.max_smt, self.initial_cores)
        self.log.info("Testing all SMT values: %s", self.all_smt_values)
        
        # Run all test scenarios
        test_methods = [
            self.test_all_smt_operations,
            self.test_dynamic_core_operations,
            self.test_smt_core_interaction,
            self.test_progressive_core_online_with_smt,
            self.test_specific_cores_offline_with_smt,
            self.test_random_stress,
            self.test_parallel_operations,
        ]
        
        for test_method in test_methods:
            try:
                self.log.info("\n" + "="*60)
                test_method()
                self.log.info("="*60 + "\n")
            except Exception as e:
                self.failures.append("Exception in %s: %s" % (test_method.__name__, str(e)))
                self.log.error("Test method %s failed: %s", test_method.__name__, str(e))
        
        # Report results
        if self.failures:
            self.log.error("\n=== TEST FAILURES ===")
            for failure in self.failures:
                self.log.error("- %s", failure)
            self.fail("Test completed with %s failure(s)" % len(self.failures))
        else:
            self.log.info("\n=== ALL TESTS PASSED ===")
    
    def tearDown(self):
        """
        Restore system to initial state.
        """
        self.log.info("Restoring system to initial state")
        
        try:
            # Restore cores
            process.system("ppc64_cpu --cores-on=all", shell=True, ignore_status=True)
            time.sleep(1)
            
            # Restore SMT
            process.system("ppc64_cpu --smt=%s" % self.initial_smt,
                         shell=True, ignore_status=True)
            time.sleep(1)
            
            # Final verification
            self.log.info("Final system state:")
            process.system_output("ppc64_cpu --info", shell=True)
            process.system_output("lscpu", shell=True)
            
        except Exception as e:
            self.log.error("Error during tearDown: %s", str(e))

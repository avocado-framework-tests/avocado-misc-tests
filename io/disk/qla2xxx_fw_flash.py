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
# Author: Maram Srimannarayana Murthy <msmurthy@linux.ibm.com>

"""
QLogic (Marvell) qla2xxx FC HBA Firmware Flash Test.

Installs qaucli RPM if absent, resolves the HBA instance number for
each PCI address via sysfs WWPN cross-reference, then flashes firmware
by driving the qaucli interactive menu via piped stdin.

qaucli operates as a numbered interactive menu; all firmware operations
are driven by piping newline-delimited selections to stdin.  Firmware
activates inline via adapter self-reset.
"""

import os
import re
import shutil

from avocado import Test
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager

QAUCLI_PATH = '/opt/QLogic_Corporation/QConvergeConsoleCLI/qaucli'


class Qla2xxxFwFlash(Test):
    """
    QLogic qla2xxx FC HBA firmware flash test.

    Drives qaucli via piped stdin to read firmware versions and flash
    new firmware.  Firmware activates inline (adapter self-resets) —
    no DLPAR or reboot required.
    """

    def setUp(self):
        """
        Validate architecture, read YAML parameters, and install qaucli.
        """
        if 'ppc64' not in distro.detect().arch:
            self.cancel("Supported only on ppc64 architecture")

        self.qaucli_installed_by_test = False
        self.fw_tmp_path = None
        self.fw_zip_tmp_path = None
        self.qaucli_tmp_path = None

        pci_devices_raw = self.params.get('pci_devices', default=None)
        self.qaucli_file = self.params.get('qaucli_file', default=None)
        self.firmware_file = self.params.get('firmware_file', default=None)

        for param, value in [
            ('pci_devices', pci_devices_raw),
            ('qaucli_file', self.qaucli_file),
            ('firmware_file', self.firmware_file),
        ]:
            if not value:
                self.fail(f"Required parameter '{param}' is missing or empty")

        self.pci_list = pci_devices_raw.split()

        self._install_rsct_packages()
        self._install_qaucli()

    def _install_rsct_packages(self):
        """
        Install pciutils; cancel the test if installation fails.
        """
        smm = SoftwareManager()
        for pkg in ['pciutils']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(
                    f"Required package '{pkg}' could not be installed"
                )

    def _install_qaucli(self):
        """
        Install qaucli from RPM if not present.  Downloads via curl to
        /tmp/ and installs with 'rpm -ivh'.  Sets
        self.qaucli_installed_by_test = True on success.
        """
        if shutil.which('qaucli') or os.path.exists(QAUCLI_PATH):
            self.log.info("qaucli already available, skipping installation")
            return

        basename = os.path.basename(self.qaucli_file)
        self.qaucli_tmp_path = f'/tmp/{basename}'

        cmd = f'curl -kL {self.qaucli_file} -o {self.qaucli_tmp_path}'
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail(f"qaucli RPM download failed: {self.qaucli_file}")

        if process.system(
            f'rpm -ivh {self.qaucli_tmp_path}',
            shell=True, sudo=True, ignore_status=True
        ):
            self.fail(
                f"rpm -ivh failed for qaucli RPM: {self.qaucli_tmp_path}"
            )

        if not os.path.exists(QAUCLI_PATH):
            self.fail("qaucli binary not found after RPM installation")

        self.qaucli_installed_by_test = True
        self.log.info("qaucli installed successfully via rpm -ivh")

    def _get_wwpns_for_pci(self, pci_addr):
        """
        Return normalised WWPNs (lowercase, no colons) for all fc_host
        sysfs entries whose realpath contains pci_addr.  Returns an
        empty set if no match is found.
        """
        wwpns = set()
        fc_host_base = '/sys/class/fc_host'
        if not os.path.isdir(fc_host_base):
            return wwpns
        for host in os.listdir(fc_host_base):
            host_path = os.path.join(fc_host_base, host)
            if pci_addr not in os.path.realpath(host_path):
                continue
            port_name_path = os.path.join(host_path, 'port_name')
            if not os.path.exists(port_name_path):
                continue
            with open(port_name_path, encoding='utf-8') as fh:
                raw = fh.read().strip().lstrip('0x').replace(':', '').lower()
            if raw:
                wwpns.add(raw)
                self.log.info(
                    "sysfs fc_host %s -> WWPN %s for PCI %s",
                    host, raw, pci_addr
                )
        return wwpns

    def _get_qaucli_list_output(self):
        """
        Run 'qaucli -pr fc -g' and return decoded stdout.  Result is
        cached in self._qaucli_list_cache; invalidated after each flash.
        """
        if not hasattr(self, '_qaucli_list_cache'):
            self._qaucli_list_cache = process.system_output(
                f'{QAUCLI_PATH} -pr fc -g',
                ignore_status=True, shell=True
            ).decode('utf-8')
        return self._qaucli_list_cache

    def _invalidate_qaucli_list_cache(self):
        """
        Drop the cached 'qaucli -pr fc -g' output so the next call
        re-runs the command after an adapter reset.
        """
        if hasattr(self, '_qaucli_list_cache'):
            del self._qaucli_list_cache

    def _get_hba_count(self):
        """
        Return the count of distinct HBA model entries from
        'qaucli -pr fc -g'.  Used to decide whether to inject an
        adapter selection token in the piped stdin sequence.
        """
        output = self._get_qaucli_list_output()
        count = sum(
            1 for line in output.splitlines()
            if re.match(r'\s*HBA Model\s+\S+', line)
        )
        self.log.info("qaucli reports %d HBA model(s)", count)
        return count

    def _get_instance_for_pci(self, pci_addr):
        """
        Resolve the qaucli HBA instance number for pci_addr by
        cross-referencing sysfs fc_host WWPNs with 'qaucli -pr fc -g'
        output.  Fails the test if no match is found.
        """
        sysfs_wwpns = self._get_wwpns_for_pci(pci_addr)
        if not sysfs_wwpns:
            self.fail(
                f"No fc_host sysfs entries found for PCI address {pci_addr}"
            )

        output = self._get_qaucli_list_output()

        pattern = re.compile(
            r'WWPN\s+([\da-fA-F:]+)\s+\(HBA instance\s+(\d+)\)'
        )
        for line in output.splitlines():
            match = pattern.search(line)
            if not match:
                continue
            wwpn_raw = match.group(1).replace(':', '').lower()
            instance = int(match.group(2))
            if wwpn_raw in sysfs_wwpns:
                self.log.info(
                    "Resolved qaucli instance %d for PCI %s via WWPN %s",
                    instance, pci_addr, match.group(1)
                )
                return instance

        self.fail(
            f"No qaucli HBA instance found for PCI address {pci_addr} "
            f"(sysfs WWPNs: {sysfs_wwpns})"
        )

    def _get_fw_versions(self, instance):
        """
        Query FC Firmware Version for the HBA instance via qaucli stdin.
        Menu path adapts for single vs multiple HBAs to avoid injecting
        a redundant adapter selection token.  Returns {'active': <ver>}.
        Fails if the field is absent from the output.
        """
        hba_count = self._get_hba_count()
        if hba_count > 1:
            adapter_sel = instance + 1
            stdin_seq = f'1\\n1\\n1\\n{adapter_sel}\\n\\n99\\n'
        else:
            stdin_seq = '1\\n1\\n1\\n\\n99\\n'
        cmd = f'printf "{stdin_seq}" | {QAUCLI_PATH}'
        result = process.run(cmd, shell=True, ignore_status=True)

        versions = {}
        for line in result.stdout_text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith('fc firmware version'):
                versions['active'] = stripped.split(':', 1)[-1].strip()
                break

        if not versions:
            self.fail(
                f"qaucli adapter detail returned no FC Firmware Version "
                f"for instance {instance}"
            )
        self.log.info(
            "FC Firmware Version for instance %d: %s",
            instance, versions['active']
        )
        return versions

    def _download_firmware(self):
        """
        Download firmware from self.firmware_file to /tmp/.  If the URL
        is a .zip, extracts it and returns the path to the first .bin.
        Sets self.fw_zip_tmp_path and self.fw_tmp_path accordingly.
        Fails if download, extraction, or .bin search fails.
        """
        basename = os.path.basename(self.firmware_file)
        local_path = f'/tmp/{basename}'

        cmd = f'curl -kL {self.firmware_file} -o {local_path}'
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail(
                f"Firmware file download failed: {self.firmware_file}"
            )
        self.log.info("Firmware downloaded to %s", local_path)

        if not basename.lower().endswith('.zip'):
            self.fw_tmp_path = local_path
            return local_path

        self.fw_zip_tmp_path = local_path
        extract_dir = f'{local_path}_extract'
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)

        if process.system(
            f'unzip -o {local_path} -d {extract_dir}',
            shell=True, ignore_status=True
        ):
            self.fail(f"Failed to extract firmware zip: {local_path}")

        bin_files = []
        for root, _, files in os.walk(extract_dir):
            for fname in files:
                if fname.lower().endswith('.bin'):
                    bin_files.append(os.path.join(root, fname))

        if not bin_files:
            self.fail(
                f"No .bin firmware file found in zip archive: {local_path}"
            )
        if len(bin_files) > 1:
            self.log.warning(
                "Multiple .bin files found in zip, using first: %s",
                bin_files
            )

        bin_path = bin_files[0]
        self.fw_tmp_path = bin_path
        self.log.info("Firmware .bin extracted to %s", bin_path)
        return bin_path

    def _flash_firmware(self, instance, fw_path):
        """
        Flash fw_path onto the HBA instance by driving the qaucli menu
        via piped stdin.  Menu path adapts for single vs multiple HBAs.
        Captures a dmesg diff to the Avocado log directory.  Fails if
        'Flash update complete' is absent from the qaucli output.
        """
        dmesg_before = process.system_output(
            'dmesg', ignore_status=True
        ).decode('utf-8', errors='replace').splitlines()

        self.log.info(
            "Flashing firmware %s to qaucli instance %d", fw_path, instance
        )

        hba_count = self._get_hba_count()
        if hba_count > 1:
            adapter_sel = instance + 1
            stdin_seq = (
                f'3\\n1\\n1\\n{adapter_sel}\\n{fw_path}\\n1\\n1\\n\\n99\\n'
            )
        else:
            stdin_seq = f'3\\n1\\n1\\n{fw_path}\\n1\\n1\\n\\n99\\n'
        cmd = f'printf "{stdin_seq}" | {QAUCLI_PATH}'
        result = process.run(cmd, shell=True, ignore_status=True,
                             timeout=300)

        output = result.stdout_text
        self.log.info("qaucli flash output:\n%s", output.strip())

        if 'Flash update complete' not in output:
            self.fail(
                f"Flash update did not complete for instance {instance} — "
                f"'Flash update complete' not found in qaucli output"
            )

        dmesg_after = process.system_output(
            'dmesg', ignore_status=True
        ).decode('utf-8', errors='replace').splitlines()

        new_lines = [ln for ln in dmesg_after if ln not in dmesg_before]
        dmesg_log = os.path.join(
            self.logdir, 'qla2xxx_fw_flash_dmesg.log'
        )
        with open(dmesg_log, 'a', encoding='utf-8') as fh:
            fh.write(
                f'\n--- dmesg during flash of instance {instance} ---\n'
            )
            fh.write('\n'.join(new_lines) + '\n')
        self.log.info("dmesg captured to %s", dmesg_log)

    def _group_pci_by_card(self):
        """
        Group self.pci_list by physical card using the HBA serial number
        from 'qaucli -pr fc -g'.  Each card shares one ASIC and one
        flash; flashing any port updates all ports on that card.
        Returns a list of dicts with keys: serial, pci_ports, instances.
        """
        output = self._get_qaucli_list_output()

        wwpn_to_card = {}
        current_serial = None
        port_pattern = re.compile(
            r'WWPN\s+([\da-fA-F:]+)\s+\(HBA instance\s+(\d+)\)'
        )
        serial_pattern = re.compile(r'\(SN\s+([^)]+)\)')

        for line in output.splitlines():
            m_serial = serial_pattern.search(line)
            if m_serial:
                current_serial = m_serial.group(1).strip()
                continue
            m_port = port_pattern.search(line)
            if m_port and current_serial:
                wwpn_norm = m_port.group(1).replace(':', '').lower()
                instance = int(m_port.group(2))
                wwpn_to_card[wwpn_norm] = (current_serial, instance)

        cards = {}
        for pci_addr in self.pci_list:
            sysfs_wwpns = self._get_wwpns_for_pci(pci_addr)
            matched = False
            for wwpn in sysfs_wwpns:
                if wwpn in wwpn_to_card:
                    serial, instance = wwpn_to_card[wwpn]
                    if serial not in cards:
                        cards[serial] = {'pci_ports': [], 'instances': []}
                    cards[serial]['pci_ports'].append(pci_addr)
                    cards[serial]['instances'].append(instance)
                    self.log.info(
                        "PCI %s → card SN %s (instance %d)",
                        pci_addr, serial, instance
                    )
                    matched = True
                    break
            if not matched:
                self.fail(
                    f"Could not map PCI address {pci_addr} to any HBA "
                    f"card in qaucli output"
                )

        return [
            {'serial': sn, **info} for sn, info in cards.items()
        ]

    def test_firmware_flash(self):
        """
        Orchestrate the firmware flash sequence grouped by physical card.
        Flashing through one port updates the entire card.  Pass
        criterion: 'Flash update complete' in qaucli output.  Same-
        version reflash is valid and does not fail the test.
        """
        fw_path = self._download_firmware()

        card_groups = self._group_pci_by_card()
        self.log.info(
            "Identified %d physical card(s) from %d PCI address(es)",
            len(card_groups), len(self.pci_list)
        )

        for card in card_groups:
            serial = card['serial']
            pci_ports = card['pci_ports']
            instances = card['instances']

            self.log.info(
                "===== Flashing card SN %s (%d port(s): %s) =====",
                serial, len(pci_ports), ' '.join(pci_ports)
            )

            pre_fw_map = {}
            for pci_addr, instance in zip(pci_ports, instances):
                versions = self._get_fw_versions(instance)
                pre_fw_map[pci_addr] = versions['active']
                self.log.info(
                    "Pre-flash  PCI %s instance %d: FC Firmware Version %s",
                    pci_addr, instance, versions['active']
                )

            flash_instance = instances[0]
            flash_pci = pci_ports[0]
            self.log.info(
                "Flashing card SN %s via instance %d (PCI %s)",
                serial, flash_instance, flash_pci
            )
            self._flash_firmware(flash_instance, fw_path)

            self._invalidate_qaucli_list_cache()

            for pci_addr, instance in zip(pci_ports, instances):
                versions = self._get_fw_versions(instance)
                post_fw = versions['active']
                pre_fw = pre_fw_map[pci_addr]
                if post_fw != pre_fw:
                    self.log.info(
                        "Post-flash PCI %s instance %d: "
                        "FC Firmware Version %s -> %s (upgraded)",
                        pci_addr, instance, pre_fw, post_fw
                    )
                else:
                    self.log.info(
                        "Post-flash PCI %s instance %d: "
                        "FC Firmware Version %s (same-version reflash)",
                        pci_addr, instance, post_fw
                    )

            self.log.info(
                "===== Flash PASSED for card SN %s =====", serial
            )

    def _uninstall_qaucli(self):
        """
        Uninstall the qaucli RPM via 'rpm -e QConvergeConsoleCLI'.
        Logs a warning if the binary remains; does not fail tearDown.
        """
        self.log.info("Uninstalling qaucli RPM installed by test")

        process.system(
            'rpm -e QConvergeConsoleCLI',
            shell=True, sudo=True, ignore_status=True
        )

        if os.path.exists(QAUCLI_PATH):
            self.log.warning(
                "qaucli binary still present at %s after rpm -e",
                QAUCLI_PATH
            )
        else:
            self.log.info("qaucli RPM removed successfully via rpm -e")

    def tearDown(self):
        """
        Uninstall qaucli if installed by this test and remove all
        temporary files created during the run.  Pre-existing qaucli
        installations are not touched.
        """
        if self.qaucli_installed_by_test:
            self._uninstall_qaucli()
        else:
            self.log.info("qaucli was pre-existing, skipping uninstall")

        if self.qaucli_tmp_path and os.path.exists(self.qaucli_tmp_path):
            os.remove(self.qaucli_tmp_path)
            self.log.info(
                "Removed qaucli RPM %s", self.qaucli_tmp_path
            )

        if self.fw_zip_tmp_path:
            if os.path.exists(self.fw_zip_tmp_path):
                os.remove(self.fw_zip_tmp_path)
                self.log.info(
                    "Removed firmware zip %s", self.fw_zip_tmp_path
                )
            extract_dir = f'{self.fw_zip_tmp_path}_extract'
            if os.path.isdir(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
                self.log.info(
                    "Removed firmware extraction directory %s", extract_dir
                )
        elif self.fw_tmp_path and os.path.exists(self.fw_tmp_path):
            os.remove(self.fw_tmp_path)
            self.log.info("Removed firmware file %s", self.fw_tmp_path)

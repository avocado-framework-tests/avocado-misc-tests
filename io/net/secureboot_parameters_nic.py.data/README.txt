Validates NIC driver state after Secure Boot enable on IBM Power LPARs
(ppc64le, RHEL/SUSE).

Requires Secure Boot to be enabled on the LPAR before running.
If lockdown=[none] is detected in setUp, the test cancels immediately.

Tests
-----
test_lockdown_state          - Verify lockdown=integrity and IBM DT
                               ibm,secure-boot=2 property set.
test_interface_visibility    - Verify NIC interfaces visible in sysfs
                               after SB enable and ping peer_ip.
test_driver_secureboot_checks - Driver-specific checks (see below).

Driver-specific checks
----------------------
ibmvnic   - VIO driver binding, vnic@ device-tree node, net/ interface,
            operstate not 'down', Partner init message in dmesg,
            ibm,hcn-mode logged for HNV identification.
ibmveth   - VIO driver binding, l-lan@ device-tree node, net/ interface.
pci_nic   - PCI device bound to driver, net/ interface, ethernet@ node
(tg3,       in /proc/device-tree/pci@*/, operstate logged.
mlx5_core,
etc.)

YAML file
---------
secureboot_parameters_nic.yaml

Parameters
----------
nic_driver      - Driver under test: ibmvnic | ibmveth | <pci-driver>
nic_driver_type - Set to 'pci' for PCIe NIC drivers; omit for VIO NICs.
interface       - Interface name or MAC address on the host.
host_ip         - IP address to assign to the interface.
netmask         - Network mask.
peer_ip         - Peer IP address for ping connectivity check.
peer_user       - Peer SSH username (default: root).
peer_password   - Peer SSH password.
ip_config       - Set to False if IP is already configured (default: True).

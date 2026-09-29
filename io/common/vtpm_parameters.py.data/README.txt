Validates vTPM parameters on IBM Power LPARs (ppc64le, RHEL/SUSE) for a
given storage or network driver alongside an active vTPM.

Checks: device-tree node, compatible string, kernel config, device-node
permissions, CRQ init in dmesg, /proc/devices entry, and measurement log.

Driver-specific checks
----------------------
ibmvfc    - vfc-client@ VIO node co-exists with vtpm@ in vdevice/
ibmvscsi  - v-scsi@ VIO node co-exists with vtpm@ in vdevice/
ibmvnic   - vnic@ VIO node, driver binding, net/ interface, operstate,
            ibm,hcn-mode (HNV backup leg identification)
ibmveth   - l-lan@ VIO node, driver binding, net/ interface
pci_nic   - PCI device bound to driver, ethernet@ in device-tree,
(tg3,       operstate logged (down = informational only)
mlx5_core,
etc.)

YAML files
----------
vtpm_parameters.yaml     - Storage/FC and VIO NIC drivers.
                           Set: driver: <name>

vtpm_parameters_nic.yaml - Direct-attach/SR-IOV PCIe NIC drivers.
                           Set: driver_type: pci
                                driver: <kernel_driver_name>

Parameters
----------
driver      - Driver under test (nvme, nvmf, lpfc, qla2xxx, ibmvfc,
              ibmvscsi, ibmvnic, ibmveth, or a PCIe NIC driver name).
driver_type - Set to 'pci' for PCIe NIC drivers only.

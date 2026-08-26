Validates vTPM parameters on IBM Power LPARs (ppc64le, RHEL/SUSE) for a
given block device driver (nvme, nvmf, lpfc, qla2xxx, ibmvfc, ibmvscsi).

The test verifies the device-tree node, compatible string, required kernel
configuration options, device-node presence and permissions, CRQ driver
registration in dmesg, /proc/devices entry, and the binary BIOS measurement
log under /sys/kernel/security/tpm0/binary_bios_measurements.

For ibmvfc, the test also confirms the vfc-client@ VIO node co-exists with
the vtpm@ node in /proc/device-tree/vdevice/. For ibmvscsi, it confirms the
v-scsi@ VIO node co-exists with the vtpm@ node.

This test must be run as root on an IBM Power LPAR with vTPM enabled.

Available parameters
--------------------

block_driver - Block device driver under test. Must be one of:
               nvme, nvmf, lpfc, qla2xxx, ibmvfc, ibmvscsi

IOMMU Interrupt remapping support
=================================
AMD IOMMU supports interrupt remapping to translate and isolate device interrupts,
improving system security and stability.

2K Interrupt remapping support
------------------------------
AMD IOMMU supports upto 2048 interrupts per device function. Which is indicated
by IOMMU extended feature2 bits 8-9. When this feature is enabled through IOMMU control
register, device driver can request up to 2048 interrupts per device function.

Note: Patches are part of Upstream v6.15.

Testing
-------
1. Check device, IOMMU HW and IOMMU driver for "count" number of interrupt support.
2. Validate and attach "pci_device" to VFIO driver.
3. Request "count" interrupt allocation for "pci_device".

Note: This test needs to be run as root.

Inputs Needed (in multiplexer file):
------------------------------------
pci_device -	can be fetched from <lspci -nnD> output.
count -		number of interrupt to request for allocation.

eg. Test 2k Interrupt remapping support
avocado run avocado-misc-tests/cpu/interrupt.py -p pci_device="0000:01:00.0" -p count=2048

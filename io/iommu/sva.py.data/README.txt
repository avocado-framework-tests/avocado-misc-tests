SVA PCIe Capability Test Suite
==============================
This test suite verifies SVA-related PCIe capabilities for a given PCI device, including:
1. PASID (Process Address Space ID):
   Allows a device to tag DMA transactions with a PASID. Each PASID is an identifier used by a PCI
   device to indicate which process’s virtual address space a DMA transaction belongs to. Thus allow
   PCI device to share process address space. The PASID can be up to 20 bits, but the actual number
   of supported bits may be lower depending on the implementation.

2. ATS (Address Translation Service):
   Allows the PCI device to request translations from the IOMMU and cache it, improving memory access
   performance.

3. PRI (Page Request Interface):
   Enables the PCI device to generate page requests (page faults) to the IOMMU/OS so that missing pages
   can be mapped dynamically. This supports on-demand paging for SVA and mediated devices.

Testing
-------
1. Check lspci for the input PCI device.
2. Verifies if PCI device supports the required capability and is enabled.

Input Parameters
----------------
pci_device: The full PCI address of the device under test (including domain), e.g., 0000:85:00.1.

eg. Run PCI device feature (PASID, ATS, PRI) detection test
avocado run avocado-misc-tests/io/iommu/sva.py -p pci_device="0000:01:00.0" --max-parallel-tasks=1

Various combination of unbind, bind, change iommu group domain type, reset and rescan pci device is used
to form sub-tests that test and exercise iommu code.

Unbind - Detach pci device from driver.
Bind - Attach pci device to the driver.
Change iommu group domain type - Change iommu group domain type of pci device.
Reset - Reset the pci device.
Rescan - Rescan for pci device.

Pci device to be tested (on subtests involving "change iommu group domain type") should be alone in its iommu group.
Group domain type change for a pci device which belongs to an iommu group having more than one pci device is not supported
in present systems.

This test needs to be run as root.

Inputs Needed (in multiplexer file):
------------------------------------
pci_devices -      can be fetched from <lspci -nnD>  output. Use space for multiple devices "001b:62:00.0 001b:62:00.1"
count -      This is an integer value given for number of time tests to run.

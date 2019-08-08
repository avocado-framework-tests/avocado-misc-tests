This Test removes and adds back a scsi device in all the specified PCI domains
or wwids specified in the 'multiplexer' file.
if wwids are provided, pci devices are ignored.
This test needs to be run as root.

Inputs Needed (in 'multiplexer' file):
--------------------------------------
wwids - wwids can be fetched from multipath -ll or lsscsi -u commands.
PCI_devices -   PCI Device entry got from 'lspci' command.

This Test removes and adds back a scsi device in all the specified PCI domains
specified in the 'multiplexer' file.
Runs the test for '0000:01:00.0' if no value for pci domain is given.
This test needs to be run as root.

Inputs Needed (in 'multiplexer' file):
--------------------------------------
PCI_devices -   PCI Device entry got from 'lspci' command.

This Test removes and adds back a scsi device in all the specified wwids
or domains in the 'multiplexer' file separated by comma (,).
This test needs to be run as root.

Inputs Needed (in 'multiplexer' file):
--------------------------------------
wwids - wwids can be fetch from 'multipath -ll' or 'lsscsi -u' commands
pci_device: pci domain can be fetch from 'lspci -nnD' command.

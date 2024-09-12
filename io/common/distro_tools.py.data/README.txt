description:
------------------------
This Program to test the different distro tools, like lsslot,netstat,lsprop,lsvio,lsdevinfo,usysattn,usysident,ofpathname.
-----------------------------
Inputs Needed To Run Tests:
-----------------------------
pci_device --> Specify pci address for test


User specification for "lsprop -R" command execution:
--------------------------------------------------
By default "lsprop -R" runs for "/proc/device-tree" directory
And this can be changed to specific directory in YAML file

For Ex in YAML file:
test_opt: -R /proc/device-tree/ --> pointing to "device-tree" directory under "/proc".

to change "/tmp"
test_opt: -R /tmp/              --> pointing to "/tmp" directory. 


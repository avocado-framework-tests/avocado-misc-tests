PCI Hotplug can remove and add pci devices when the system is active.
And checks their respective functionality after remove/add operation.
This test verifies that for supported slots.
This test needs to be run as root.

Inputs Needed (in multiplexer file):
------------------------------------
pci_devices -       PCI devices, pass space separated pci devices "001b:62:00.0 001b:62:00.1"
num_of_hotplug -   Specify number of times hotplug to be performed
peer_ip -          if the hot_pluggable adapter is network type, then you have to provide with
                   corresponding peer interface IP to check the ping functionality after the 
                   adapter is added back. this is not required if adapter is not net.

Mellanox OpenFabrics Enterprise Distribution (MOFED) System Update Package,
provides necessary softwares to operates across all Mellanox network adapter
solutions supporting 10, 20, 40 and 56 Gb/s InfiniBand (IB); 10, 40 and 56 Gb/s
Ethernet; and 2.5 or 5.0 GT/s PCI Express 2.0 and 8 GT/s PCI Express 3.0
uplinks to servers.

This test verifies the installation of MOFED iso with different
combinations of input parameters, as specified in multiplexer file.

This test needs to be run as root.

Inputs Needed (in multiplexer file):
------------------------------------
iso_location -  HTTP location of MOFED ISO (Available from Mellanox website)
option -        installation parameters
uninstall -     Indicate whether to uninstall or not (True/False, default=True)

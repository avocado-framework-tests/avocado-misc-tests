Tests bridge interface with 'brctl' command.
Input interface is specified in the multiplexer file.

This test needs to be run as root.

Requirements:
-------------
Python module 'netifaces' is needed. Install via 'pip install netifaces' (or)
'easy_install netifaces'

Input Needed (in multiplexer file):
-----------------------------------
Interfaces - Specify the space separated interface names or mac addresses 
             with which the bridge interface needs to be created.
             interfaces: "env3 env4"  or interfaces: '02:xx:xx:xx:xx:03 02:xx:xx:xx:xx:04'
Peer-IP   - Specify the IP for ping test after bridge interface is created
host-IP   - Specify the IP for ip configuration for interface.
Netmask   - Specify the netmask for ip configuration for interface.

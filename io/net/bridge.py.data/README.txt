Tests bridge interface with 'brctl' command.
Input interface is specified in the multiplexer file.

This test needs to be run as root.

Requirements:
-------------
Python module 'netifaces' is needed. Install via 'pip install netifaces' (or)
'easy_install netifaces'

Input Needed (in multiplexer file):
-----------------------------------
Interface - Specify the interface with which the bridge interface needs to
            be created.
Peer-IP   - Specify the IP for ping test after bridge interface is created

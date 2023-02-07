Tests the network driver and interface with 'ethtool' command.
Different parameters are specified in Parameters section of multiplexer file.
Interfaces are specified in Interfaces section of multiplexer file.

This test needs to be run as root.

Requirements:
-------------
For all specified interfaces, configuration file for that interface needs
to be updated, so that setting 'up / down <interface>' configures the interface.

Input Needed (in multiplexer file):
-----------------------------------
interface      -   Specify the interface name 'eth1' or mac addr '34:80:0d:9b:dc:30' of device under test
arg            -   Specify the argument that needs to be tested.
action_elapse  -   Specify action elapse for those arguments that need it.
host-IP        -   Specify host-IP for ip configuration.
netmask        -   specify netmask for ip configuration.
hbond          -   Specify if the test is run on hbond or regular interface
ping_count     -   Mention the ping count required for ping test

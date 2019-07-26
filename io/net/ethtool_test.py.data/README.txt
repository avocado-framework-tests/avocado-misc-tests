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
Interfaces     -   Specify the interface for which the test needs to be run.
arg            -   Specify the argument that needs to be tested.
action_elapse  -   Specify action elapse for those arguments that need it.

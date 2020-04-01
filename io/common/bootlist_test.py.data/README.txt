Test does testing bootlist for Normal and Service mode even Both mode,
as converting to all modes ad display ouiput as logical Device name
and open firmware devices.
here we have two yaml file.one is for interface and other is for disk.

Requirements:
-------------
Test need one or more interface for this test.so that we can
converting in to the different mode.
Test need one or more disk for this test.so that we can
converting in to the different mode.

Input Needed (in yaml file)
---------------------------
Interfaces - Specify the interfaces(space separated) for which the test needs to be run. like eth8 eth9
disks - specify the disks (space separated) for which the test needs to be run .like /dev/sda /dev/sdb


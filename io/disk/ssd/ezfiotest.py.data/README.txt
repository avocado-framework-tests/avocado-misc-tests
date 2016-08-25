This test script is intended to give a block-level based overview of
SSD performance. Uses FIO to perform the actual IO tests. 
Places the output files in avocado test's outputdir.
This test needs to be run as root.

Inputs Needed (in multiplexer file):
------------------------------------
Devices -       SSD Block devices
Utilization -   Amount of drive to test (in percent)

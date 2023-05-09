This test script is intended to give a block-level based overview of
SSD performance. Uses FIO to perform the actual IO tests. 
Places the output files in avocado test's outputdir.
This test needs to be run as root.

Inputs Needed (in multiplexer file):
------------------------------------
disk -          SSD Block device like /dev/nvme0n1 or device name by-id or by-path
utilization -   Amount of drive to test (in percent)

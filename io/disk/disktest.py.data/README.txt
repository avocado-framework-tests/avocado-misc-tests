Pattern test of the disk, using unique signatures for each block and each
iteration of the test. Designed to check for data corruption issues in the
disk and disk controller.

It writes chunks one by one to the disks (spawning parallel processes per
each disk) and checking failures after each chunk is written.

Available parameters
--------------------

disk       - Disk to be used in test.
dir        - Directory of used in test. When the target does not exist,
	     it's created.

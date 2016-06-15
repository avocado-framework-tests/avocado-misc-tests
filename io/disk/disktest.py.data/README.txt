Pattern test of the disk, using unique signatures for each block and each iteration of the test. Designed to check for data corruption issues in the disk and disk controller.

It writes chunks one by one to the disks (spawning parallel processes per each disk) and checking failures after each chunk is written.

Available parameters
--------------------

disks - List of directories of used in test. In case only string is used it's split using ','. When the target is not directory, it's created.
gigabyte - Disk space that will be used for the test to run.
chunk_mb - Size of the portion of the disk used to run the test. Cannot be smaller than the total amount of RAM.

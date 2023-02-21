Pattern test of the disk, using unique signatures for each block and each
iteration of the test. Designed to check for data corruption issues in the
disk and disk controller.

It writes chunks one by one to the disks (spawning parallel processes per
each disk) and checking failures after each chunk is written.

Available parameters
--------------------

disk       - Provide the test disk name /dev/sda or /dev/mapper/mpatha or 
             scsi-360050768108000000000283 or nvme-eui.364555305250000003
             you can get the disk by id name via /dev/disk/by-id/
dir        - Directory of used in test. When the target does not exist,
	     it's created.

This program downloads the LTP test suite, compiles it and runs 2 filesystem related tests 'fs_di' and 'fs_inod' by invoking the runltp test script. 
This program creates a filesystem on a disk and then mounts it to the mount point specified and then the runltp script is triggered that runs the 2 tests on the mount point.
The disk and the mount point has to be provided by the user. Do not pass the root disk. Make sure an empty disk is passed.
The user can also give a filesystem of choice to be created and to start the test.

Example for the inputs needed to run the program:
disk: '/dev/sda'
mount_point: '/mnt'

This program downloads the LTP test suite, compiles it and runs 2 filesystem related tests 'fs_di' and 'fs_inod' by involking the runltp test script. 
This program creates a filesystem on a disk and then mounts it to the mount point specified and then the runltp script is triggered that runs the 2 tests on the mount point.

Inputs needed to run the program:
disk: ''   eg: /dev/sda
dir: ''    eg: /mnt
fs: ''     eg: ext4
args: '-s fs_di,-s fs_inod'


 

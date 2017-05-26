This tests different block device list tools with the
help of some disk operations like mounting filesystem on os boot disk
and check all tools are getting updated.

Different tools it tests are:
lsblk, fdisk, sfdisk, parted, df, blkid, lshw, hwinfo

Test should run on OS disk where it can access other storage block devices
like /dev/sda. So it will do operations like creating file system and mounting
it on OS disk and verifies all the tools are getting updated properly.

It will also verifies for disk Size, name, UUID and IO Sector sizes in
different tools vs sysfs paths.

Test environment:
If system is having n disks say sda, sdb ....sdn
If test code is in sda, this test can do operations on other
disks sdb, sdc ..sdn(So these disks will be disk inputs). So
test this carefully as it may override the data in sdb, sdc ...sdn

Inputs:
------
disk: '/dev/sdb'
fs: 'ext4'
dir: '/mnt'

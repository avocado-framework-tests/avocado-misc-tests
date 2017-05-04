Bonnie++ is a disk and file system benchmarking tool for measuring I/O performance. With Bonnie++ you can quickly and easily produce a meaningful value to represent your current file system performance.
Example : ./bonnie++ -u root -d /mnt -s0 -b -n 10:100:10:1000
so one has to pass following parameter in the yaml file
scratch-dir: /mnt (disk mounted on some dir. say /mnt here)
uid-to-use: root (user name or it UUID, here it is name i,e root)
number-to-stat: 10:0:0:2:8192 (Number of files to create file test)
size_to_pass: 0 (dataset size, here we are passing 0 to skip it as we running file related test)

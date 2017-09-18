About fs_mark
-------------

fs_mark options:
 -n 10000000: The number of files to be tested per thread (more on that later)
 -s 400; Each file will be 400KB
 -L 1: Loop the testing once (fs_mark testing)
 -S 0: Issue no sync() or fsync() during the creation of the file system. 
 -D 10000: There are 10,000 subdirectories under the main root directory
 -d /mnt: The root directory for testing;
 -N 1000: 1,000 files are allocated per directory
 -t 10: Use 10 threads for building the file system
 -k: Keep the file system after testing

SAMPLE RUN
  A typical run of the program would look like this:
    ./fs_mark -d /mnt -s 10240 -n 1000

Multiplexer Input Parameters
----------------------------

disk		- disk on which the test is to be run
dir         - dir on which the disk needs to be mounted and run
num_files	- number of files allocated per directory
size		- size of each file

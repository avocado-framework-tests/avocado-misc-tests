Overview
---------
The forkoff test demonstrates and tests the behavior of memory allocation in child processes created by the fork() system call on a Linux machine by creating multiple child processes that allocate memory and test the system's memory management behavior.

This test case has three different scenarios
1. Total free memory is allocated to one process
2. Split free memory among given processes
3. Create maximum processes possible with minimum memory (10 MB) per process

Note that this test may consume a large amount of system resources, so it should be run on a machine with sufficient memory and processing power.

Parameters
-----------
* procs : no. of procs to be created in scenario 2, it can be between 1 and the max_pid of the system
Example : procs: 10 [creates 10 processes]

* minmem : memory size in MB to be allocated to each process in scenario 3, depends on the memory in the system
Example  : minmem: 10 # in MB [creates maximum no. of possible processes with 10MB allocated to each process]

* iterations : no. of pages of the mmap-ed memory to be touched in all the above scenarios.
Example :iterations: 1 [touches 1st page in the allocated region]

Wrapper scripts for power management related experiments in BML using modified ebizzy
-------------------------------------------------------------------------------------


ebizzy is a multi-threaded micro benchmark that estimates scalability of memory 
allocations and scalability.

Open source ebizzy has been modified to inject pre-defined load per-cpu for general
power management related experiment.

CREDITS
-------
Vaidyanathan Srinivasan <svaidy@linux.vnet.ibm.com>
Trinabh Gupta <tringupt@in.ibm.com> 
Prerna Saxena <prerna@linux.vnet.ibm.com>

Initial development in 2010, further wrappers in 2012.

USAGE
-----

Setup:
1. Boot BML in ST mode
	bml -smt=0 fs_large

2. Copy package (tar.gz) into the BML runtime and untar the contents
3. ./configure #Create Makefile
4. make	#Build ebizzy binary

Execution:

USAGE:
./powersave-transition.sh BUSY_CORES IDLE_CORES LOAD TIME

Example 1:

./powersave-transition.sh  4 0,8 20 60
		       Busy^ ^idle| ^^ for 60 seconds
		       		  ^20% utilization

Core 4 is held busy while cores 0 and 8 transition in/out of nap.
The time period is 1000ms, so 20% utilization means the core will 
be bus for 200ms and then drop to idle (nap/sleep) for 800ms.


Example 2:

./powersave-transition.sh  4 0,8 1 120

Core 4 is busy while cores 0,8 are loaded only 1% just to keep
idle-busy transitions happening on those cores.

Example 3:

./powersave-transition.sh 0,4,8 16,20,24 2 120

Cores 0,4,8 are held busy while 16,20,24 transition in/out of idle
at 2% per second.  Total run lasts for 120s.


The actual test run starts after a short calibration phase where
utilizations may be higher.

The loading can be verified with top:

top - 10:35:53 up 27 min,  2 users,  load average: 2.45, 0.93, 0.39 
Tasks:  76 total,   1 running,  75 sleeping,   0 stopped,   0 zombie
Cpu0  :100.0%us,  0.0%sy,  0.0%ni,  0.0%id,  0.0%wa,  0.0%hi,  0.0%si,  0.0%st
Cpu4  :100.0%us,  0.0%sy,  0.0%ni,  0.0%id,  0.0%wa,  0.0%hi,  0.0%si,  0.0%st
Cpu8  :100.0%us,  0.0%sy,  0.0%ni,  0.0%id,  0.0%wa,  0.0%hi,  0.0%si,  0.0%st
Cpu16 :  2.0%us,  0.0%sy,  0.0%ni, 98.0%id,  0.0%wa,  0.0%hi,  0.0%si,  0.0%st
Cpu20 :  2.0%us,  0.0%sy,  0.0%ni, 98.0%id,  0.0%wa,  0.0%hi,  0.0%si,  0.0%st
Cpu24 :  2.0%us,  0.0%sy,  0.0%ni, 98.0%id,  0.0%wa,  0.0%hi,  0.0%si,  0.0%st
Mem:   8047348k total,   276740k used,  7770608k free,        0k buffers
Swap:        0k total,        0k used,        0k free,   207364k cached

Hit '1' in top console to see per-cpu utilization.


Limitations:

* Speed of transitions are in milli-seconds since this is all done in
  user space.  Moving into kernel driver may get us down to few
  micro-seconds.

* Keeping different cores at different idle states nap/sleep is yet to
  be tested


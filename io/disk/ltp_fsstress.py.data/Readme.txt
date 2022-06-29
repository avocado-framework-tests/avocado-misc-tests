Fsstress is a tress test on different file systems. stress level can be managed
with following options

p : number of processes.
n : number of operations.
l : number of loops for each processes.

User can change the above parameter values based on requirement.

example:
./fsstress -d /mnt -l 2 -n 250 -p 200

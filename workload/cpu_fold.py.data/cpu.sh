#!/bin/bash
# An online and offline core workload script to stress the 
# cpu's on- and offline core functionality using the number 
# of cores available on the system.

get_core=`ppc64_cpu --cores-present`
total_cores=$(echo "$get_core" | grep -oE '[0-9]+')

while [ 1 ]
do
for ((i=1; i<$total_cores; i++)); do
    if ((i % 2 == 0)); then
        ppc64_cpu --offline-cores=$i
        ppc64_cpu --cores-on
        ppc64_cpu --info
        sleep 2
    else
        ppc64_cpu --online-cores=$i
        ppc64_cpu --cores-on
        ppc64_cpu --info
        sleep 2
    fi
done
for ((i=1; i<$numbers; i++)); do
    if ((i % 2 == 0)); then
        ppc64_cpu --online-cores=$i
        ppc64_cpu --cores-on
        ppc64_cpu --info
        sleep 2
    else
        ppc64_cpu --offline-cores=$i
        ppc64_cpu --cores-on
        ppc64_cpu --info
        sleep 2
    fi
done
done

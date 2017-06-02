#!/bin/bash
##
# Script to make cores transit in and out of sleep  state.
#
# Usage ./powersave-transition BUSY_CORES IDLE_CORES LOAD TIME
#
##

# No of threads = 1* no of cores
function parse_threads
{
    nr_cores=(`echo $1| tr ',' ' '`)
    return $((1*${#nr_cores[@]}))
}

if [ $# -ne 4 ]
then
    echo "USAGE:"
    echo "$0 BUSY_CORES IDLE_CORES LOAD TIME"
    echo "Note that BUSY_CORES and IDLE_CORES are comma-separated lists ONLY"
    exit
fi

echo 2 > /proc/sys/kernel/powersave-nap
parse_threads $1
nr_busy_threads=$?
taskset -c $1 ./ebizzy -s 4096 -S $4 -t $nr_busy_threads & 

#Now launch sleeping ebizzy..
parse_threads $2
nr_busy_threads=$?

#Performance with 1 thread
echo "Starting Calibration"
echo "./ebizzy -s 4096 -S 10 -t 1"
records=`./ebizzy -s 4096 -S 10 -t 1 | grep records | cut -d " " -f 1`
echo "Finished Calibration..."

at=`echo "get_a($records,$3)" | bc -l helper.b`
delay=`echo "get_i($records,$3)" | bc -l helper.b`

#Now run ebizzy again
echo "Starting Actual Run"
echo "./ebizzy -s 4096 -S $4 -t $nr_busy_threads -a $at -i $delay"
./ebizzy -s 4096 -S $4 -a $at -i $delay -t $nr_busy_threads

echo 0 > /proc/sys/kernel/powersave-nap

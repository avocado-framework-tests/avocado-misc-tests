#!/bin/sh
if [ $# != 3 ]
then
        echo "Usage:"
        echo "$0 Utilization Num_Threads Time"
        exit
fi

#Performance with 1 thread
echo "Starting Calibration"
echo "./ebizzy -s 4096 -S 10 -t 1"
records=`./ebizzy -s 4096 -S 10 -t 1 | grep records | cut -d " " -f 1`
echo "Finished Calibration..."
#echo $records

at=`echo "get_a($records,$1)" | bc -l helper.b`
echo $at
delay=`echo "get_i($records,$1)" | bc -l helper.b`
echo $delay

#Now run ebizzy again
echo "Starting Actual Run"
echo "./ebizzy -s 4096 -S $3 -t $2 -a $at -i $delay"
./ebizzy -s 4096 -S $3 -a $at -i $delay -t $2

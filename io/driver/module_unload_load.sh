#!/bin/bash

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: 2016 IBM
# Author: Harsha Thyagaraja <harshkid@linux.vnet.ibm.com>

CONFIG_FILE="$AVOCADO_TEST_DATADIR"/config
BUILT_IN_DRIVERS=`cat /lib/modules/$(uname -r)/modules.builtin |awk -F"/" '{print $NF}'|sed 's/\.ko//g'`
DRIVERS=`find /lib/modules/$(uname -r)/ -name \*.ko | awk -F"/" '{print $NF}'|sed 's/\.ko//g'`
ERR=""
PASS=""
[[ -z $ITERATIONS ]] && ITERATIONS=10


module_load() {
    echo "Reloading driver $1"
    modprobe $1
    if [[  $? != 0  ]]; then
        echo "Failed to load driver module $1"
        ERR="$ERR,load-$1"
        break;
    fi
    echo
}


module_unload() {
    for i in $( cat $CONFIG_FILE | grep "$1=" | awk -F'=' '{print $2}' ); do
        module_unload $i
        if [[  $? != 0  ]]; then
            return
        fi
    done
    echo "Unloaded driver $1"
    rmmod $1
    if [[  $? != 0  ]]; then
        echo "Failed to unload driver module $i"
        ERR="$ERR,unload-$1"
        break;
    fi
}


for driver in $DRIVERS; do
    echo "Starting driver module load/unload test for $driver"
    echo
    for j in $(seq 1 $ITERATIONS); do
        echo $BUILT_IN_DRIVERS | grep $driver > /dev/null
        if [[ $? == "0" ]]; then
            echo $driver" is builtin and it cannot be unloaded"
            break;
        fi
        if [[ $(lsmod | grep -w ^$driver | awk '{print $NF}') != '0' ]]; then
            echo $driver" has dependencies and it cannot be unloaded"
            break;
        fi
        module_unload $driver
        # Sleep for 5s to allow the module unload to complete
        sleep 5
        module_load $driver
        # Sleep for 5s to allow the module load to complete
        sleep 5
    done
    if [[  $j -eq $ITERATIONS  ]]; then
        echo "Finished driver module load/unload test for $driver"
        PASS="$PASS,$driver"
    fi
    echo
    echo "Completed driver module load/unload test for $driver"
    echo
done
echo
if [[  "$ERR"  ]]; then
    echo "Some modules failed to load/unload: ${ERR:1}"
    exit 1
fi
if [[  "$PASS"  ]]; then
    echo "Successfully loaded/unloaded: ${PASS:1}"
fi

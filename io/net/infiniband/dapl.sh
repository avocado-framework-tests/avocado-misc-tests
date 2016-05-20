#!/bin/bash -e

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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
# Author: Manvanthara B Puttashankar <manvanth@linux.vnet.ibm.com>

# This Program runs dapltest tests on client and server for the interfaces
# specified in config file in the data directory. It runs for 5 different
# inputs, as specified in multiplexer file.

PATH=$(avocado "exec-path"):$PATH

# Install dependencies
if [[ `python -c 'from avocado.utils.software_manager import SoftwareManager; \
   print SoftwareManager().install("dapl*")'` == 'False' ]]
then
    avocado_debug 'Dapl Packages not installed'
    exit
fi

# Load Modules
modules=(ib_uverbs ib_ucm ib_cm ib_mad ib_sa ib_umad ib_addr rdma_cm rdma_ucm \
    ib_core mlx4_core mlx5_core mlx5_ib ib_ipoib mlx4_en mlx4_ib)
for i in "${modules[@]}"; do
    modprobe $i
done

# Parsing Input
CONFIG_FILE="$AVOCADO_TEST_DATADIR"/config
params=(DAPL_IF1 DAPL_IF2 PEER_IP)
for i in "${params[@]}"; do
    eval $(cat $CONFIG_FILE | grep -w $i)
done
host_param=$(eval "echo $HOST_PARAM")
peer_param=$(eval "echo $PEER_PARAM")

# Timeout
timeout=2m

# Runs dapltest on client and server
dapl_exec()
{
    if [[ "$3" == "" ]]; then
        avocado_info "Client specific run for $1($2)"
        avocado_debug "$1 $2"
        timeout $timeout $1 $2 || { echo "Client specific run failed"; exit 1; }
    else
        avocado_info "Client data for $1($3)"
        ssh $PEER_IP "timeout $timeout $1 $2  > /tmp/ib_log 2>&1 &" || \
            { echo "Peer run failed"; exit 1; }

        sleep 5
        avocado_debug "$1 $3 "
        timeout $timeout $1 $3 || { echo "Client run failed"; exit 1; }

        sleep 5
        avocado_info "Server data for $1($2)"
        avocado_debug "$1 $2"
        ssh $PEER_IP "timeout $timeout cat /tmp/ib_log; rm -rf /tmp/ib_log"
    fi
}

# Parses the input values and calls dapl_exec() to execute dapltest
testdapl()
{
    if [[ $DAPL_IF1 != "" ]] && [[ $DAPL_IF2 != "" ]]; then
        if type "dapltest" > /dev/null
        then
            dapl_exec dapltest "$host_param" "$peer_param"
        else
            avocado_debug "Cmd dapltest doesn't exist, Test will be skipped"
            exit 1
        fi
    else
        avocado_debug "DAPL interface not specified, Test will be skipped"
    fi
}

# MAIN

testdapl
exit 0

#!/bin/bash -e
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
<<<<<<< HEAD
timeout=2m
=======
to=2m
>>>>>>> 3906e2696c14a3e053a283d4a8a60dcd393293e9

# Runs dapltest on client and server
dapl_exec()
{
    if [[ "$3" == "" ]]; then
        avocado_info "Client specific run for $1($2)"
        avocado_debug "$1 $2"
<<<<<<< HEAD
        timeout $timeout $1 $2 || { echo "Client specific run failed"; exit 1; }
    else
        avocado_info "Client data for $1($3)"
        ssh $PEER_IP "timeout $timeout $1 $2  > /tmp/ib_log 2>&1 &" || \
=======
        timeout $to $1 $2 || { echo "Client specific run failed"; exit 1; }
    else
        avocado_info "Client data for $1($3)"
        ssh $PEER_IP "timeout $to $1 $2  > /tmp/ib_log 2>&1 &" || \
>>>>>>> 3906e2696c14a3e053a283d4a8a60dcd393293e9
            { echo "Peer run failed"; exit 1; }

        sleep 5
        avocado_debug "$1 $3 "
<<<<<<< HEAD
        timeout $timeout $1 $3 || { echo "Client run failed"; exit 1; }
=======
        timeout $to $1 $3 || { echo "Client run failed"; exit 1; }
>>>>>>> 3906e2696c14a3e053a283d4a8a60dcd393293e9

        sleep 5
        avocado_info "Server data for $1($2)"
        avocado_debug "$1 $2"
<<<<<<< HEAD
        ssh $PEER_IP "timeout $timeout cat /tmp/ib_log; rm -rf /tmp/ib_log"
=======
        ssh $PEER_IP "timeout $to cat /tmp/ib_log; rm -rf /tmp/ib_log"
>>>>>>> 3906e2696c14a3e053a283d4a8a60dcd393293e9
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

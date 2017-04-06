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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

# Tests the network driver and interface with 'ethtool' command.
# Different parameters are specified in Parameters section of multiplexer file.
# Interfaces are specified in Interfaces section of multiplexer file.
# This test needs to be run as root.

PATH=$(avocado "exec-path"):$PATH

# Install dependencies
python << END
from avocado.utils.software_manager import SoftwareManager;
if SoftwareManager().check_installed("ethtool") is False:
    print "Ethtool is not installed"
    if SoftwareManager().install("ethtool") is False:
        print "Not able to install ethtool"
        exit(1)
END

[[ -z $interface ]] && interface="eth1"
echo "Interface: $interface"

ip link show dev $interface > /dev/null 2>&1 || {
    avocado_warn "$interface does not exist"
    exit 1
}

echo "Parameter: ${arg}"

ifup $interface
for command in ifdown ifup; do
    sleep 5
    $command $interface
    sleep 5
    echo "Ethool, $command:"
    output_file="$AVOCADO_TEST_OUTPUTDIR/output_$command"
    ethtool ${arg} ${interface} $action_elapse > "$output_file" 2>&1
    error=${PIPESTATUS[0]}

    if [ $error == 0 ]; then
        avocado_debug "PASS"
    elif grep "Operation not supported" $output_file; then
        avocado_debug "PASS (Not supported return:$error)"
    elif grep "no stats available" $output_file; then
        avocado_debug "PASS (No stats available return:$error)"
    elif [[ "${arg}" = "-t" && "$command" = "ifdown" ]]; then
        avocado_debug "PASS (ethtool -t may fail when iface is down)"
    else
        avocado_debug "FAIL (return: $error)"
        exit $error
    fi
done
ifup $interface
sleep 5

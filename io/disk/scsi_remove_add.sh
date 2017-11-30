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

# This Test removes and adds back a scsi device in all the specified PCI 
# domains specified in the 'multiplexer' file.
# Runs the test for '0000:01:00.0' if no value for pci domain is given.
# This test needs to be run as root. 

PATH=$(avocado "exec-path"):$PATH

# Install dependencies
python << END
from avocado.utils.software_manager import SoftwareManager;
if SoftwareManager().check_installed("lsscsi") is False:
    print "lsscsi is not installed"
    if SoftwareManager().install("lsscsi") is False:
        print "Not able to install lsscsi"
        exit(1)
END

[[ -z $pci_device ]] && pci_device="0000:01:00.0" 

echo "PCI Device: $pci_device"
device_list_output=($(ls -l /dev/disk/by-path/ | grep "$pci_device" | awk '{print $NF}'))
if [[ -z $device_list_output ]]; then
    avocado_debug "No Devices in PCI ID $pci_device"
    exit
fi
for (( device_id=0; device_id<${#device_list_output[@]}; device_id++ )); do
    device=$(echo ${device_list_output[device_id]} | sed -e 's/\// /g' | awk '{print $NF}')
    scsi_num=$(lsscsi | grep $device | awk  -F'[' '{print $NF}' | awk  -F']' '{print $1}')
    if [[ -z $scsi_num ]]; then
        echo "No SCSI Devices in PCI ID $pci_device"
        continue
    fi
    scsi_num_seperated=$(echo $scsi_num | sed -e 's/:/ /g')
    avocado_debug $device
    echo "Current Config"
    lsscsi
    echo "deleting $scsi_num"
    echo 1 > /sys/block/$device/device/delete
    sleep 5
    lsscsi
    echo "$scsi_num deleted"
    echo "adding $scsi_num back"
    echo "scsi add-single-device $scsi_num_seperated" > /proc/scsi/scsi
    sleep 5
    lsscsi
    echo "$scsi_num added back"
    echo
done

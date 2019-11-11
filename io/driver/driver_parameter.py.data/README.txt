This Program Verifies the driver parameters and script takescare of unloading the dependant modules, if any.
Each driver being qualified should have an seperate yaml file.

This script should be run as root.

Inputs
------
module: Module name for which the parameter test is being excercised.
interface: Specify one of the interface which has IP configured. 
host_ip: IP address to be used for the host interface
netmask: netmask for the IP address
peer_ip: IP address to be used for the host interface  
sysfs_check_required: For Drivers which supports sysfs entry for paramters value mention 1, If not 0.


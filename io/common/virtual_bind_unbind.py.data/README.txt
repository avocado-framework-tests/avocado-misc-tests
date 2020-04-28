This script will unbind and bind the virtualized device
for vnic, vscsi, vfc,veth as many times as specified by 
the user

Inputs Needed :
------------------------------------
virtual_device - virtual device for the test interface or disk name.
virtual_slot - to get slot for vfc use lsslot, as vfc do not give correct slot number 
               using lscfg -vl ( all other vdevices gives correct slot using lscfg -vl)
               ex: U9009.42A.13C6F1W-V2-C201
host_ip - specify ip for the interface for ip configuration if vnic or veth device.
netmask - specify netmask for the interface for ip configuration if vnic or veth device.
count - The number of times the unbind and bind test has to be executed.
peer_ip - IP of the peer if vnic or veth device to verify network connectivity after unbind/bind.

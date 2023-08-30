Tcpdump Test
------------
Runs tcpdump on specified interface for specified number of packets.
If dropped packets are more than acceptable level, as specified,
then test fails.

Inputs
------
interface: test interface name env3 or mac addr 02:5d:c7:xx:xx:03
count: number of packets
drop_accepted: interface packet drop accepted in percentage (eg 10 for 10%)
host-IP : Specify host-IP for ip configuration.
netmask : specify netmask for ip configuration.

Prerequisites
-------------
python module netifaces is needed (pip install netifaces)

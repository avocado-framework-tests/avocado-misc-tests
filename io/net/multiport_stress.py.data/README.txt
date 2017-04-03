This is a test to run multiport stress on the NIC adapter.
To begin with, the test runs a Ping test on multiple interfaces
of a network adapter parallely.

The yaml files has 3 parameters: host_interfaces and peer_ips.
host_interfaces takes multiple NIC interface names separated by comma.
peer_interfaces takes multiple peer ip's separated by comma.
packet_size is the number of packets to be transferred.

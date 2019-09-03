This is a test to run multiport stress on the NIC adapter.
To begin with, the test runs a Ping test on multiple interfaces parallely
which is followed by Flood ping

The yaml files has 5 parameters:
    host_interfaces takes multiple NIC interface names separated by comma.
    peer_ips takes multiple peer ip's separated by comma.
    count is the number of packets to be transferred. Default value is 1000.
    host_ips based on interface specify number of ip address separated by comma
    for ip configuration.
    netmask specify the netmask for ip configuration.

This is a test to run multiport stress on the NIC adapter.
To begin with, the test runs a Ping test on multiple interfaces parallelly
which is followed by Flood ping

The yaml files has following parameters:
    interfaces takes multiple NIC interface names separated by spaces ex  interfaces: "env3 env4" or mac addresses "02:5d:c7:xx:xx:03  02:5d:c7:xx:xx:04"
    peer_ips takes multiple peer ip's separated by space ex : peer_ips: "102.10.10.188 202.20.20.188"
    count is the number of packets to be transferred. Default value is 1000.
    host-IP is Specify for ip configuration pass space separated host_ips: "102.10.10.188 202.20.20.188"
    netmask is specify for ip configuration.

VLAN Testcase:

This testcase covers below 3 scenarios.

Scenario 1: It keeps both host & peer in default VLAN id, VLAN 1.
            Now ping each other. it should PASS
Scenario 2: It keeps host in vlan 1 and Peer in vlan 2230.
            Now ping. it should FAIL
Scenario 3: It keeps both in the vlan id (taken from yaml file),
            and create vlan interfaces and then ping.
            It should PASS.

Parameters:

NIC Switch Details:
switch_name: "x.xx.xx.xxx"
userid: "admin"
password: "**********"

VLAN number for the ports to be configured
vlan_num: 1

Host & Peer port ID's
host_port: 38
peer_port: 45

Host & Peer Interfaces for the VLAN test
interface: "enp128s0f4d1"
peer_interface: "enP4p1s0f2"

Peer Details
peer_ip: "x.xx.xx.xxx"
peer_user: "root"
peer_password: "********"
cidr_value: "24"

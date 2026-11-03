VETH DLPAR TEST
--------------
The test performs veth device remove and add from the host LPAR using drmgr.
The virtual slot of the interface is discovered automatically (lsslot).

interface : Provide veth interface name or mac address like "c2:33:44:64:66" of interface to be tested
host_ip: IP address to be configured
netmask: Netmask like 255.255.255.255
peer_ip: Peer IP address to ping peer network
num_of_dlpar: Number of times test to be repeated
lockdown_enable: (optional) True to enable kernel lockdown before the test
lockdown_mode: (optional) integrity or confidentiality, default integrity

Use veth_dlpar_lockdown.yaml to run the test with kernel lockdown enabled.

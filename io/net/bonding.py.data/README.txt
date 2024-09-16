description:
------------------------
This Program to test bonding, bonding means bind multiple network interfaces together into a single channel using the bonding kernel module and a special network interface called a channel bonding interface. Channel bonding enables two or more network interfaces to act as one, simultaneously increasing the bandwidth and providing redundancy.
The modes are:
    mode=0 (Balance Round Robin)
    mode=1 (Active backup)
    mode=2 (Balance XOR)
    mode=3 (Broadcast)
    mode=4 (802.3ad)
    mode=5 (Balance TLB)
    mode=6 (Balance ALB)
In this test we enable mode 0 in peer machine and enable all modes in host machine.
Note:
1. For Infiniband based devices only mode 1 (Active backup) is supported. Due to which the expectation is that test environment is allways connected via Switch (i.e peer_bond_needed is set to False).

-----------------------------
Inputs Needed To Run Tests:
------------------------------
bond_interfaces --> Interfaces names or mac address space separated in the Host machine requird for Bonding
Note: example bond_interfaces = "ib0 ib1", Space between the interface names
peerip --> peer ip address
peer_interfaces --> This is needed only if a Bond interface is to be created in the Peer machine, space separated names if specifying multiple
bond_name --> to create bond
username --> user name
host_ips --> space separated ip addresses
peer_bond_needed --> If bond interface is needed to be created in Peer machine
peer_wait_time --> Time required for the interfaces in Peer machine to come up
sleep_time --> Generic Sleep time used in the test
-----------------------
Requirements:
-----------------------
1. install netifaces using pip
command: pip install netifaces

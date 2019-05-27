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
-----------------------------
Inputs Needed To Run Tests:
------------------------------
bond_interfaces --> Interfaces in the Host machine requird for Bonding
peerip --> peer ip address
peer_interfaces --> This is needed only if a Bond interface is to be created in the Peer machine.
bond_name --> to create bond
username --> user name
peer_bond_needed --> If bond interface is needed to be created in Peer machine
peer_wait_time --> Time required for the interfaces in Peer machine to come up
sleep_time --> Generic Sleep time used in the test
-----------------------
Requirements:
-----------------------
1. install netifaces using pip
command: pip install netifaces
2. Generate sshkey for your test partner to run the test uninterrupted.(Have a passwordless ssh between the peers)
3. Make sure IPs are set for interfaces to be used, via configuration file. ifup / ifdown should set the IPs back.

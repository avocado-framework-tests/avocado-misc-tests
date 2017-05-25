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
host_interfaces --> host interfaces to perform test
peerip --> peer ip address.
peer_interfaces --> This is needed only if a Bond interface is to be created in the Peer machine.
bondname --> to create bond
bonding_mode --> bonding mode
username --> user name
peer_bond_needed --> This can be set to True/False. True indicating that a Bond interface has to be created n the peer machine and False indicating the opposite.  
peer_wait_time --> This value should be set to the time that a Bond interface takes to come up in the Peer.

-----------------------
Requirements:
-----------------------
1. install netifaces using pip
command: pip install netifaces
2. Generate sshkey for your test partner to run the test uninterrupted.(have a passwordless ssh between the peers)

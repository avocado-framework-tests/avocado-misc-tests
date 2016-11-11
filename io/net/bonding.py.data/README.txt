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
Iface1 --> host interface to perform test
Iface2 --> host interface to perform test
peerip --> peer ip address
peerif2 --> peer interface to perform test
bondname --> to create bond
bonding_mode --> bonding mode
-----------------------
Requirements:
-----------------------
1. install netifaces using pip
command: pip install netifaces
2. Generate sshkey for your test partner to run the test uninterrupted.(have a connection less ssh between the peers)

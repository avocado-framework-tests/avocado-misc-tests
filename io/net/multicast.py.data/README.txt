description:
------------------------
This Program to check receive multicast. in peer machine multicast group is configured, so we use the ping tool to send icmp echo request packets to all id's in group. if this icmp request received by host then we conclude that host is in multicast group.
-----------------------------
Inputs Needed To Run Tests:
-----------------------------
peerip ---> IP of the Peer interface to be tested
user_name---> name of the user
interface --> host test interface name eth1 or mac address 02:5d:xx:xx:xx:xx 
host-IP  ---> Specify host-IP for ip configuration.
netmask  ---> specify netmask for ip configuration.
-----------------------
Requirements:
-----------------------
1. Generate sshkey for your test partner to run the test uninterrupted.(have a connection less ssh between the peers)
2. install netifaces using pip
command: pip install netifaces

Description:
------------------------
This Program runs Ip over Ib test on client and server for the interface specified in yaml file. Both the machines should have infiniband adapters.
This test run with two options:
1)datagram
2)connected
Measurement for Time specified in yaml file are seconds.
-----------------------------
Inputs Needed To Run Tests:
-----------------------------
PEER_IP ---> IP of the Peer interface to be tested
Iface --> interface on which test run
-----------------------
Requirements:
-----------------------
1.Generate sshkey for your test partner to run the test uninterrupted.
2.install nteifaces using pip.
command: pip install netifaces
3.user should have root access to both client machine and peer machine.

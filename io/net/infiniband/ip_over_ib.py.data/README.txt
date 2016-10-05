This Program runs Ip Over IB tests on client and server for the interface specified in yaml file. Both the machines should have infiniband adaptors.
This test run with two options:
1)connected
2)datagram
Measurement for Time specified in yaml file are seconds.
-----------------------------
Inputs Needed Run Tests:
-----------------------------
PEER_IP	    - IP of the Peer interface to be tested
install nteifaces using pip
  command: pip install netifaces
install git
Note:
-----
1. Generate sshkey for your test partner to run the test uninterrupted.

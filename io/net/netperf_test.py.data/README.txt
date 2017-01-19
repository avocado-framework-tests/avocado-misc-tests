Description:
------------------------
Netperf is a benchmark that can be used to measure the performance of
many different types of networking. It provides tests for both
unidirectional throughput, and end-to-end latency.

Inputs Needed To Run Tests:
-----------------------------
PEERIP		    - IP of the Peer interface to be tested
PEERUSER        - Username in Peer system to be used
Iface		    - interface on which test run
timeout		    - Timeout
NETSERVER_RUN	- Whether to run netserver in peer or not

Requirements:
-----------------------
1.Generate sshkey for your test partner to run the test uninterrupted.
2.install nteifaces using pip.
command: pip install netifaces
3.user should have root access to both client machine and peer machine.

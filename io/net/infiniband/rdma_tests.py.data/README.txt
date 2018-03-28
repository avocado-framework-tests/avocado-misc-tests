Description:
------------------------
This Program runs RDMA tests on client and server for the interface specified in yaml file.
Both the machines should have infiniband adapters.
It runs for test options specified.

This test run with below tools:
ib_send_bw
ib_write_bw
ib_read_bw
ib_atomic_bw
ib_send_lat
ib_write_lat
ib_read_lat
ib_atomic_lat

Measurement for Time specified in yaml file are seconds.
-----------------------------
Inputs Needed To Run Tests:
-----------------------------
test_opt    - options for basic test
peer_ip     - IP of the Peer interface to be tested
interface   - interface on which test run
CA_NAME     - CA Name, got from 'ibstat' command
PEERCA      - Peer CA Name, got from 'ibstat' command
PORT_NUM    - Port Num, got from 'ibstat' command
PEERPORT    - Peer Port Num, got from 'ibstat' command
timeout     - timeout for commands
-----------------------
Requirements:
-----------------------
1. Generate sshkey for your test partner to run the test uninterrupted.
2.install MOFED iso
3.install nteifaces using pip
command: pip install netifaces
4.install perf package

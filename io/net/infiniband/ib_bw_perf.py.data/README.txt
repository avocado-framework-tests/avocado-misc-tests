Description:
------------------------
This Program runs bandwidth performance tests on client and server for the interface specified in yaml file. Both the machines should have infiniband adapters. It runs for test options and extended test options. Test options are mandatory but extended test options are depends upon user interst. if user want to execute tests for extended test options user need to set flag field in yaml file, otherwise unset flag.Test options are run on all distro's, but extended test options depends on distro.
This test run with four tools:
1)ib_send_bw
2)ib_write_bw
3)ib_read_bw
4)ib_atomic_bw
Measurement for Time specified in yaml file are seconds.
-----------------------------
Inputs Needed To Run Tests:
-----------------------------
test_opt    - options for basic test
ext_opt     - options for extended test
ext_flag    - flag to indicate whether to run extended tests or not (1 to run)
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

Description:
------------------------
This Program runs latency performance tests on client and server for the interface specified in yaml file. Both the machines should have infiniband adaptors. It runs for test options and extended test options. Test options are mandatory but extended test options are depends upon user interst. if user want to execute tests for extended test options user need to set falg field in yaml file, otherwise unset flag.Test options are run on all distro's, but extended test options depends on distro.
This test run with four tools:
1)ib_send_lat
2)ib_write_lat
3)ib_read_lat
4)ib_atomic_lat
Measurement for Time specified in yaml file are seconds.
-----------------------------
Inputs Needed To Run Tests:
-----------------------------
PEER_IP ---> IP of the Peer interface to be tested
install nteifaces using pip
command: pip install netifaces
install perf package
install MOFED iso
-----------------------
Requirements:
-----------------------
1. Generate sshkey for your test partner to run the test uninterrupted.

This Program runs bandwidth performance tests on client and server for the interface specified in yaml file. It runs for test options and extended test options. Both machine should have infiniband adaptors. Test options are mandatory but extended test options are depends upon user interst. if user want to execute tests for extended test options user need to set falg field in yaml file, otherwise unset flag.Test options are run on all distro's, but extended test options depends on distro.
This test run with four tools:
1)ib_send_bw
2)ib_write_bw
3)ib_read_bw
4)ib_atomic_bw
Measurement for Time specified in yaml file are seconds.
-----------------------------
Inputs Needed Run Tests:
-----------------------------
PEER_IP	    - IP of the Peer interface to be tested
install nteifaces using pip
  command: pip install netifaces
install perf package
Note:
-----
1. Generate sshkey for your test partner to run the test uninterrupted.

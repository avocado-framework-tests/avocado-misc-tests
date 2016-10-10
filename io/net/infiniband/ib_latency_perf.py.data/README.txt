Description:
------------------------
This Program runs latency performance tests on client and server for the interface specified in yaml file. Both the machines should have infiniband adapters. It runs for test options and extended test options. Test options are mandatory but extended test options are depends upon user interst. if user want to execute tests for extended test options user need to set flag field in yaml file, otherwise unset flag.Test options are run on all distro's, but extended test options depends on distro.
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
Iface --> interface on which test run
ext_flag--> if it is 0 then test run for test_opt, if it is 1 then test run for both test_opt and ext_test_opt
-----------------------
Requirements:
-----------------------
1. Generate sshkey for your test partner to run the test uninterrupted.
2.install MOFED iso
3.install nteifaces using pip
command: pip install netifaces
4.install perf package

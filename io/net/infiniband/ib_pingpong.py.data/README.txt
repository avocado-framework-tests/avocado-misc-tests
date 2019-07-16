This Program runs pingpong tests on client and server for the interface specified in yaml file. It runs for test options and extended test options. Test options are mandatory but extended test options are depends upon user interst. if user want to execute tests for extended test options user need to set falg field in yaml file, otherwise unset flag.
This test run with four tools:
1)ibv_ud_pingpong
2)ibv_uc_pingpong
3)ibv_rc_pingpong
4)ibv_srq_pingpong
-----------------------------
Inputs Needed Run Tests:
-----------------------------
PEER_IP	    - IP of the Peer interface to be tested
install nteifaces using pip
  command: pip install netifaces
install MOFED iso
Note:
-----
1. Generate sshkey for your test partner to run the test uninterrupted.
2. Ensure to run the tests from cfg file so that all the MTU sizes can be tested accordingly.

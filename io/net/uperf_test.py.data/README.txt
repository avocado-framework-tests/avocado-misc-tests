Description:
------------------------
Unified Performance Tool or uperf for short, is a network
performance measurement tool that supports execution of
workload profiles

Inputs Needed To Run Tests:
-----------------------------
interface		- interface on which test run
peer_ip			- IP of the Peer interface to be tested
peer_user_name		- Username in Peer system to be used
UPERF_SERVER_RUN	- Whether to run netserver in peer or not (1 to run, 0 to not run)
EXPECTED_THROUGHPUT	- Expected Throughput as a percentage (1-100)

Requirements:
-----------------------
1. Generate sshkey for your test partner to run the test uninterrupted.
2. Install netifaces using pip. command: pip install netifaces
3. Install dependant packages for uperf tools to be compiled in the
Peer machine. 
For Rhel and Sles distros: lksctp-tools, lksctp-tools-devel
For Ubuntu: libsctp1, libsctp-dev, lksctp-tools

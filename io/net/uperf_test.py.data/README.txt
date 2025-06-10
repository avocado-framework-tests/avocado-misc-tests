Description:
------------------------
Unified Performance Tool or uperf for short, is a network
performance measurement tool that supports execution of
workload profiles

Inputs Needed To Run Tests:
-----------------------------
interface		- test interface name eth2 or mac addr 02:5d:c7:xx:xx:03 
peer_ip			- IP of the Peer interface to be tested
peer_user		- Username in Peer system to be used
UPERF_SERVER_RUN	- Whether to run netserver in peer or not (1 to run, 0 to not run)
EXPECTED_THROUGHPUT	- Expected Throughput as a percentage (1-100)
host-IP                 - Specify host-IP for ip configuration.
netmask                 - specify netmask for ip configuration.

Requirements:
-----------------------
1. Generate sshkey for your test partner to run the test uninterrupted.
2. Install netifaces using pip. command: pip install netifaces
3. Install dependent packages for uperf tools to be compiled in the
Peer machine. 
For Rhel and Sles distros: lksctp-tools, lksctp-tools-devel
For Ubuntu: libsctp1, libsctp-dev, lksctp-tools

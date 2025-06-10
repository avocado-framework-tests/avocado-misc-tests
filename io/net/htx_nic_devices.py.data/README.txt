HTX Stress test for NIC devices

This testcase prepares the all interfaces provided in yaml file
ready for the execution and also updates bpt file with necessary
data. Once configuration is done test starts executing the stress
test on all the interfaces provided in input yaml file

User can mention the time limit to be executed in minutes.

This test assumes below packages to be installed on both host & peer
	pexpect
	htx

The net_id should be >= 100 and  <= 223
htx_rpm_link :  provide base url location of .rpm for htx installation

Hostname for the host and the peer servers must always be set to the
fully qualified domain name of the server IP. If not, set it using
hostnamectl command

If the test interfaces are the ones with Public IP's, they cannot be
used to run this script as this script will change the IP's for them
based on the net_id value. If this happens, none of the Peer commands
will be executed as ssh will not happen and the test will fail.
Make sure that there is a separate interface configured with Public IP
and is left untouched.

Please pass these parameters as space separarted values if there are more than one inputts
host_interfaces: "env2 env5" or "02:5d:c7:xx:xx:03 02:5d:c7:xx:xx:04"
peer_interfaces: "eht1 eth2"
net_ids: "150 151"
host_ips: "102.10.10.188 202.20.20.188"

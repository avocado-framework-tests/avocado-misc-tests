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

Hostname for the host and the peer servers must always be set to the
fully qualified domain name of the server IP. If not, set it using
hostnamectl command

If the test interfaces are the ones with Public IP's, they cannot be
used to run this script as this script will change the IP's for them
based on the net_id value. If this happens, none of the Peer commands
will be executed as ssh will not happen and the test will fail.
Make sure that there is a separate interface configured with Public IP
and is left untouched.

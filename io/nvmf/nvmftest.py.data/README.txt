This test Suite covers the following tests.
* target config
* nvmf discover
* nvmf connect
* nvmf disconnect
* nvmf connect cfg
* nvmf disconnect cfg
* clear target config

Prerequisites:
--------------
1. Install MOFED with NVMf enabled on both test system and peer
2. Generate sshkey and copy to your peer to run the test uninterrupted
(Have a passwordless ssh between the peers)

Inputs Needed (in multiplexer file):
------------------------------------
* namespaces    -   comma separated namespaces on the peer to configure for NVMf
* peer_ips      -   comma separated peer IP address

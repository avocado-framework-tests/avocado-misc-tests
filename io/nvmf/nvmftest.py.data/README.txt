This test Suite covers the following tests.
* target config
* nvmf discover
* nvmf connect
* nvmf disconnect
* nvmf connect cfg
* nvmf disconnect cfg
* clear target config

Note: Only one namespace and peer ip are supported right now via the test.

Prerequisites:
--------------
1. Install MOFED with NVMf enabled on both test system and peer
2. Generate sshkey and copy to your peer to run the test uninterrupted
(Have a passwordless ssh between the peers)

Inputs Needed (in multiplexer file):
------------------------------------
* namespace	-	namespace on the peer to configure for NVMf
* peer_ip	-	peer IP address

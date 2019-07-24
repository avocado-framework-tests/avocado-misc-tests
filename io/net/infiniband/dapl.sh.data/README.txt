This Program runs Direct Access Programming Library (DAPL) tests on client and server for the interfaces specified in config file (dat.conf). It runs for 5 different inputs, as specified in multiplexer file.

Inputs Needed in config file:
-----------------------------
peer_ip             - IP of the Peer interface to be tested
dapl_interface      - RDMA Interface on the Host. Can be taken from the file dat.conf (dat.conf location differs based on OS)
dapl_peer_interface - RDMA Interface on the Host. Can be taken from the file dat.conf (dat.conf location differs based on OS)

Note:
-----
1. Ensure the dat.conf has details of your dapl interface under test (refer: man dat.conf)
    a.  For infiniband interface the ofa-v2-ib0 entry is available by default in /etc/dat.conf
    b.  However for ROCE devices, Interface being tested needs to be added manually for both host and peer. For example if your interface is enP24p1s0f0. Add the below line manually in /etc/dat.conf
          ofa-v2-enP24p1s0f0 u2.0 nonthreadsafe default libdaplofa.so.2 dapl.2.0 "enP24p1s0f0 0" ""
2. Generate sshkey for your test partner to run the test uninterrupted. 


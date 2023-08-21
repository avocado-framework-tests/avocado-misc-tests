The network sriov test for adding and removing logical
sriov device.we can create multiple logical device.

1. input requirment for normal SRIOV logical device
---------------------------------------------------
hmc_username = Specify the HMC user name.
hmc_pwd = Specify the HMC password.
sriov_adapter = Specify the sriov adapter loc code for test.
sriov_port: specify adapter port for test.
ipaddr = ip address for ip configuration in sriov logical interface.
netmask = specify the netmask for ip configuration.
peer_ip = specify peer ip address.
mac_id = mac address for sriov logical device.

Note(A):
--------
when YAML parameters given with space seperated, the script creates "N" number of
logical ports with Network settings assocaited with it.

Ex: To create 2 SRIOV logical ports coming from each port when card having 2 physical port.

sriov_adapter: "U78CD.001.FZHAE88-P2-C6 U78CD.001.FZHAE88-P2-C6"
sriov_port: "0 1"
ipaddr: "192.168.180.1 192.168.190.1" etc ..

The above scenario creates 2 SRIOV logical ports each one from each port i.e port 0 and port 1


2. input requiremnet for max SRIOV logical device
--------------------------------------------------
along with normal SRIOV logical device parameters,max SRIOV logical device required
 
max_sriov_ports = Specify the max number of logical SRIOV ports to be created.

Note:
-----
Note(A) applies for max_sriov_ports also, like when 2 parameters given by space seperated,
the script will creates one logical SRIOV port from each Physical port upto user given number.

Ex:
sriov_adapter: "U78CD.001.FZHAE88-P2-C6 U78CD.001.FZHAE88-P2-C6"
sriov_port: "0 1"
max_sriov_ports : 32

This scenario creates 64 SRIOV logical port 32 ports created on each port.
Incase of single sriov_port given,it creats 32 logical ports.


3.The same test can be used to create Migratable SRIOV logical device (HNV)

Make sure you are using the correct yamls for Migratable SRIOV
sriov_device_test.py.data/migratable_sriov_veth.yaml
sriov_device_test.py.data/migratable_sriov_vnic.yaml

Some new parameters have been added for Migratable SRIOV support

migratable = Make sure it is HNV SRIOV  (0 or 1)
backup_device_type =  mention the type of backup device "veth" or "vnic"
backup_veth_vnetwork = mention the virtual network name ex : "VLAN1-ETHERNET0"
vnic_sriov_adapter = mention location code for vnic backup devicce ex :  "U78D5.ND2.CSS140C-P1-C3-C1"
vnic_port_id = specify which port of the vnic backup adapter (0/1/2/3)
max-capacity = max capacity of physical port of vnic adapter available
capacity = port capacity to use (default 2)
vios-lpar-name = mention the vios lpar name in hmc
failover-priority = optional,  default 50


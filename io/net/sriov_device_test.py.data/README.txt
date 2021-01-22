The network sriov test for adding and removing logical
sriov device.we can create multiple logical device.
input requirment for normal SRIOV logical device
----------------
hmc_username = Specify the HMC user name.
hmc_pwd = Specify the HMC password.
sriov_adapter = Specify the sriov adapter loc code for test.
sriov_port: specify adapter port for test.
ipaddr = ip address for ip configuration in sriov logical interface.
netmask = specify the netmask for ip configuration.
peer_ip = specify peer ip address.
mac_id = mac address for sriov logical device.

The same test can be used to create Migratable SRIOV logical device (HNV)

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

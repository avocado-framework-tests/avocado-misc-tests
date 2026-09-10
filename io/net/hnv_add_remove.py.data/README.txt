HNV DLPAR add/remove loop test with optional kernel lockdown validation.

Test methods
------------
test_hnv_dlpar_loop
    Add and remove HNV logical device num_of_dlpar times.

test_hnv_dlpar_loop_with_lockdown
    Same loop with kernel lockdown active. Asserts lockdown level is
    unchanged before and after every iteration.
    Set lockdown_enable: true in YAML to run this test.

YAML files
----------
Pick one based on the HNV backup device type:

  hnv_add_remove_veth.yaml  -- veth backup (virtual Ethernet network)
  hnv_add_remove_vnic.yaml  -- vNIC backup (SR-IOV adapter on VIOS)

Parameters
----------
hmc_username, hmc_pwd       HMC credentials
manageSystem                Managed system name
sriov_adapter               Physical slot location code(s)
sriov_port                  Physical port ID(s)
mac_id                      MAC address(es) for the logical port(s)
ipaddr, netmasks, peer_ips  IP config and ping target per port
migratable                  Must be true for HNV
num_of_dlpar                Add/remove iterations (default: 1)
lockdown_mode               integrity or confidentiality (default: integrity)
lockdown_enable             true to run lockdown test (default: false)

veth only:  backup_veth_vnetwork
vNIC only:  vnic_sriov_adapter, vnic_port_id, vios_name

Note: space-separated values in sriov_adapter/sriov_port/mac_id/
ipaddr/netmasks/peer_ips create one logical port per entry.

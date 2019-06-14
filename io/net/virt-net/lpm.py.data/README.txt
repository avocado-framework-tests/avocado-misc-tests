Explanation of the input parameters:
------------------------------------
slot_num                Slot number on which the Network virtualized interface will be added. Should be 3 - 2999, and free currently.
vios_names              Comma separated name of the vios used to add/remove Network virtualized interface
sriov_adapters	        Comma separated location code (DRC) of the the adapters that is assigned to the hypervisor
sriov_ports             Comma separated ports using which the Network virtualized interface will be added/removed
                        Ex: if the adapter has 2 ports and the Network virtualized interface should be added using Port 1, mention value as 0
                            else mention 1 if Network virtualized interface should be added using Port 2s

bandwidth               The percentage of the ports bandwidth this Network virtualized interface is entitled to
remote_server	        Remote server
remote_vios_names       Comma separated name of the remote vios used to add/remove Network virtualized interface
remote_sriov_adapters   Comma separated location code (DRC) of the the remote adapters that is assigned to the hypervisor
remote_sriov_ports      Comma separated ports using which the remote Network virtualized interfaces

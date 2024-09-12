Description:
------------
numactl is a tool to Control NUMA policy for processes or shared memory.

Types of Test:
---------------

This scripts supports Network and FC based numactl operations, along with PCI hot plug between different NUMA nodes.

Inputs Needed To Run Tests:
---------------------------
a> For Network related Tests:
	
	interface		- Interface on which test run
	host_ip                 - Specify host-IP for ip configuration
	netmask                 - Specify netmask for Host ip configuration
	peer_ip			- IP of the Peer interface to be tested
	pci_device              - PCI Device entry got from 'lspci' command
	
b> For FC related Tests:
	disk                    - Disk to run numactl with dd options < Best practice to use additional disk other than OS installed Disk>
	seek                    - DD command seek values,skip BLOCKS obs-sized blocks at start of output	
	count                   - DD count values,to copy a specific amount of data
	bytes			- DD bytes values,to read and write up to BYTES bytes at a time
	input_device            - DD input file,to clean a drive or device before forensically copying data
	pci_device 		- PCI Device entry got from 'lspci' command


Supported NUMA policy settings:
------------------------------
1. Interleave 
2. localalloc
3. Preferred
4. cpunodebind
5. physcpubind
6. PCI numa bind

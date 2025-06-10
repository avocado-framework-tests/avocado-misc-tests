
Overview
----------
The homenode test, tests the new sys_set_mempolicy_home_node introduced by c6018b4b254971863bd0ad36bb5e7d0fa0f0ddb0. This syscall can be used to set a home node for the MPOL_BIND and MPOL_PREFERRED_MANY memory policy. This test tries to allocate memory from the node closest to the node that has been set as the home node.

Parameters
-----------
* h_page: if you want to allocate hugepages set this parameter to True otherwise False

* nr_pages: no. of pages you want to allocate. Make sure you don't try to allocate more pages than what the system can handle.

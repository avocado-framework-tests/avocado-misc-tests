Overview
----------
The hugepage_sanity test, tests the allocation of hugepages on Linux systems. It allocates a specified amount hugepages and then performs write operations to verify that the memory is accessible and functioning correctly. It primarily uses mmap system call and memset function to allocate the hugepages.


Prerequisites
--------------
This test script requires a Linux system with hugepages support enabled. You must have the hugetlbfs supported in order to use hugepages.
In most linux systems have the hugepage support enabled by default.
There are very few Linux systems do not support HugePages by default. For such systems, the Linux kernel can be built using the CONFIG_HUGETLBFS and CONFIG_HUGETLB_PAGE configuration options. CONFIG_HUGETLBFS is located under File Systems and CONFIG_HUGETLB_PAGE is selected when you select CONFIG_HUGETLBFS.

Additionally, you will need Python 3.x and the avocado-framework package installed on the Linux system.


Parameters
--------------
* hpagesize : the size of hugepage in MB you want to run the test on (if system supports more than 1 hugepage size), by default it is the default size supported on the kernel
Example : hpagesize: 2
This runs the test for hugepage size of 2MB.


* num_pages : number of hugepages that the test should allocate, by default it is 1. Make sure the number is such that there is sufficient memory available with the system to function properly. 
Example : num_pages: 2
This allocates only 2 hugepages of the specified size.

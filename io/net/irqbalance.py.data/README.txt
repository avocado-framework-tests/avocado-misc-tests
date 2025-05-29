description:
-------------
This Program to assign and check different smp_affinity_list to IRQ of given IO device, and to capture calltraces, dmesg stacks during the operations with validation of assigned values.
Along with above operations with Program also covers following tests.

    1. Setting up different avialble CPU'S to IO based process by taskset and validating values set.
    2. Making off/on [ offline/online ] of CPU's from min available CPU's to Max available CPU's serial fashion.
    3. Setting different SMT levels and off/on using ppc64_cpu utils.


-----------------------------
Inputs Needed To Run Tests:
-----------------------------

1. For Network based test
-------------------------
peerip ---> IP of the Peer interface to be tested
host_ip  --->   Specify host-IP for ip configuration.
netmask  --->   specify netmask for ip configuration.
interface --->  host interface through which we get host_ip
ping_count ---> specity ping count for " ping flood" test, default set to "10000"

2. For Storage based test:
------------------------
disk ----> Specify the disk path to run the test.
Ex: "/dev/nvme0n1" for NMVe based Disk.


-----------------------
Requirements:
-----------------------
1. Ensure IP configured on Peer machine on given Host IP range, and script will take care configuring IP on Host.
2. install netifaces using pip
3. For storage based test, make sure you are running test other than OS installed disk.
command: pip install netifaces


-----------------------
Supported devices:
-----------------------

1. For network vETH and vNIC devices are supported 
2. For storage supported only for "NVMe" based disk.

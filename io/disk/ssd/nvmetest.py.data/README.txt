NVM-Express user space tooling for Linux, which handles NVMe devices.

This Suite creates namespace, and performs the following tests:
* firmware upgrade
* format namespace
* read
* write
* compare
* flush
* write zeroes
* write uncorrectable
* dsm
* reset
* subsystem reset
* reset_sysfs

This test needs to be run as root.
The suite selects one of the interface on the device and runs tests on it.
If there are no namespaces on the nvme device, the test does not run.
Inputs Needed (in multiplexer file):
------------------------------------
Device      -       NVMe device / interface (Eg: nvme0)

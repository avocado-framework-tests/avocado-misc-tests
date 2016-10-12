NVM-Express user space tooling for Linux, which handles NVMe devices.

This Suite creates namespace, and performs the following tests:
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

This test needs to be run as root.

Inputs Needed (in multiplexer file):
------------------------------------
Devices -       NVMe devices

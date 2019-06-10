NVM-Express user space tooling for Linux, which handles NVMe devices.
The test suite can run for both distro nvme-cli and upstream nvme-cli.

This Suite creates namespace, and performs the following tests:
* firmware upgrade
* create full capacity namespace
* create max namespace
* format namespace
* read
* write
* compare
* flush
* write zeroes
* write uncorrectable
* dsm
* reset
* reset_sysfs
* subsystem reset

This test needs to be run as root.
The suite selects first namespace on the device and runs tests on it.
Inputs Needed (in multiplexer file):
------------------------------------
Device      -       NVMe device / interface (Eg: nvme0)

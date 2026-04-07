"disk": Parameters can be obtained from either the 'nvme list' command output or the 'lsblk' command results, given that the namespace has been created on the NVMe disk.
Example: "/dev/nvmeXnY"

"sed_password": The password must consist of 8 or more alphanumeric characters and will be utilized for the specified tests.
"change_sed_password": The password must consist of 8 or more alphanumeric characters and will be utilized for the specified tests.
Both 'sed_password' and 'change_sed_password' are required fields for executing all tests. The 'sed_password' and 'change_sed_password' values must be distinct.

"device": The value should represent the NVMe controller's name. In the absence of a disk parameter, the script will autonomously generate a disk if not available on the specified subsystem and proceed with the subsequent tests
The device parameter accepts values in the following formats:
1. NQN (Name Space Qualifier Name): nqn.1994-11.com.vendor:nvme:modela:2.5-inch:SERIALNUM
2. Subsystem: nvme-subsysX
3. Controller: nvmeX

These tests cover 
1. SED Initialization
2. SED locking with and without keyring
3. SED unlocking with and without keyring
4. SED Revert
5. SED destructive revert

SED tests has following pre-requisite,
Ensure that the NVMe disk is not initialized for locking prior to initiating the test.

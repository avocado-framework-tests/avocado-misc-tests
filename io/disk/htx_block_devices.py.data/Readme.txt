HTX [Hardware Test eXecutive] is a test tool suite, which is used by various
System p validation labs to verify the System p hardware design. It is used
during processor bring up, hardware system integration, I/O Verification(IOV),
Characterization and Manufacturing. The goal of HTX is to stress test the
system by exercising all hardware components concurrently in order to uncover
any hardware design flaws and hardware hardware or hardware-software 
interaction issues. HTX runs on AIX, Bare Metal Linux(BML) and distribution
Linux. HTX offers a light weight HTX daemon (HTXD) which support command line
interface and menu based user interactive interface.

The test also changes SMT values while HTX is running, based on input from the
user in yaml file.

Inputs:
------
htx_disk: '/dev/sdb /dev/sdc' or if want to pass mpath disk, then it will be /dev/mapper/mpathX
        : for nvme drives, we need to pass namespaces like /dev/nvme0nX
        : Also it can take any of the device name like device by-id, by-path or by uuid
all: True or False (True if all disks in selected mdt needs to be run.
     Overrides disks selected)
time_limit: 1 (In minutes)
mdt_file: Pass the require mdt file, eg: 'mdt.io', mdt.hd
run_type: this is to how do we want to install the htx tool eg: 'git' or 'rpm' based
rpm_link: if you want to install htx through RPM then Pass the rpm link here.

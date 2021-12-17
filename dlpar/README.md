#### This README.md file details on how to configure system to run dlpar cpu/memory tests ####
# Ensure LPARs are installed with dlpar packages for respective Distros(Ex: RHEL and SLES) #
# Path to install dlpar packages:
- https://ausgsa.ibm.com/projects/p/poweryum/yum/OSS/
OR
- https://public.dhe.ibm.com/software/server/POWER/Linux/yum/OSS/
#
# Ensure, lpars are capable of dlpar operationis i.e, CPU, MEMORY Dlpar capable and RMC state is active
# Run below command on HMC and check: 
# lssyscfg -r lpar -m <managed system name> -F lpar_id,name,rmc_state,dlpar_mem_capable,dlpar_proc_capable,dlpar_io_capable
#
# HowTo run tests from avocado:
# avocado run --test-runner runner dlpar_main.py -m <path for lpar.yaml>
#
# This test require 2 LPARs to run dlpar cpu, memory operations namely add/remove/move.
# All the test configuration needs to be filled in test.cfg file which exists under config/test.cfg
#
# Sample test.cfg is provided as below:
#cat config/test.cfg
[log]
file_level = DEBUG
console_level = INFO

[hmc]
name = <fully qualified hmc hostname>
machine = <managed system name> 
partition = <partition name, for hmc it is same as managed system name> 
user = <hmc default user, ex: hscroot>
passwd = <hscroot password>

[linux_primary]
name = <lpar name> 
machine = <managed system name> 
partition = <partition name, should be same as lpar name>
user = <user, ex: root> 
passwd = <root password> 

[linux_secondary]
name = <lpar name> 
machine = <managed system name> 
partition = <partition name, should be same as lpar name>
user = <user, ex: root> 
passwd = <root password> 

[dedicated_cpu]
quantity_to_test = 1
sleep_time = 60
iterations = 1
min_procs = 2
desired_procs = 2
max_procs = 10

[virtual_cpu]
quantity_to_test = 1
sleep_time = 60
iterations = 1

[cpu_unit]
quantity_to_test = 0.5
sleep_time = 60
iterations = 1
min_procs = 2
desired_procs = 2
max_procs = 10
min_proc_units = 2
desired_proc_units = 2
max_proc_units = 10
sharing_mode = cap

[memory]
quantity_to_test = 1024
sleep_time = 40
iterations = 1
mode = add_remove
linux_machine = primary
min_mem = 8192
desired_mem = 8192
max_mem = 204800

#end - config/test.cfg

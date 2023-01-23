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
# avocado run dlpar_main.py -m <path for lpar.yaml> --max-parallel-tasks=1
# This test require 2 LPARs to run dlpar cpu, memory operations namely add/remove/move.
# All the test configuration needs to be filled in lpar.yaml file which exists under dlpar_main.py.data/lpar.yaml
#
# Sample lpar.yaml is provided as below:
#cat dlpar_main.py.data/lpar.yaml
[log]
log_file_level = DEBUG
log_console_level = INFO

[hmc]
hmc_name = <fully qualified hmc hostname>  #The hmc_name is populated in the dlpar_main.py file. Keep the hmc_name blank.
hmc_machine = <managed system name> 
hmc_partition = <partition name, for hmc it is same as managed system name> 
hmc_user = <hmc default user, ex: hscroot>
hmc_passwd = <hscroot password>

[linux_primary]
pri_name = <lpar name> #The pri_name is populated in the dlpar_main.py file. Keep the pri_name blank.
pri_partition = <partition name, should be same as lpar name> #The pri_partition is populated in the dlpar_main.py file. Keep the pri_partition blank.
pri_machine = <managed system name> 


[linux_secondary]
sec_name = <lpar name> 
sec_machine = <managed system name> 
sec_partition = <partition name, should be same as lpar name>
sec_user = <user, ex: root> 
sec_passwd = <root password> 

[dedicated_cpu]
ded_quantity_to_test = 1
ded_sleep_time = 60
ded_iterations = 1
ded_min_procs = 2
ded_desired_procs = 2
ded_max_procs = 10

[virtual_cpu]
vir_quantity_to_test = 1
vir_sleep_time = 60
vir_iterations = 1

[cpu_unit]
cpu_quantity_to_test = 0.5
cpu_sleep_time = 60
cpu_iterations = 1
cpu_min_procs = 2
cpu_desired_procs = 2
cpu_max_procs = 10
cpu_min_proc_units = 2
cpu_desired_proc_units = 2
cpu_max_proc_units = 10
cpu_sharing_mode = cap

[memory]
mem_quantity_to_test = 1024
mem_sleep_time = 40
mem_iterations = 1
mem_mode = add_remove
mem_linux_machine = primary
mem_min_mem = 8192
mem_desired_mem = 8192
mem_max_mem = 204800

#end - dlpar_main.py.data/lpar.yaml -> MUX config data is present.
#The tests.cfg file is created under config/tests.cfg by using dlpar_main.py.data/lpar.yaml data 
#With the mux configuration from dlpar_main.py.data/lpar.yaml, the user can run the dedicated mode or shared mode dlpar operation.

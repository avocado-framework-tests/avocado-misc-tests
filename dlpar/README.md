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
# All the test configuration needs to be filled in dlpar_main.py.data/dlpar.yaml
#
# Sample dlpar.yaml is provided as below:
#cat dlpar_main.py.data/dlpar.yaml

cfg_cpu_per_proc: 8
hmc_manageSystem:   <partition name, It is managed system name>
hmc_user:        <hmc default user, ex: hscroot>
hmc_passwd:      <hscroot password>
target_lpar_hostname: <fully qualified  lpar name(Secondary lpar)>
target_partition: <target partition name(Secondary lpar name)>
target_user: <user, ex: root>
target_passwd: <root password>
ded_quantity_to_test: 2
sleep_time: 60
iterations: 1
vir_quantity_to_test: 1
cpu_quantity_to_test: 0.60
mem_quantity_to_test: 1024
mem_linux_machine: primary

config:
    lpar_mode: !mux
        dedicated:
            lp_mode:

Note: lp_mode -> 1. dedicated
		 2. shared

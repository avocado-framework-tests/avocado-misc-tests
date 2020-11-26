This test Removes and adds back the vfc interfaces for given number of times.
Remove/add operations are done from HMC CLI. test will run for all the vfc 
interfaces mapped to the lpar. it works fine for dual vios setup also.

parameter:
hmc_ip :      HMC IP or host name (9.XX.XXX.XXX)
hmc_username: username of the HMC
hmc_pwd:      password of the HMC
count:        Number of times the vfc interfaces has to remove and add back
skip_drc_name: you can get drc_name from "lsslot -c slot" output. It will skip its corresponding vfc interface from dlpar operation.

This Program loads and unloads the kernel driver modules. For the kernel driver modules that have dependencies, the dependant modules should  be listed in the config file (config). The script takescare of unloading the dependant modules, if any, before unloading the core module. It runs for a total of 100 times as stress.

The script picks up the modules listed in lspci and performs the module unload/load operation.

The test will PASS when at least one of the drivers finishes the whole loop. 

This script should be run as root.

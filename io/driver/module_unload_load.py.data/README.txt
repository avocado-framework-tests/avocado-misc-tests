This Program loads and unloads the kernel driver modules. The script takescare of unloading the dependant modules, if any, before unloading the core module. It runs for a total ofgiven number of iteration.

This script should be run as root.

Inputs
------
ITERATIONS -    No of counts to unload and load the module. Defaults to 1.
MODULE -       Name of modules to unload/load.

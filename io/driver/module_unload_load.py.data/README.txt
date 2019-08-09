This Program loads and unloads the kernel driver modules. The script takes care of unloading the dependant modules, if any, before unloading the core module. It runs for a total of given number of 
iterations.This script should be run as root.
Inputs
------
ITERATIONS -    Number of counts to unload and load the module. Defaults to 1.
MODULE -       Name of modules to unload/load.
only_io -       if user wants to unload and load the specific IO module then this value should be True. False to unload and load all the module available in OS.
fc -            if the module is of FC adapter then this value should be true which is used for flushing the multipath service without which we cannot unload the module. Flase if not FC adapter.

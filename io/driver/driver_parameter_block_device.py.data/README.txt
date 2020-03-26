This Program Verifies the driver parameters and script takescare of unloading the dependant modules, if any.
Each driver being qualified should have an seperate yaml file.

This script should be run as root.

Inputs
------
module: Module name for which the parameter test is being excercised.
disk : Disk name of above module to run dd after the parameter values are changed.
multipath_enabled: Give 'yes' if the module has multipath enabled, if not give 'no'

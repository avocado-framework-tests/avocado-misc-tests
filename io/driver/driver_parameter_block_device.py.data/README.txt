This Program Verifies the driver parameters and script takescare of unloading the dependent modules, if any.
Each driver being qualified should have an separate yaml file.

This script should be run as root.

Inputs
------
module: Module name for which the parameter test is being exercised.
disk : Disk name of above module to run dd after the parameter values are changed.
multipath_enabled: Give 'yes' if the module has multipath enabled, if not give 'no'

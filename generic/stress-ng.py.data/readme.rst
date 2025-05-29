stress-ng test
--------------
Stress-ng exercises various subsystems as well as kernel interfaces. 
It has 175 stressor covering CPU, MEMORY, IO, INTERRUPT, SCHEDULER, VM code paths.

Running stress-ng with root privileges will adjust out of memory settings on Linux systems 
to make the stressors unkillable in low memory situations, so use this judiciously. 

Test can be run to cover all subsystems using class parameter from yaml
class: 'all'

To run for a specific component
class: 'cpu'

To run for specific stressors
stressors: 'mmap numa stack'

To exclude few test:
exclude: 'stack,brk,io'

To run random 60 test:
stressors: 'random'
workers: '60'

For a test run having multiple stressors, Common arguments can be passed using
"common_args" and stressor specific arguments can be passed using "<stressor_name>"
parameter.
for eg. if stressors: "readahead hdd"
then    readahead: '--readahead-bytes 16M'
        hdd: '--hdd-opts dsync'
        common_args: '-k'
Here "common_agrs" is used for both stressors i.e. readahead and hdd
but "readahead" is used for readahead stressor and "hdd" is used for hdd stressor.

This Test removes and adds back a scsi device in all the specified wwids
specified in the 'multiplexer' file.
This test needs to be run as root.

Inputs Needed (in 'multiplexer' file):
--------------------------------------
wwids -   one or more wwids can be given saperated by ','.
          wwids can be fetch from 'multipath -ll' command output

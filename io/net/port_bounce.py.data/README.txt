Port bounce Testcase:

this testcase mainly depends on the setup of fc or fcoe switch to
connect different adapters to different ports in respective switches.
And also this test applicable only for Brocade Switches.

parameters:
type <fc/fcoe> : type of switch fc/fcoe <in small case>
fcoe_fc <yes/no> : If port is an FC port in FCOE switch
switch_name : FC Switch name/ip
userid : FC switch user name to login
password : FC switch password to login
sbt: short bounce time in seconds
lbt: long bounce time in seconds
count : Number of times test to run
port_ids : FC switch port ids where port needs to disable/enable

Port bounce Testcase:

this testcase mainly depends on the setup of fc switch to
connect different adapters to different ports of switches.
And also this test applicable only for Brocade Switches.

parameters:
switch_name : FC Switch name/ip
userid : FC switch user name to login
password : FC switch password to login
sbt: short bounce time in seconds
lbt: long bounce time in seconds
count : Number of times test to run
port_ids : FC switch port ids where port needs to disable/enable

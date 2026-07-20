description:
------------------------
This Program to test switch port enable/disable functionality.
The test is now generic and supports multiple switch vendors through YAML profiles.

-----------------------------
Inputs Needed To Run Tests:
-----------------------------
interface --> host interface name eth3 or mac addr 02:5d:c7:xx:xx:03
peer_ip --> peer interface to perform test.
host_ip --> Specify host-IP for ip configuration.
netmask --> specify netmask for ip configuration.
switch_name --> switch ip address to test.
userid --> switch userid
password --> switch password
port_id --> port id to perform test.
switch_profile --> (optional) switch profile YAML file name (default: juniper_switch)
                   Available profiles
                    - cisco_switch.yaml (Cisco switches)
                    - juniper_switch.yaml (Juniper switches)

-----------------------
Switch Profile Configuration:
-----------------------
Each switch vendor has a YAML profile that defines:
- login_command: Command to execute after SSH login (e.g., "iscli", "enable", "cli")
- commands: Dictionary of commands for different operations
  - enter_config: Enter configuration mode
  - select_interface: Select interface (supports {port_id} placeholder)
  - disable_port: Disable port command
  - enable_port: Enable port command
  - exit_config: Exit configuration mode
- wait_time: Time to wait after port state changes (default: 5 seconds)
- prompt: Expected command prompt

To add support for a new switch vendor:
1. Create a new YAML file in switch_test.py.data/ (e.g., myswitch.yaml)
2. Define the switch_profile with appropriate commands
3. Reference it in switch_test.yaml using switch_profile parameter

-----------------------
Requirements:
-----------------------
1. install paramiko using pip
command: pip install paramiko
2. install pyyaml using pip
command: pip install pyyaml

VNIC VALIDATION FROM VIOS TEST
-------------------------------
The test validates the complete lifecycle of a vNIC (SR-IOV backed Virtual NIC)
on a PowerVM LPAR via HMC:
  1. Add the vNIC via HMC with a primary backing device and, optionally, one or
     more secondary backing devices.
  2. Verify the interface is present and UP on the Host OS.
  3. Login to VIOS and confirm the vNIC server mapping is correctly established.
  4. Delete the vNIC via HMC:
       a. Remove all secondary backing devices first (in reverse order).
       b. Remove the primary vNIC slot.
  5. Re-check VIOS to confirm no stale vNIC server entries remain.

PARAMETERS
----------
hmc_username    HMC login user name 
hmc_pwd         HMC login password
manageSystem    Managed system name as shown on HMC (e.g. Server-9080-M9S-SN12345)
vios_ip         IP address of the VIOS
vios_username   VIOS login user name
vios_pwd        VIOS login password
vios_name       LPAR name of the VIOS as known to HMC (e.g. VIOS1)
slot_num        Unused virtual slot number (3-2999) to assign the vNIC (e.g. 30)
mac_id          MAC address for the vNIC (e.g. 02:03:03:03:03:01)

BACKING DEVICE PARAMETERS
--------------------------
sriov_adapter, sriov_port, bandwidth, and priority each accept a
space-separated list of values — one token per backing device.

  Index 0  =  primary backing device   (required)
  Index 1  =  secondary backing device (optional)
  Index N  =  additional backing devices (optional)

The secondary (and any further) backing devices are added via chhwres -o s
after the primary vNIC slot is created, and are removed in reverse order
before the primary slot is deleted.

sriov_adapter   Physical location code(s) of the SR-IOV backing adapter(s).
                One value means a single (primary) backing device.
                Space-separated values configure multiple backing devices.

                  Single:  "U78DA.ND0.WZS0027-P0-C11"
                  Dual:    "U78DA.ND0.WZS0027-P0-C11 U78DA.ND0.WZS0027-P0-C12"

sriov_port      Port number(s) on the SR-IOV adapter(s), 0-based (default 0).
                One value per adapter token. If fewer values are given than
                adapters, the last value is reused for remaining adapters.

                  Single:  "0"
                  Dual:    "0 1"

bandwidth       Bandwidth allocation percentage(s) entitled to each backing
                device (default 2). Same fill-last rule applies.

                  Single:  "2"
                  Dual:    "2 2"

priority        Failover priority for each backing device, range 1-100.
                Lower number = higher priority. Same fill-last rule applies.
                If omitted, priorities auto-increment from 50
                (primary=50, secondary=51, …).

                  Single:  "50"
                  Dual:    "50 51"

auto_failover   Enable auto-priority failover: 1 to enable, 0 to disable
                (default 1). Applies to the vNIC slot, not per-device.

OPTIONAL PARAMETERS
--------------------
device_ip       IP address to configure on the vNIC interface on Host OS.
netmask         Netmask for device_ip (e.g. 255.255.255.0).
                Required when device_ip is set.
peer_ip         Peer IP to ping after the vNIC interface comes up.

num_iterations  Number of times to repeat the full add/verify/delete cycle
                (default 1). Useful for stress/regression testing.

NOTE: device_ip, netmask, peer_ip, and num_iterations are optional. When
omitted only link-state is verified. All other parameters are mandatory.

EXAMPLES
--------
# Single backing device (primary only)
sriov_adapter: "U78DA.ND0.WZS0027-P0-C11"
sriov_port: "0"
bandwidth: "2"
priority: "50"

# Two backing devices (primary + secondary for failover)
sriov_adapter: "U78DA.ND0.WZS0027-P0-C11 U78DA.ND0.WZS0027-P0-C12"
sriov_port: "0 0"
bandwidth: "2 2"
priority: "50 51"

# Two backing devices, shared port/bandwidth (fill-last behaviour)
sriov_adapter: "U78DA.ND0.WZS0027-P0-C11 U78DA.ND0.WZS0027-P0-C12"
sriov_port: "0"     # port 0 reused for both adapters
bandwidth: "2"      # 2% reused for both adapters
priority: "50 51"

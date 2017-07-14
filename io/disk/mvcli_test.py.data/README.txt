Mvcli Test for OpenPower based Marvell adapter 88SE9230.

This tests the different mvcli tool operations like
info, get, set, smart, locate, register, delete, create, event
on RAID Marvell adapter 88SE9230

Abbreviation:
    VD  - Virtual Disk,   Array  - Disk Array
    PD  - Physical Disk,  BGA - BackGround Activity

And also FW Flash test available for Marvell adapter 88SE9230.

Parameters:
	tool_url: URL location of mvcli tool
        fw_url: URL location of Mvcli FW
        fw_upgrade: <yes|no> Whether to upgrade the firmware or not
        adapter_id: ID of the adapter where the tests will be running
        pd_ids: List of phyisical disk ID's under adapter id adapter_id

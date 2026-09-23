VIOS-Level EEH Error Injection and Recovery Test for Virtual Fibre Channel (ibmvfc)

1. Why eeh_tool_64 with -w 64 is required (not 32-bit eeh_tool):
   The physical FC HBA (e.g. PCIe4 4-Port 32Gb FC Adapter, PCI ID df1000f51410c106)
   is hosted on a Power10 eBMC system (9043-MRX, FW1060.70/NM1060_170).
   Power10 PHBs use 64-bit address domains. The 32-bit eeh_tool passes the
   32-bit truncated BAR address (0x80240000) to RTAS via the 'ioa-bus-error'
   token (-w 32). On Power10, PHYP cannot resolve a 32-bit address to a PHB
   domain and silently returns rc=0/status=0 without arming the freeze latch.
   The 64-bit tool passes the full 64-bit BAR (0x0000000080240000) to the
   'ioa-bus-error-64' RTAS token (-w 64), which is the correct token for
   Power10 PHB injection. PHB_Unit_ID 0x0800000020000030 confirms 64-bit
   domain. eeh_tool_64 is confirmed at /home/padmin/eeh_tool_64.

2. eeh_tool Op 3 Function Codes:
   Only Load/Store address-parity and data-parity errors (functions 0-11)
   are used. These inject a PCI bus freeze that the RTAS firmware classifies
   as recoverable, allowing the OS EEH handler to reset the slot and bring
   the adapter back online. On PCIe adapters they map to TLP ECRC errors.

   Selected injection functions (recoverable):
     EEH_FUNC_MEM_LOAD_DATA = 1  (Load Memory Space Data parity / TLP ECRC)
     EEH_FUNC_IO_LOAD_DATA  = 3  (Load I/O Space Data parity / TLP ECRC)
   Function 1 is preferred because data-path parity errors most reliably
   trigger the freeze+recover cycle across both PCI/PCI-X and PCIe adapter
   generations in PowerVM VIOS environments.

   Excluded non-recoverable / inapplicable functions:
     14 - DMA Read  Master abort  : not applicable on PCIe; may permanently
                                     disable the slot rather than freeze it.
     18 - DMA Write Master abort  : same reason as 14.
     19 - DMA Write Target abort  : explicitly "Not Applicable" on PCIe per
                                     eeh_tool help output.
     15 - DMA Read  Target abort  : Completer Abort on PCIe; firmware
                                     severity classification is
                                     implementation-defined and may be
                                     treated as fatal on some adapters.

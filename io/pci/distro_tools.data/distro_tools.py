pci_device: ""
adapter_type: "net"
Test: !mux
    lsslot:
        tool: lsslot
        test_opt: !mux
            lsslot_pci:
                test_opt: pci
            lsslot_pci_-a:
                test_opt: pci -a
            lsslot_phb:
                test_opt: phb
            lsslot_pci_-o:
                test_opt: pci -o
            lsslot_slot:
                test_opt: slot
    netstat:
        tool: netstat
        test_opt: !mux
            netstat_a:
                test_opt: a
            netstat_l:
                test_opt: l
            netstat_s:
                test_opt: s
            netstat_r:
                test_opt: r
            netstat_i:
                test_opt: i
    lsprop:
        tool: lsprop
        test_opt: !mux
            lsprop_R:
                test_opt: R
            lsprop_r:
                test_opt: r

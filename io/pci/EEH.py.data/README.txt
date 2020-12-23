This script injects EEH errors on the adapter specified in yaml file.
It takes five parameters. One is the value to set max_eeh_frezze bit, and other
is the EEH function number, Partition end point(PE), PCI host bus(PHB),
type of error either 0 or 1, which indicates 32bit or 64bit.

Function can take values from 0-17, each value indicates different type of error.
e.g.,   # 0 : MMIO read
        # 4 : CFG read
        # 6 : MMIO write
        # 10: CFG write

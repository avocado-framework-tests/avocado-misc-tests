This Test unbinds and binds back the driver using pci_adress for givrn number time.
This test needs to be run as root.

Inputs Needed (in multiplexer file):
------------------------------------
pci_devices -      can be fetched from <lspci -nnD>  output. use space( ) for multiple devices "001b:62:00.0 001b:62:00.1"
count -      This is an interger value give for number of time the unbind and bind operation to run

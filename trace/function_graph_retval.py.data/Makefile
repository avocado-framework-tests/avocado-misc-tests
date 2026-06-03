obj-m += test_retval.o

all:
	make -C /lib/modules/$(shell uname -r)/build M=MODULE_DIR modules

clean:
	make -C /lib/modules/$(shell uname -r)/build M=MODULE_DIR clean
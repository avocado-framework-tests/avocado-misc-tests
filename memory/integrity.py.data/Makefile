CFLAGS = -O3 -funroll-loops
LDFLAGS = -lnuma

all : mem_integrity_test

mem_integrity_test : mem_integrity_test.c
	gcc $(CFLAGS) mem_integrity_test.c -o $@ $(LDFLAGS)

clean :
	rm -f mem_integrity_test

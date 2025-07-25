all: libc_livepatch1.so test

libc_livepatch1.so: libc_livepatch1.c
	gcc -fPIC -fpatchable-function-entry=16,14 -shared -o libc_livepatch1.so libc_livepatch1.c

test: test.c
	gcc -o test test.c

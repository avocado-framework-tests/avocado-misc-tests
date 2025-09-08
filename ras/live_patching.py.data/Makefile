all: libc_livepatch1.so test test_long libc_livepatch_2func.so test_2func libc_livepatch_nested.so

libc_livepatch1.so: libc_livepatch1.c
	gcc -fPIC -fpatchable-function-entry=16,14 -shared -o libc_livepatch1.so libc_livepatch1.c

test: test.c
	gcc -o test test.c

test_long: test_long.c
	gcc -o test_long test_long.c

libc_livepatch_2func.so: libc_livepatch_2func.c
	gcc -fPIC -fpatchable-function-entry=16,14 -shared -o libc_livepatch_2func.so libc_livepatch_2func.c

test_2func: test_2func.c
	gcc -o test_2func test_2func.c

libc_livepatch_nested.so: libc_livepatch_nested.c
	gcc -fPIC -fpatchable-function-entry=16,14 -shared -o libc_livepatch_nested.so libc_livepatch_nested.c


all : mem_integrity_test

mem_integrity_test : mem_integrity_test.c
	gcc mem_integrity_test.c -o $@ -lnuma -w
clean :
	rm mem_integrity_test 

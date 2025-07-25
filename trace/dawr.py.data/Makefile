all : dawr_v1  dawr_v2 dawr_v3 boundary_check
dawr_v1 : dawr_v1.c
	gcc -g -o dawr_v1 dawr_v1.c
dawr_v2 : dawr_v2.c
	gcc -g -o dawr_v2 dawr_v2.c
dawr_v3 : dawr_v3.c
	gcc -g -o dawr_v3 dawr_v3.c
boundary_check : boundary_check.c
	gcc -g -o boundary_check boundary_check.c
clean : 
	rm dawr_v1 dawr_v2 dawr_v3 boundary_check

all : dawr_v1  dawr_v2 dawr_v3 boundary_check dawr_local dawr_pointer dawr_struct dawr_array
dawr_v1 : dawr_v1.c
	gcc -g -o dawr_v1 dawr_v1.c
dawr_v2 : dawr_v2.c
	gcc -g -o dawr_v2 dawr_v2.c
dawr_v3 : dawr_v3.c
	gcc -g -o dawr_v3 dawr_v3.c
boundary_check : boundary_check.c
	gcc -g -o boundary_check boundary_check.c
dawr_local : dawr_local.c
	gcc -g -o dawr_local dawr_local.c
dawr_pointer : dawr_pointer.c
	gcc -g -o dawr_pointer dawr_pointer.c
dawr_struct : dawr_struct.c
	gcc -g -o dawr_struct dawr_struct.c
dawr_array : dawr_array.c
	gcc -g -o dawr_array dawr_array.c
clean : 
	rm dawr_v1 dawr_v2 dawr_v3 boundary_check dawr_local dawr_pointer dawr_struct dawr_array

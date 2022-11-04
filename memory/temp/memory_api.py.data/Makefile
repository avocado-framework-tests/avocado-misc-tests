all : memory_api mremap

memory_api : memory_api.c
	gcc memory_api.c -o $@

mremap : mremap.c
	gcc mremap.c -o $@

clean :
	rm memory_api mremap

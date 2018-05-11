#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <stdlib.h>
#include <unistd.h>
#include <getopt.h>
#include <linux/mman.h>

void *mmap_memory(unsigned long size)
{
        void *mmap_pointer;
        mmap_pointer = mmap(NULL, size, PROT_READ | PROT_WRITE,
                                MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if ((!mmap_pointer) && (mmap_pointer != MAP_FAILED)) {
                perror("mmap");
                exit(-1);
        }
        return mmap_pointer;
}

void set_mergeable(void *addr, unsigned long size)
{
	if (madvise(addr, size, MADV_MERGEABLE) == -1){
		perror("madvise mergeable\n");
	}
}

void clear_mergeable(void *addr, unsigned long size)
{
	if (madvise(addr, size, MADV_UNMERGEABLE) == -1){
		perror("madvise unmergeable\n");
	}
}
	

int main(int argc, char *argv[])
{
	int c;
	int touch = 0;
	int nr_pages = 0;
	int hardoffline = 0;
	int softoffline = 0;
	unsigned long size;
	unsigned long pagesize = getpagesize();
	void *map1;
	void *map2;
	if (argc < 2){
		printf("Usage : <./poison> -n <nr_pages> -t -h[hardoffline or -s for softofflining]\n");
		exit(-1);
	}
	while((c = getopt(argc, argv,"n:t:hs")) != -1){
        	switch(c) {
		case 'n' :
                	nr_pages = atoi(optarg);
			break;
		case 't' :
			touch = 1;
			break;
		case 'h' :
			hardoffline = 1;
			break;
		case 's' :
			softoffline = 1;
			break;
        	}
	}
	size = nr_pages * pagesize;
	map1 = mmap_memory(size);
	printf("Mapped at %p\n", map1);
	map2 = mmap_memory(size);
	printf("Mapped at %p\n", map2);
	printf("Set MADV_MERGEABLE flag for the mapped memory\n");
	set_mergeable(map1, size);
	set_mergeable(map2, size);
	memset(map1, 'x', size);
	memset(map2, 'x', size);
	printf("Poison the Pages\n");
	if(hardoffline || softoffline){
		if((madvise(map1, size, hardoffline ? MADV_HWPOISON : MADV_SOFT_OFFLINE )) == -1){
		perror("madvise poison\n");
		exit(-1);
		}
	}
	if(touch){
		printf("Write into Affected Pages\n");
		memset(map1, 'x', size);
	}
	printf("Clear MADV_MERGEABLE flag for the mapped memory\n");
	clear_mergeable(map1, size);
	clear_mergeable(map2, size);
	printf("Test passed !!!\n");
	return 0;
}

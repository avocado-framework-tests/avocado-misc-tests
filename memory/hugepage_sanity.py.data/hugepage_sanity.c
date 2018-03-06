/*
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See LICENSE for more details.
 * Copyright: 2017 IBM
 * Author: Ranjit Manomohan <ranjitm@google.com>
 * Modified by: Harish<harish@linux.vnet.ibm.com>
 */

#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>

#define MAP_HUGE_2MB    (21 << MAP_HUGE_SHIFT)
#define MAP_HUGE_16MB    (24 << MAP_HUGE_SHIFT)
#define MAP_HUGE_1GB    (30 << MAP_HUGE_SHIFT)
#define MAP_HUGE_SHIFT  26
#define PROT ( PROT_READ | PROT_WRITE )

int FLAGS = (MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB);
unsigned long MEM_SIZE = 1048576, TMP_SIZE; 

long local_read_meminfo(const char *tag)
{
        unsigned long val;
        char buff[256];
        FILE *meminfo = fopen("/proc/meminfo", "r");
        if(meminfo == NULL){
                exit(-1);
        }
        while(fgets(buff, sizeof(buff), meminfo)){
                int memsize;
                if(sscanf(buff, tag, &memsize) == 1){
                        val = memsize;
                }
        }
        if(fclose(meminfo) != 0){
                exit(-1);
        }
        return val;

}

void setup_hugetlb_pool(unsigned long size, long count)
{
        FILE *fd;
        unsigned long poolsize;
	char buf[100];
        snprintf(buf, sizeof buf,
                "/sys/kernel/mm/hugepages/hugepages-%lukB/nr_hugepages",
                size);
	if( access( buf, F_OK ) == -1 ) {
		printf("Given hugepage size is not supported in kernel\n");
                exit(-1);
	}
        fd = fopen(buf, "w");
        if (!fd){
                printf("Cannot open nr_hugepages for writing\n");
		exit(-1);
	}
        fprintf(fd, "%lu", count);
        fclose(fd);

        /* Wait till pages are allocated*/
        sleep(5);
        /* Confirm the resize worked */
	fd = fopen(buf, "r");
	if (!fd){
                printf("Cannot open nr_hugepages for reading\n");
		exit(-1);
	}
        fscanf(fd, "%lu", &poolsize);
        if (poolsize != count){
                printf("Failed to resize pool to %lu pages. Got %lu instead\n",
                        count, poolsize);
		exit(-1);
	}
}

void check_alloc_free_huge_page(unsigned long size, long pages)
{
	printf("Setting hugepages to %d\n", pages);
	setup_hugetlb_pool(size * 1024, pages);
}

unsigned long get_hugepage_bytes()
{
    	unsigned long pagesize = local_read_meminfo("Hugepagesize: %lu kB");
    	return pagesize * 1024;
}

int alloc_hugepage(unsigned long size, unsigned long no_page){
        char *addr;
        unsigned long total = size * no_page;
        TMP_SIZE = MEM_SIZE * total;

        if( size == 1024 )
		FLAGS |= MAP_HUGE_1GB;
        else if ( size == 2 )
		FLAGS |= MAP_HUGE_2MB;
	else
		FLAGS |= MAP_HUGE_16MB;

        addr = mmap(NULL, TMP_SIZE, PROT, FLAGS, -1, 0);
        if (addr == MAP_FAILED)
        {
                printf("Allocation of %d MB failed using HUGEPAGE size\n", size);
                return -1;
        }
        printf("Allocation successful for %d MB of %luMB Hugepage size\n", total, size);

        if(memset(addr, 'x', TMP_SIZE) == NULL){
                printf("Memset Failed - > %d MB not supported\n", total);
                return -1;
        }

        printf("Memset successful for %d MB Hugepage\n", total);
        /* Un-map entire region, must be hugepage-aligned*/
        if(munmap(addr, TMP_SIZE)){
		printf("Unmap failed\n");
		return -1;
        }
        return 0;
}

int
main(int argc, char *argv[])
{
        int flag = 0;
        unsigned long no_page, size, val;
        if (argc > 3){
                printf("Usage <execname> [hugepage-size](MB)  [no-of-hugepages]\n");
                exit(-1);
        }
        if (argc == 1){
                printf("Using default hugepagesize and 1 hugepage\n");
		size = get_hugepage_bytes() / MEM_SIZE;
		no_page = 1;
	}
        if (argc == 2){
		size = atol(argv[1]);
                no_page = 1;
	}
        if (argc == 3) {
		size = atol(argv[1]);
        	no_page = atol(argv[2]);
    	}
	printf("PAGESIZE: %lu MB\tNumber of pages: %lu\n", size, no_page);
    	check_alloc_free_huge_page(size, no_page);
    	flag = alloc_hugepage(size, no_page);

        if(!flag)
		printf("Test Passed!!\n");
        else
		printf("Test Failed!!\n");
        return 0;

}

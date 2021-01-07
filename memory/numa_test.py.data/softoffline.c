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
 * Copyright: 2020 IBM
 * Author: Aneesh Kumar K.V <anesh.kumar@linux.vnet.ibm.com>
 * Author: Harish <harish@linux.vnet.ibm.com>
 */


#include <stdio.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>
#include <asm/unistd.h>
#include <numa.h>
#include <numaif.h>
#include <string.h>
#include <stdlib.h>
#include <getopt.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <linux/mman.h>
#include <hugetlbfs.h>


#define errmsg(x, ...) fprintf(stderr, x, ##__VA_ARGS__),exit(1)

extern int get_pfn(void *addr, unsigned long *);
int main(int argc, char *argv[])
{
	char *p;
	int c, i, nr_pages = 3;
	int page_size = getpagesize();
	int mapflag = MAP_ANONYMOUS;
	int protflag = PROT_READ|PROT_WRITE;
	unsigned long *old_pfn, *new_pfn;

	while ((c = getopt(argc, argv, "m:n:hH")) != -1) {
		switch(c) {
		case 'm':
			if (!strcmp(optarg, "private"))
				mapflag |= MAP_PRIVATE;
			else if (!strcmp(optarg, "shared"))
				mapflag |= MAP_SHARED;
			else
				errmsg("invalid optarg for -m\n");
			break;
		case 'n':
			nr_pages = strtoul(optarg, NULL, 10);
			break;
		case 'h':
			mapflag |= MAP_HUGETLB;
			page_size = gethugepagesize();
			break;
		case 'H':
			errmsg("%s -m [private|shared] -h  -n <number of pages>\n", argv[0]);

		default:
			errmsg("invalid option\n");
			break;
		}
	}
	old_pfn = (unsigned long*) malloc(nr_pages * sizeof(unsigned long));
	new_pfn = (unsigned long*) malloc(nr_pages * sizeof(unsigned long));

	if (!(mapflag & (MAP_SHARED | MAP_PRIVATE)))
		errmsg("Specify shared or private using -m flag\n");

	p = mmap(NULL, nr_pages * page_size, protflag, mapflag, -1, 0);
	if (p == MAP_FAILED)
		errmsg("Failed mmap\n");

	/* fault in */
	memset(p, 'a', nr_pages * page_size);
	for (i = 0; i < nr_pages; i++){
		get_pfn(p + (i * page_size), &old_pfn[i]);
		printf("pfn before soft offline 0x%lx\n", old_pfn[i]);
	}

	if (madvise(p, nr_pages * page_size, MADV_SOFT_OFFLINE) == -1)
		errmsg("madvise failed\n");

	memset(p, 'a', nr_pages * page_size);
	for (i = 0; i < nr_pages; i++){
		get_pfn(p + (i * page_size), &new_pfn[i]);
		printf("pfn after soft offline 0x%lx\n", new_pfn[i]);
	}

	for (i = 0; i < nr_pages; i++){
		if (!old_pfn[i] || !new_pfn[i])
			continue;
		if (old_pfn[i] == new_pfn[i]){
			printf("pfn matches, softoffline failed at %d\n", i);
			return -1;
		}
	}
	printf("Softoffline succeeded!\n");
	return 0;
}

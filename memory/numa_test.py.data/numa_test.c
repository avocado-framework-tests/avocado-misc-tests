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
 * Copyright: 2018 IBM
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
#include <hugetlbfs.h>

#define errmsg(x, ...) fprintf(stderr, x, ##__VA_ARGS__),exit(255)
#define ARRAY_SIZE(arr) (sizeof(arr) / sizeof((arr)[0]))
#define PROTFLAG PROT_READ|PROT_WRITE

extern int *get_numa_nodes_to_use(int max_node, unsigned long size);
extern unsigned long get_pfn(void *addr);
unsigned long i;

struct testcase {
	const char *msg;
	int id;
};

static struct testcase testcases[] = {
	{
		.msg = "numa_move_pages",
		.id = 1,
	},
	{
		.msg = "mbind",
		.id = 2,
	},
};

int test_func(unsigned long nr_nodes, int mapflag, unsigned long nr_pages, unsigned long page_size, int id, const char *msg)
{
	char *p;
	int *node_list, *status, *nodes;
	int ret, same_pfn = 0;
	void **addrs;
	struct bitmask *all_nodes, *old_nodes, *new_nodes;
	unsigned long *old_pfn, memory_to_use;

	printf("\n \n Testcase %d: %s\n\n", id, msg);
	old_pfn = (unsigned long *)malloc(sizeof(unsigned long) * nr_pages);
	memory_to_use = nr_pages * page_size;

	node_list = (int *)malloc(sizeof(int) * 2);
	node_list = get_numa_nodes_to_use(nr_nodes, memory_to_use);

	all_nodes = numa_bitmask_alloc(nr_nodes);
	numa_bitmask_setbit(all_nodes, node_list[0]);
	numa_bitmask_setbit(all_nodes, node_list[1]);

	old_nodes = numa_bitmask_alloc(nr_nodes);
	numa_bitmask_setbit(old_nodes, node_list[0]);
	numa_sched_setaffinity(0, old_nodes);

	if ( id == 2 ){
		new_nodes = numa_bitmask_alloc(nr_nodes);
		numa_bitmask_setbit(new_nodes, node_list[1]);
	}
	else{
		addrs  = malloc(sizeof(char *) * nr_pages + 1);
		status = malloc(sizeof(char *) * nr_pages + 1);
		nodes  = malloc(sizeof(char *) * nr_pages + 1);
	}

	printf("Pages: %lu, Size: %lu\n", nr_pages, page_size);

	p = mmap(NULL, memory_to_use, PROTFLAG, mapflag, -1, 0);
	if (p == MAP_FAILED){
		errmsg("Failed mmap\n");
		return 1;
	}
	/* fault in */
	memset(p, 'a', memory_to_use);
	sleep(3);
	numa_sched_setaffinity(0, all_nodes);
	for (i = 0; i < nr_pages; i++) {
		if (id == 1)
		{
			addrs[i] = p + i * page_size;
			nodes[i] = node_list[1];
			status[i] = 0;
		}
		old_pfn[i] = get_pfn(p + i* page_size);
	}
	printf("Executing %s\n", msg);
	if (id == 1)
		ret = numa_move_pages(0, nr_pages, addrs, nodes, status, MPOL_MF_MOVE_ALL);
	else
		ret = mbind(p, memory_to_use, MPOL_BIND, new_nodes->maskp,
			new_nodes->size + 1, MPOL_MF_MOVE|MPOL_MF_STRICT);
	sleep(3);

	if (ret == -1)
	{
		errmsg("Failed %s \n", msg);
		return 1;
	}
	memset(p, 'a', memory_to_use);

	printf("Checking PFN's\n");

	for (i = 0; i < nr_pages; i++) {
		if(old_pfn[i]!=0){
			if(old_pfn[i] == get_pfn(p + i* page_size)){
				same_pfn++;
			}
		}
	}
	if(same_pfn){
		errmsg("Number of pages with same PFN: %d\n", same_pfn);
		return 1;
	}
	sleep(2);

	munmap(p, memory_to_use);
	return 0;
}


int main(int argc, char *argv[])
{
	int c, i, mapflag = MAP_ANONYMOUS;
	unsigned long nr_nodes = numa_max_node() + 1, page_size = getpagesize(), nr_pages;

	while ((c = getopt(argc, argv, "vm:n:Hh")) != -1) {
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
			mapflag = mapflag | MAP_ANONYMOUS | MAP_HUGETLB;
			page_size = gethugepagesize();
			break;
		case 'H':
			errmsg("%s -m [private|shared] -n <number of pages> [-h]\n", argv[0]);
			break;
		default:
			errmsg("invalid option\n");
			break;
		}
	}

	if (nr_nodes < 2)
		errmsg("A minimum of 2 nodes is required for this test.\n");

	if (mapflag & MAP_HUGETLB)
		printf("Using Hugepages\n");

	if (!(mapflag & (MAP_SHARED | MAP_PRIVATE)))
		errmsg("Specify shared or private using -m flag\n");

	for (i = 0; i < ARRAY_SIZE(testcases); i++) {
		struct testcase *t = testcases + i;
		if (test_func(nr_nodes, mapflag, nr_pages, page_size, t->id, t->msg))
		{
			printf("Test %s Failed", t->msg);
			exit(1);
		}
		printf("Testcase %d: %s Passed\n", t->id, t->msg);
	}
	return 0;
}

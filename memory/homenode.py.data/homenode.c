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
 * Copyright: 2023 IBM
 * Author: Aneesh Kumar K.V <aneesh.kumar@linux.ibm.com> and Vaibhav Jain <vaibhav@linux.ibm.com>
 * Modified-By: Geetika Moolchandani <geetika@linux.ibm.com>
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
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <stdbool.h>
#include <stdint.h>

#define errmsg(x, ...) fprintf(stderr, x, ##__VA_ARGS__),exit(1)
#define __NR_HOME_NODE 450

#ifndef MPOL_PREFERRED_MANY
#define MPOL_PREFERRED_MANY	5
#endif

int sys_set_mempolicy_home_node(unsigned long start, unsigned long len,
				unsigned long home_node, unsigned long flags)
{

	int ret = syscall(__NR_HOME_NODE, start, len, home_node, 0);
	return ret >= 0 ? ret : -errno;

}



int main(int argc, char *argv[])
{

	char *p;
	int ret, c;
	int i, nr_pages = 3;
	int page_size = getpagesize();
	int mapflag = MAP_ANONYMOUS;
	int polflag = MPOL_BIND;
	int protflag = PROT_READ|PROT_WRITE;
 	unsigned long nr_nodes = numa_max_node() + 1;
	struct bitmask *all_nodes, *old_nodes, *new_nodes;
	unsigned long src_node, dest_node;

 	long freemem_before[4] = {0}, freemem_after[4] = {0};

	int home_node;

	while ((c = getopt(argc, argv, "m:f:n:hH")) != -1) {

		switch(c) {

		case 'm':
			if (!strcmp(optarg, "private"))
				mapflag |= MAP_PRIVATE;
			else if (!strcmp(optarg, "shared"))
				mapflag |= MAP_SHARED;
			else
				errmsg("invalid optarg for -m\n");
			break;

		case 'f':
			if (!strcmp(optarg, "MPOL_BIND"))
				polflag = MPOL_BIND;
			else if (!strcmp(optarg, "MPOL_PREFERRED_MANY"))
				polflag = MPOL_PREFERRED_MANY;
			else
				errmsg("invalid optarg for -f\n");
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

	if (nr_nodes < 2)
		errmsg("A minimum of 2 nodes is required for this test.\n");


	if (!(mapflag & (MAP_SHARED | MAP_PRIVATE)))
		errmsg("Specify shared or private using -m flag\n");


	all_nodes = numa_bitmask_alloc(nr_nodes);
	old_nodes = numa_bitmask_alloc(nr_nodes);
	new_nodes = numa_bitmask_alloc(nr_nodes);

	src_node = 0;
	dest_node = 1;
	home_node = 3;

	printf("nr pages=%d page_size=%d\n", nr_pages, page_size);
	printf("src node = %ld and dest node = %ld home node=%d\n", src_node, dest_node, home_node);


	numa_bitmask_setbit(all_nodes, src_node);

  	numa_bitmask_setbit(all_nodes, numa_max_node());

  	numa_bitmask_setbit(old_nodes, src_node);

  	numa_bitmask_setbit(new_nodes, dest_node);

	numa_bitmask_setbit(new_nodes, dest_node + 1);

	numa_sched_setaffinity(0, old_nodes);

	p = mmap(NULL, nr_pages * page_size, protflag, mapflag, -1, 0);

	if (p == MAP_FAILED)
		errmsg("Failed mmap\n");
	ret = mbind(p, nr_pages * page_size, polflag, new_nodes->maskp,
		    new_nodes->size + 1, MPOL_MF_MOVE|MPOL_MF_STRICT);

	printf("dest node %ld->%ld\n", dest_node, home_node);
	ret = sys_set_mempolicy_home_node((unsigned long)p + 2*page_size , nr_pages * page_size,
					  home_node, 0);

	if (ret == -1)
		errmsg("Failed home node");


	for(int nid=0;nid <4; ++nid)
	  numa_node_size(nid, &freemem_before[nid]);

	/* page fault in */
	memset(p, 'a', nr_pages * page_size);


	for(int nid=0;nid <4; ++nid) {
	  numa_node_size(nid, &freemem_after[nid]);
	  printf("Free Mem(%d)\tbefore(%ld)\tafter(%ld)\tDelta(%ld pages)\n", nid,freemem_before[nid],
		 freemem_after[nid],
		 (freemem_before[nid]-freemem_after[nid])>>16);
	}

}

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
#include <hugetlbfs.h>
#include <time.h>

#define errmsg(x, ...) fprintf(stderr, x, ##__VA_ARGS__),exit(1)

extern int is_thp(unsigned long pfn);
extern unsigned long get_pfn(void *addr);
extern unsigned long get_first_mem_node(void);
extern unsigned long get_next_mem_node(unsigned long node);

int verbose;
void **addrs;
int nr_pages;    /* number of pages in page size */
int page_size;
int hpage_size;
unsigned long dest_node;
int *status, *nodes;

double test_migration(void *p, char *msg)
{
	int non_thp = 0;
	int i, thp, ret;
	unsigned long pfn;
	double time;
	struct timespec ts_start, ts_end;

	if (verbose)
		fprintf(stderr, "%s\n", msg);
	for (i = 0; i < nr_pages; i++) {
		addrs[i] = p + (i * page_size);
		nodes[i] = dest_node;
		status[i] = 0;
		pfn =  get_pfn(p + (i* page_size));
		if (pfn) {
			if (!non_thp && !is_thp(pfn))
				non_thp = 1;
			if (verbose)
				fprintf(stderr, "pfn before move_pages 0x%lx is_thp %d\n",
					pfn, is_thp(pfn));
		}
	}

	clock_gettime(CLOCK_MONOTONIC, &ts_start);
	ret = numa_move_pages(0, nr_pages, addrs, nodes, status, MPOL_MF_MOVE_ALL);
	if (ret == -1)
		errmsg("Failed move_pages\n");
	clock_gettime(CLOCK_MONOTONIC, &ts_end);

	for (i = 0; i < nr_pages; i++) {
		pfn = get_pfn(p + (i* page_size));
		if (pfn && verbose)
			fprintf(stderr, "pfn after move_pages 0x%lx is_thp %d\n", pfn, is_thp(pfn));
	}
	time = ts_end.tv_sec - ts_start.tv_sec + (ts_end.tv_nsec - ts_start.tv_nsec) / 1e9;
	printf("%s time(seconds) (Non THP = %d) = %.6f\n", msg, non_thp, time);
	return time;
}

int main(int argc, char *argv[])
{
	int c;
	void *hp, *p;
	int mapflag = MAP_ANONYMOUS | MAP_PRIVATE;
	int protflag = PROT_READ|PROT_WRITE;
	unsigned long nr_nodes = numa_max_node() + 1;
	struct bitmask *all_nodes, *old_nodes;
        unsigned long src_node;
        double thp_time, bp_time;

	page_size = getpagesize();
	hpage_size = gethugepagesize();

        while ((c = getopt(argc, argv, "n:vh")) != -1) {
		switch(c) {
		case 'n':
			nr_pages = strtoul(optarg, NULL, 10);
			/* Now update nr_pages using system page size */
			nr_pages = nr_pages * hpage_size/page_size;
			break;
		case 'h':
			errmsg("%s -n <number of pages>\n", argv[0]);
			break;
		case 'v':
			verbose = 1;
			break;
		default:
			errmsg("invalid option\n");
			break;
		}
	}

	if (nr_nodes < 2)
		errmsg("A minimum of 2 nodes is required for this test.\n");


	all_nodes = numa_bitmask_alloc(nr_nodes);
	old_nodes = numa_bitmask_alloc(nr_nodes);
        src_node = get_first_mem_node();
        dest_node = get_next_mem_node(src_node);
	printf("src node = %ld and dest node = %ld\n", src_node, dest_node);

        numa_bitmask_setbit(all_nodes, src_node);
	numa_bitmask_setbit(all_nodes, dest_node);
	numa_bitmask_setbit(old_nodes, src_node);

	numa_sched_setaffinity(0, old_nodes);
	addrs  = malloc(sizeof(char *) * nr_pages + 1);
	status = malloc(sizeof(char *) * nr_pages + 1);
	nodes  = malloc(sizeof(char *) * nr_pages + 1);

	p = aligned_alloc(page_size, nr_pages *page_size);
	if (p == NULL)
		errmsg("Failed mmap\n");

	hp = aligned_alloc(hpage_size, nr_pages *page_size);
	if (hp == NULL)
		errmsg("Failed mmap\n");

	madvise(hp, nr_pages * page_size, MADV_HUGEPAGE);
	madvise(p, nr_pages * page_size, MADV_NOHUGEPAGE);

	memset(p, 'a', nr_pages * page_size);
	memset(hp, 'a', nr_pages * page_size);

	numa_sched_setaffinity(0, all_nodes);

	thp_time = test_migration(hp, "THP migration");
	bp_time = test_migration(p, "Base migration");

	if (bp_time >= thp_time)
		errmsg("Base page migration took more time\n");
	return 0;
}

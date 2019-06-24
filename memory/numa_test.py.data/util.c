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
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <numa.h>

#define PMAP_ENTRY_SIZE		sizeof(unsigned long)
#define PM_PFRAME_MASK		0x007FFFFFFFFFFFFFUL
#define PM_PRESENT		0x8000000000000000UL

unsigned long get_pfn(unsigned long addr)
{
	int fd;
	unsigned long pmap_entry;
	unsigned long pmap_offset;
	int page_size = getpagesize();

	fd = open("/proc/self/pagemap", O_RDONLY);
	if (fd == -1)
		return 0;

	pmap_offset = (addr / page_size)*PMAP_ENTRY_SIZE;

	if (lseek(fd, pmap_offset, SEEK_SET) == -1) {
		printf("%s Failed to lseek\n", __func__);
		goto err_out;
	}

	if (read(fd, &pmap_entry, PMAP_ENTRY_SIZE) == -1) {
		printf("%s Failed to read\n", __func__);
		goto err_out;
	}

	if (!(pmap_entry & PM_PRESENT)) {
		goto err_out;
	}

	close(fd);
	return pmap_entry & PM_PFRAME_MASK;

err_out:
	close(fd);
	return 0;
}

int *get_numa_nodes_to_use(int max_node, unsigned long memory_to_use)
{
	unsigned long free_node_sizes;
	long node_size;
	int node_iterator, *nodes_to_use, got_nodes = 0;

	nodes_to_use = (int *)malloc(sizeof(int) * 2);
	/* Get 2 Nodes which contains system memory*/
	for(node_iterator=0; node_iterator < max_node; node_iterator++){
		node_size = numa_node_size(node_iterator,&free_node_sizes);
		if (node_size > 0 && free_node_sizes > memory_to_use) {
			nodes_to_use[got_nodes++] = node_iterator;
			if (got_nodes == 2)
				break;
		}
	}

	/* Verify if we got 2 nodes to use */
	if (got_nodes == 2){
		printf("Nodes used in test %d %d \n", nodes_to_use[0], nodes_to_use[1]);
	} else {
		printf("memory is not found in 2 nodes\n");
		exit(255);
	}
	return nodes_to_use;
}

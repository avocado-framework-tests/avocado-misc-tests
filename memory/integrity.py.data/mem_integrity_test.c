/*
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *
 * See LICENSE for more details.
 *
 * Copyright: 2019 IBM
 * Author: Santhosh G <santhog4@linux.vnet.ibm.com>
 */

#include <stdio.h>
#include <sys/mman.h>
#include <linux/mman.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <numa.h>
#include <numaif.h>

#define PMAP_FILE	"/proc/self/pagemap"
#define PMAP_SIZE	8

#define PATTERN		0xffffffff


unsigned long total_mem = 0;
int max_node;
int nodes_to_use[2];

/* Determines the Free memory in the system */ 
void get_total_mem_bytes()
{
	unsigned long vm_size = 0;
        char buff[256];
	FILE *meminfo = fopen("/proc/meminfo", "r");

	if(meminfo == NULL){
		printf("No Meminfo Information\n");
		exit(-1);
	}
	while(fgets(buff, sizeof(buff), meminfo)){
		unsigned long memsize;
		if(sscanf(buff, "MemFree: %lu kB", &memsize) == 1){
			total_mem = memsize * 1024.0;
		}
	}
        if(fclose(meminfo) != 0){
		exit(-1);
	}
}

/* Writes pattern at given address for given size*/ 
void write_memory(void *addr, int pattern, unsigned long size)
{
	unsigned long iterator;
	int *temp = (int*)addr;

	for(iterator=0; iterator < (size/(sizeof(int))); iterator++) {
		*temp = pattern;
		temp++;
	}
}

/* Read and verify the pattern from given address for given size */
void read_memory(void *addr, int pattern, unsigned long size)
{
	unsigned long iterator;
	unsigned long read = 0;
	int *temp = (int*)addr;

	for(iterator=0; iterator < (size/(sizeof(int))); iterator++){
		if (*temp != pattern) {
			printf("Iterator %lu", iterator);
			printf("Correctness failed at loop read\n"
                               "PATTERN MISMATCH OCCURED \n");
			exit(-1);
		}
		read++;
		temp++;
	}
}

/* Does mmap for given size and returns address*/
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

void lock_mem(void *mmap_pointer, unsigned long size)
{
	int lock;
	lock = mlock(mmap_pointer, size);
	if (lock != 0) {
		perror("lock");
		exit(-1);
	}
}

void unlock_mem(void *mmap_pointer, unsigned long memory)
{
	int unlock;

	unlock = munlock(mmap_pointer, memory);
	if (unlock != 0) {
		perror("munlock");
		exit(-1);
	}
}

/* Verify Whether the page actually faulted*/
void verify_page_fault(void *addr, unsigned long memory)
{
	unsigned long psize, offset, npages, pfn, iterator;
	int fd;
	void *tmp;

	psize = getpagesize();
	npages = memory / psize;
	fd = open(PMAP_FILE, O_RDONLY);
	if (fd == -1) {
		perror("open() failed");
		exit(-1);
	}
	for (iterator=0; iterator < npages; iterator++) {
		tmp = addr + iterator * psize;
		offset = ((unsigned long) tmp / psize) * PMAP_SIZE;
		if (lseek(fd, offset, SEEK_SET) == -1) {
			perror("lseek() failed");
			exit(-1);
		}
		if (read(fd, &pfn, sizeof(pfn)) == -1) {
			perror("read() failed");
			exit(-1);
		}
		if (!((pfn >> 63) & (1UL))) {
			printf("Pfn bit is not set !! So Some pages are not faulted\n");
			exit(-1);
		}
	}	
}	 

/* Sets the nodes to be used in test which contains atleast 10% of total memory*/
void get_numa_nodes_to_use(unsigned long memory_to_use)
{
	unsigned long free_node_sizes;
	long node_size;
	int node_iterator;
	int got_nodes = 0;

	/* Get 2 Nodes which contains 10% of total system memory*/
	for(node_iterator=0; node_iterator <= max_node; node_iterator++){
		node_size = numa_node_size(node_iterator,&free_node_sizes);
		if (node_size > 0){
			if ((free_node_sizes > memory_to_use) && (got_nodes <= 1)){
				nodes_to_use[got_nodes++] = node_iterator;
			}
		}
	}

	/* Verify if we got 2 nodes to use */
	if (got_nodes == 2){
		printf("Nodes used in test %d %d \n", nodes_to_use[0], nodes_to_use[1]);
	}else {
		printf("10 percent of total memory is not found in 2 nodes\n");
		exit(255);
	}
}

/* Returns number of pages used in numanode 'node' searched by a addr*/
unsigned long get_npages_from_numa_maps(void *addr, int node)
{
	int pid;
	char numa_maps_file[32];
	const char line[1024];
	char addr_in_string[64];
	const char node_info[16];
	char *ptr_addr_in_string;
	char *string_ptr;
	char *temp_str_ptr;
	unsigned long npages = 0;

	ptr_addr_in_string = addr_in_string;
	pid = getpid();
	snprintf(addr_in_string, sizeof(addr_in_string), "%p", addr);
	snprintf(numa_maps_file, sizeof(numa_maps_file), "/proc/%d/numa_maps", pid);
	snprintf(node_info, sizeof(node_info), "N%d=", node);

	/* Incremented 2 bytes to avoid 0x */
	ptr_addr_in_string += 2;
	FILE *numa_maps = fopen(numa_maps_file,"r");
	if (numa_maps ==NULL){
		exit(-1);
	}
	/* Parse each line from numa maps to get the no of pages used by the addr 
	   in the corresponding node */ 
	while(fgets(line, sizeof(line), numa_maps)){
		if (strstr(line, ptr_addr_in_string) != NULL){
			string_ptr = strtok(line, " ");
			while(string_ptr != NULL){
				temp_str_ptr = string_ptr;
				if(strstr(temp_str_ptr,node_info)){
					npages = strtoul((string_ptr + strlen(node_info)), NULL, 0);
					printf("%lu pages allocated in Node %d\n", npages, node);
					return npages;
					}
				string_ptr = strtok(NULL, " ");
 				}
			}
		}	

	return -1;	
}

void write_read_pattern_into_memory()
{
	void *mmap_pointer;
	unsigned long memory_to_use = 0;

        printf("\nScenario : Pattern Write Read Scenario:\n\n");
	/* Compute 80% of memory and use for write and read */
	memory_to_use = (total_mem * 80 ) / 100;
	printf("mmap memory %lu bytes\n", memory_to_use);
        mmap_pointer = mmap_memory(memory_to_use);
        printf("Lock all mapped memory \n");
	lock_mem(mmap_pointer, memory_to_use);
        printf("Write into mapped memory \n");
        write_memory(mmap_pointer, PATTERN, memory_to_use);
        printf("Reading from memory\n");
        read_memory(mmap_pointer,PATTERN, memory_to_use);
        printf("Verifying whether pfn exists for all virtual pages\n");
	verify_page_fault(mmap_pointer, memory_to_use);
	printf("Unlocking memory\n");
	unlock_mem(mmap_pointer, memory_to_use);
        printf("Unmapping Memory\n");
        munmap(mmap_pointer, memory_to_use);
}
	
void write_read_pattern_softoffline()
{
	void *mmap_pointer;
	int madvise_status;
	unsigned long memory_to_use = 0;

	/* Compute 10% of memory and use for write and read */
	memory_to_use = (total_mem * 10 ) / 100;
	printf("mmap memory %lu bytes\n", memory_to_use);
        mmap_pointer = mmap_memory(memory_to_use);
        printf("Lock all mapped memory \n");
	lock_mem(mmap_pointer, memory_to_use);
        printf("Write into mapped memory \n");
        write_memory(mmap_pointer,PATTERN, memory_to_use);
        printf("Soft offline pages \n");
	madvise_status = madvise(mmap_pointer,memory_to_use, MADV_SOFT_OFFLINE);
	if (madvise_status){
		perror("madvise");
		exit(-1);
	}
        printf("Reading from memory\n");
        read_memory(mmap_pointer,PATTERN, memory_to_use);
        printf("Verifying whether pfn exists for all virtual pages\n");
	verify_page_fault(mmap_pointer, memory_to_use);
	printf("Unlocking memory\n");
	unlock_mem(mmap_pointer, memory_to_use);
        printf("Unmapping Memory\n");
        munmap(mmap_pointer, memory_to_use);
}
	
void write_read_pattern_numa_migration()
{
        void *mmap_pointer;
        unsigned long memory_to_use = 0;
	unsigned long npages = 0, pages_numa_map = 0;
	unsigned long mask;
	int mbind_status;

        printf("\nScenario : Numa Migration \n\n");
	if(numa_available == -1){
		printf("Numa library is not present");
		exit(255);
	}
	max_node = numa_max_node();

        /* Compute 10% of memory and use for write and read */
        memory_to_use = (total_mem * 10 ) / 100;
        mmap_pointer = mmap_memory(memory_to_use);

	/* Determine No of Pages */
	npages = (memory_to_use / ((unsigned long )getpagesize()));
	if ((memory_to_use % ((unsigned long )getpagesize()))){
		npages = npages + 1;
	}
	get_numa_nodes_to_use(memory_to_use);

	/* Set nodemask for node 1 */
	mask = 0;
	mask |= 1UL << nodes_to_use[0];

        /* Allocate in Node1 via mbind*/
        mbind_status = mbind(mmap_pointer, memory_to_use, MPOL_BIND, &mask, nodes_to_use[0] + 2, NULL);
        if(mbind_status){
                perror("mbind() fails");
                exit(-1);
        }

	/* Write Patterns in Node 1 */
        printf("Lock all mapped memory \n");
	lock_mem(mmap_pointer, memory_to_use);
        printf("Write into mapped memory \n");
        write_memory(mmap_pointer,PATTERN, memory_to_use);
	pages_numa_map = get_npages_from_numa_maps(mmap_pointer,nodes_to_use[0]);
        printf("Unlock all mapped memory \n");
	unlock_mem(mmap_pointer, memory_to_use);

	/* Check all pages are allocated in node we want*/
	if((pages_numa_map == npages) && (pages_numa_map != -1)){
		printf("All pages have been allocated in node %d \n", nodes_to_use[0]);
	}else{
		printf("Pages are not allocated in node %d\n", nodes_to_use[0]);
		exit(-1);
	}
	
	/* Set node mask for node 2 */
	mask = 0;
	mask |= 1UL << nodes_to_use[1];

        /* Move all pages to from node1 to node 2 via mbind */
        printf("Move pages from Node %d to Node %d \n",nodes_to_use[0], nodes_to_use[1]);
        mbind_status = mbind(mmap_pointer, memory_to_use, MPOL_BIND, &mask,
		nodes_to_use[1] + 2, (MPOL_MF_MOVE_ALL | MPOL_MF_STRICT));
	if(mbind_status){
                perror("mbind() fails");
                exit(-1);
        }

	/* Read Patterns from Node 2 */
        printf("Lock all mapped memory \n");
	lock_mem(mmap_pointer, memory_to_use);
        printf("Reading from memory\n");
        read_memory(mmap_pointer,PATTERN, memory_to_use);
	pages_numa_map = get_npages_from_numa_maps(mmap_pointer, nodes_to_use[1]);

	/* Check all pages are allocated in node we want */
	if((pages_numa_map == npages) && (pages_numa_map != -1)){
		printf("All pages have been allocated in node %d \n", nodes_to_use[1]);
	}else{
		printf("All pages are not allocated in node %d\n", nodes_to_use[1]);
		exit(-1);
	}
        printf("Unlock all mapped memory \n");
        unlock_mem(mmap_pointer, memory_to_use);
        printf("Unmapping Memory\n");
        munmap(mmap_pointer, memory_to_use);
}

int main(int argc, char *argv[])
{
	int option = 0, scenario = 0;
	get_total_mem_bytes();
	printf("Total memory size %lu bytes \n", total_mem);
	if (argc < 2){
		printf("Usage <execname> -s <scenario_no> \n");
		exit(255);
	}
	option = getopt(argc, argv,"s:");
	if (option != -1){
		scenario = atoi(optarg);
	}
	switch (scenario){
	case 1 :
		write_read_pattern_into_memory();
		break;
	case 2 :
		write_read_pattern_numa_migration();
		break;
	case 3 :
		write_read_pattern_softoffline();
		break;
	default:
		printf("Please Provide valid scenario\n");
		break;
	}
	printf("Test Passed!!\n");

	return 0;
}

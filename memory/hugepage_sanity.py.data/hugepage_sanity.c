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
 * Author: Harish<harish@linux.vnet.ibm.com>
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>

#define MAP_HUGE_2MB    (21 << MAP_HUGE_SHIFT)
#define MAP_HUGE_16MB    (24 << MAP_HUGE_SHIFT)
#define MAP_HUGE_1GB    (30 << MAP_HUGE_SHIFT)
#define MAP_HUGE_SHIFT  26
#define PROT ( PROT_READ | PROT_WRITE )
#define HUGEPAGEFILE  "/sys/kernel/mm/hugepages/hugepages-%lukB/nr_hugepages"

int FLAGS = (MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB);
unsigned long MEM_SIZE = 1048576, TMP_SIZE, poolsize, exist;
char buf[100];
FILE *fd;

static long local_read_meminfo(const char *tag)
{
	unsigned long val = 0;
	char buff[256];
	int memsize;
	FILE *meminfo = fopen("/proc/meminfo", "r");
	if (meminfo == NULL)
		exit(-1);
	while (fgets(buff, sizeof(buff), meminfo)) {
		if(sscanf(buff, tag, &memsize) == 1)
			val = memsize;
	}
	if (fclose(meminfo) != 0)
		exit(-1);
	return val;
}

static void setup_hugetlb_pool(unsigned long size, long count)
{
	snprintf(buf, sizeof buf, HUGEPAGEFILE, size);

	fd = fopen(buf, "w");
	if (!fd) {
		printf("Cannot open nr_hugepages for writing\n");
		exit(-1);
	}
	fprintf(fd, "%lu", count);
	fclose(fd);

	/* Wait till pages are allocated*/
	sleep(5);
	/* Confirm the resize worked */
	fd = fopen(buf, "r");
	if (!fd) {
		printf("Cannot open nr_hugepages for reading\n");
		exit(-1);
	}
	fscanf(fd, "%lu", &poolsize);
	fclose(fd);
	if (poolsize != count) {
		printf("Failed to resize pool to %lu pages. Got %lu instead\n",
			count, poolsize);
		exit(-1);
	}
}

static unsigned long get_hugepage_bytes()
{
	unsigned long pagesize = local_read_meminfo("Hugepagesize: %lu kB");
	if (pagesize < 0)
		return -1;
	return pagesize * 1024;
}

static int alloc_hugepage(unsigned long size, unsigned long no_page)
{
	char *addr;
	unsigned long total = size * no_page;
	TMP_SIZE = MEM_SIZE * total;

	if (size == 1024)
		FLAGS |= MAP_HUGE_1GB;
	else if (size == 2)
		FLAGS |= MAP_HUGE_2MB;
	else
		FLAGS |= MAP_HUGE_16MB;

	addr = mmap(NULL, TMP_SIZE, PROT, FLAGS, -1, 0);
	if (addr == MAP_FAILED)
	{
		printf("Allocation of %lu MB failed using HUGEPAGE size\n", size);
		return -1;
	}
	printf("Allocation successful for %lu MB of %luMB Hugepage size\n", total, size);

	if (memset(addr, 'x', TMP_SIZE) == NULL) {
		printf("Memset Failed - > %d MB not supported\n", total);
		return -1;
	}

	printf("Memset successful for %d MB Hugepage\n", total);
	/* Un-map entire region, must be hugepage-aligned*/
	if (munmap(addr, TMP_SIZE)) {
		printf("Unmap failed\n");
		return -1;
	}
	return 0;
}

static int check_alloc_free_huge_page(unsigned long size, unsigned long pages)
{
	int flag = 0;
	snprintf(buf, sizeof buf, HUGEPAGEFILE, size * 1024);
	if (access(buf, F_OK) == -1) {
		printf("Given hugepage size is not supported in kernel\n");
		exit(-1);
	}
	fd = fopen(buf, "r");
	if (!fd) {
		printf("Cannot open nr_hugepages for reading\n");
		exit(-1);
	}
	fscanf(fd, "%lu", &exist);
	fclose(fd);

	printf("Existing hugepages %lu\n", exist);
	printf("Setting hugepages to %lu\n", pages + exist);
	setup_hugetlb_pool(size * 1024, pages + exist);
	flag = alloc_hugepage(size, pages);
	printf("Re-setting hugepages to %lu\n", exist);
	setup_hugetlb_pool(size * 1024, exist);
	return flag;
}

int
main(int argc, char *argv[])
{
	unsigned long no_page, size, val;
	if (argc > 3) {
		printf("Usage <execname> [hugepage-size](MB)  [no-of-hugepages]\n");
		exit(-1);
	}
	else if (argc == 1) {
		printf("Using default hugepagesize and 1 hugepage\n");
		size = get_hugepage_bytes() / MEM_SIZE;
		no_page = 1;
	}
	else if (argc == 2) {
		size = atol(argv[1]);
		no_page = 1;
	}
	else if (argc == 3) {
		size = atol(argv[1]);
		no_page = atol(argv[2]);
	}
	/*
	 * If Hugepage attributes are not available in /proc/meminfo
	 * error out gracefully before starting the test
	 */
	if (size <= 0) {
		printf("Error: Pagesize is invalid or not available\n");
		return -1;
	}
	printf("PAGESIZE: %lu MB\tNumber of pages: %lu\n", size, no_page);

	if (!check_alloc_free_huge_page(size, no_page))
		printf("Test Passed!!\n");
	else {
		printf("Test Failed!!\n");
		return -1;
	}
	return 0;

}

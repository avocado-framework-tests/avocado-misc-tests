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
 * Copyright: 2026 IBM
 * Author: Pavithra <pavithra@linux.ibm.com>
 *
 * PTE set/clear workload for page_table_check hook counting.
 * Usage:
 *   ./ptc_pte set   [nr_pages]  -- mmap + fault-in (exercises set_ptes)
 *   ./ptc_pte clear [nr_pages]  -- mmap + fault-in + munmap
 *                                  (exercises ptep_get_and_clear)
 * Exit: 0 on success, 1 on error.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

int main(int argc, char *argv[])
{
	long page_size;
	int nr_pages;
	size_t map_size;
	char *addr;
	int i;

	if (argc < 2) {
		fprintf(stderr, "Usage: %s set|clear [nr_pages]\n", argv[0]);
		return 1;
	}

	page_size = sysconf(_SC_PAGE_SIZE);
	if (page_size <= 0) {
		perror("sysconf");
		return 1;
	}

	nr_pages = (argc >= 3) ? atoi(argv[2]) : 64;
	if (nr_pages <= 0) {
		fprintf(stderr, "nr_pages must be > 0\n");
		return 1;
	}

	map_size = (size_t)nr_pages * (size_t)page_size;

	addr = mmap(NULL, map_size, PROT_READ | PROT_WRITE,
		    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (addr == MAP_FAILED) {
		perror("mmap");
		return 1;
	}

	for (i = 0; i < nr_pages; i++)
		((volatile char *)addr)[i * page_size] = (char)(i & 0xFF);

	if (munmap(addr, map_size) != 0) {
		perror("munmap");
		return 1;
	}

	return 0;
}

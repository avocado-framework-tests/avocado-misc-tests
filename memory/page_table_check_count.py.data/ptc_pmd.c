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
 * PMD set/clear workload for page_table_check hook counting.
 * Usage:
 *   ./ptc_pmd set    -- THP collapse -> __page_table_check_pmds_set
 *   ./ptc_pmd clear  -- THP collapse + mprotect split ->
 *                       __page_table_check_pmd_clear
 * Exit: 0 on success, 77 if THP collapse timed out, 1 on error.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define PMD_SIZE_BYTES  (2UL * 1024 * 1024)

static int smaps_has_anon_hugepage(const char *addr)
{
	FILE *fp;
	char line[256];
	int in_vma = 0;

	fp = fopen("/proc/self/smaps", "r");
	if (!fp)
		return 0;
	while (fgets(line, sizeof(line), fp)) {
		unsigned long start, end;

		if (sscanf(line, "%lx-%lx", &start, &end) == 2) {
			in_vma = (start == (unsigned long)addr);
			continue;
		}
		if (in_vma && strncmp(line, "AnonHugePages:", 14) == 0) {
			unsigned long kb = 0;

			sscanf(line, "AnonHugePages: %lu kB", &kb);
			fclose(fp);
			return kb > 0;
		}
	}
	fclose(fp);
	return 0;
}

int main(int argc, char *argv[])
{
	long page_size;
	char *raw, *addr;
	size_t i;
	int mode_clear;
	int collapsed, poll;

	if (argc < 2) {
		fprintf(stderr, "Usage: %s set|clear\n", argv[0]);
		return 1;
	}

	mode_clear = (strcmp(argv[1], "clear") == 0);

	page_size = sysconf(_SC_PAGE_SIZE);
	if (page_size <= 0) {
		perror("sysconf");
		return 1;
	}

	/* Over-allocate to carve out a PMD-aligned slice */
	raw = mmap(NULL, PMD_SIZE_BYTES * 2, PROT_READ | PROT_WRITE,
		   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (raw == MAP_FAILED) {
		perror("mmap");
		return 1;
	}

	addr = (char *)(((unsigned long)raw + PMD_SIZE_BYTES - 1) &
			~(PMD_SIZE_BYTES - 1));

	if (addr > raw)
		munmap(raw, (size_t)(addr - raw));
	if (addr + PMD_SIZE_BYTES < raw + PMD_SIZE_BYTES * 2)
		munmap(addr + PMD_SIZE_BYTES,
		       (size_t)((raw + PMD_SIZE_BYTES * 2) -
				(addr + PMD_SIZE_BYTES)));

	if (mmap(addr, PMD_SIZE_BYTES, PROT_READ | PROT_WRITE,
		 MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) != addr) {
		perror("mmap MAP_FIXED");
		return 77;
	}

	if (madvise(addr, PMD_SIZE_BYTES, MADV_HUGEPAGE) != 0) {
		perror("madvise");
		return 77;
	}

	for (i = 0; i < PMD_SIZE_BYTES; i += (size_t)page_size)
		addr[i] = (char)(i & 0xFF);

	collapsed = 0;
	for (poll = 0; poll < 500; poll++) {
		if (smaps_has_anon_hugepage(addr)) {
			collapsed = 1;
			break;
		}
		usleep(10000);
	}

	if (!collapsed) {
		fprintf(stderr, "ptc_pmd: THP collapse did not occur within 5s\n");
		munmap(addr, PMD_SIZE_BYTES);
		return 77;
	}

	if (mode_clear) {
		if (mprotect(addr, PMD_SIZE_BYTES / 2, PROT_READ) != 0) {
			perror("mprotect");
			munmap(addr, PMD_SIZE_BYTES);
			return 1;
		}
	}

	if (munmap(addr, PMD_SIZE_BYTES) != 0) {
		perror("munmap");
		return 1;
	}

	return 0;
}

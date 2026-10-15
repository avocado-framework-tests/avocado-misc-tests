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
 * Bug-verification workloads for page_table_check commit series.
 * Usage:
 *   ./ptc_bug thp_collapse_phase fault|collapse|full
 *   ./ptc_bug user_va_mapping [nr_pages]
 * Exit: 0 on success, 77 if THP collapse timed out, 1 on error.
 */

#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
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

/* Write '1\n' to stdout, then block reading one byte from stdin. */
static void pause_and_wait(void)
{
	char buf[1];

	if (write(STDOUT_FILENO, "1\n", 2) < 0) {
		perror("pause_and_wait: write");
		_exit(1);
	}
	if (read(STDIN_FILENO, buf, 1) < 0) {
		perror("pause_and_wait: read");
		_exit(1);
	}
}

static char *setup_pmd_region(long page_size)
{
	char *raw, *addr;

	raw = mmap(NULL, PMD_SIZE_BYTES * 2, PROT_READ | PROT_WRITE,
		   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (raw == MAP_FAILED)
		return MAP_FAILED;

	addr = (char *)(((unsigned long)raw + PMD_SIZE_BYTES - 1) &
			~(PMD_SIZE_BYTES - 1));

	if (addr > raw)
		munmap(raw, (size_t)(addr - raw));
	if (addr + PMD_SIZE_BYTES < raw + PMD_SIZE_BYTES * 2)
		munmap(addr + PMD_SIZE_BYTES,
		       (size_t)((raw + PMD_SIZE_BYTES * 2) - (addr + PMD_SIZE_BYTES)));

	if (mmap(addr, PMD_SIZE_BYTES, PROT_READ | PROT_WRITE,
		 MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) != addr)
		return MAP_FAILED;

	if (madvise(addr, PMD_SIZE_BYTES, MADV_HUGEPAGE) != 0)
		return MAP_FAILED;

	{
		size_t i;

		for (i = 0; i < PMD_SIZE_BYTES; i += (size_t)page_size)
			addr[i] = (char)(i & 0xFF);
	}
	return addr;
}

static int mode_thp_collapse_phase(const char *submode)
{
	long page_size;
	char *addr;
	int collapsed, poll_i;
	int is_fault    = (strcmp(submode, "fault")   == 0);
	int is_collapse = (strcmp(submode, "collapse") == 0);
	int is_full     = (strcmp(submode, "full")     == 0);

	if (!is_fault && !is_collapse && !is_full) {
		fprintf(stderr, "thp_collapse_phase: unknown submode '%s'\n",
			submode);
		return 1;
	}

	page_size = sysconf(_SC_PAGE_SIZE);
	if (page_size <= 0) {
		perror("sysconf");
		return 1;
	}

	addr = setup_pmd_region(page_size);
	if (addr == MAP_FAILED) {
		perror("setup_pmd_region");
		return 77;
	}

	if (is_fault) {
		pause_and_wait();
		munmap(addr, PMD_SIZE_BYTES);
		return 0;
	}

	if (is_collapse)
		pause_and_wait();

	collapsed = 0;
	for (poll_i = 0; poll_i < 500; poll_i++) {
		if (smaps_has_anon_hugepage(addr)) {
			collapsed = 1;
			break;
		}
		usleep(10000);
	}

	if (!collapsed) {
		fprintf(stderr, "thp_collapse_phase %s: collapse timed out\n",
			submode);
		munmap(addr, PMD_SIZE_BYTES);
		return 77;
	}

	if (is_collapse)
		pause_and_wait();

	munmap(addr, PMD_SIZE_BYTES);
	return 0;
}

static int mode_user_va_mapping(int nr_pages)
{
	long page_size;
	size_t map_size;
	char *addr;
	int i;

	page_size = sysconf(_SC_PAGE_SIZE);
	if (page_size <= 0) {
		perror("sysconf");
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
		((volatile char *)addr)[(size_t)i * (size_t)page_size] =
			(char)(i & 0xFF);

	if (munmap(addr, map_size) != 0) {
		perror("munmap");
		return 1;
	}

	return 0;
}

int main(int argc, char *argv[])
{
	if (argc < 2) {
		fprintf(stderr,
			"Usage: %s <mode> [args]\n"
			"  thp_collapse_phase fault|collapse|full\n"
			"  user_va_mapping [nr_pages]\n",
			argv[0]);
		return 1;
	}

	if (strcmp(argv[1], "thp_collapse_phase") == 0) {
		if (argc < 3) {
			fprintf(stderr,
				"thp_collapse_phase: requires submode\n");
			return 1;
		}
		return mode_thp_collapse_phase(argv[2]);
	}

	if (strcmp(argv[1], "user_va_mapping") == 0) {
		int nr = (argc >= 3) ? atoi(argv[2]) : 64;

		if (nr <= 0) {
			fprintf(stderr, "nr_pages must be > 0\n");
			return 1;
		}
		return mode_user_va_mapping(nr);
	}

	fprintf(stderr, "Unknown mode: %s\n", argv[1]);
	return 1;
}

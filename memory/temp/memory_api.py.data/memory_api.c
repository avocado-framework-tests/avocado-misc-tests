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
 * Author: Ranjit Manomohan <ranjitm@google.com>
 * Modified by: Harish<harish@linux.vnet.ibm.com>
 */

#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>

/* This file includes a simple set of memory allocation calls that
 * a user space program can use to allocate/free or move memory mappings.
 * The intent of this program is to make it easier to verify if the kernel
 * internal mappings are correct. */

#define PAGE_SHIFT 12

#define ROUND_PAGES(memsize) ((memsize >> (PAGE_SHIFT)) << PAGE_SHIFT)

/* approximately half of memsize, page aligned */
#define HALF_MEM(memsize) ((memsize >> (PAGE_SHIFT))<<(PAGE_SHIFT - 1))

#define handle_error(msg) \
   do { perror(msg); exit(EXIT_FAILURE); } while (0)

static void
handler(int sig, siginfo_t *si, void *unused)
{
        printf("Got SIGSEGV at address: 0x%lx\n", (long) si->si_addr);
        exit(255);
}

void *mremap(void *old_address, size_t old_size,
                    size_t new_size, int flags, ... /* void *new_address */);

int main(int argc, char *argv[]) {
	unsigned long i, numpages, fd, pagesize, memsize;
	int induce_err = 0;
	char *mem;
        struct sigaction sa;

        sa.sa_flags = SA_SIGINFO;
        sigemptyset(&sa.sa_mask);
        sa.sa_sigaction = handler;
        if (sigaction(SIGSEGV, &sa, NULL) == -1)
                handle_error("sigaction");

        pagesize = getpagesize();
	if (argc != 3) {
		printf("Usage: %s <memory_size> <induce-err-flag>\n", argv[0]);
		exit(EXIT_FAILURE);
	}

	memsize = strtoul(argv[1], NULL, 10);
        if (argc == 3)
                induce_err = atoi(argv[2]);

	memsize = ROUND_PAGES(memsize);

	/* We should be limited to < 4G so any size other than 0 is ok */
	if (memsize == 0) {
		printf("Invalid memsize\n");
		exit(EXIT_FAILURE);
	}


	numpages = memsize / pagesize;

	mlockall(MCL_FUTURE);

	mem = malloc(memsize);

	if (mem == (void*) -1) {
		perror("Failed to allocate memory using malloc\n");
		handle_error("malloc");
	}

	printf("Successfully allocated malloc memory %lu bytes @%p\n",
				memsize,  mem);

	sleep(1);

	free(mem);
	mem =  mmap(0, memsize, PROT_READ | PROT_WRITE,
			MAP_PRIVATE| MAP_ANONYMOUS,
			-1, 0);

	if (mem == (void*) -1) {
		perror("Failed to allocate anon private memory using mmap\n");
		handle_error("mmap");
	}

	printf("Successfully allocated anon mmap memory %lu bytes @%p\n",
				memsize,  mem);

	sleep(1);

	if (-1 == mprotect(mem, HALF_MEM(memsize), PROT_READ)) {
		perror("Failed to W protect memory using mprotect\n");
		handle_error("mprotect");
	}

	if (induce_err){
		printf("Inducing error\n");
		*(mem) = 1;
	}

	printf("Successfully write protected %lu bytes @%p\n",
			HALF_MEM(memsize), mem);

	sleep(1);

	if (-1 == mprotect(mem, HALF_MEM(memsize),
					 PROT_READ | PROT_WRITE)) {
		perror("Failed to RW protect memory using mprotect\n");
		handle_error("mprotect");
	}

	printf("Successfully cleared write protected %lu bytes @%p\n",
			HALF_MEM(memsize), mem);
	sleep(1);

	/* Mark all pages with a specific pattern */
	for (i = 0; i < numpages; i++) {
		unsigned long *ptr = (unsigned long *)(mem + i*pagesize);
		*ptr = i;
	}

	mem = mremap(mem , memsize,
				memsize + HALF_MEM(memsize),
				1 /* MREMAP_MAYMOVE */);

	if (mem == MAP_FAILED) {
		perror("Failed to remap expand anon private memory\n");
		handle_error("mremap");
	}

	printf("Successfully remapped %lu bytes @%p\n",
			memsize + HALF_MEM(memsize), mem);

	sleep(1);
	/* Read all pages to check the pattern */
	for (i = 0; i < numpages; i++) {
		unsigned long value = *(unsigned long*)(mem + i*pagesize);
		if (value != i) {
			printf("remap error expected %lu got %lu\n",
					i, value);
			handle_error("wrong_value");
		}
	}

	if (munmap(mem, memsize + HALF_MEM(memsize))) {
		perror("Could not unmap and free memory\n");
		handle_error("munmap");
	}


	fd = open("/dev/zero", O_RDONLY);

	mem =  mmap(0, memsize, PROT_READ | PROT_WRITE,
			MAP_PRIVATE,
			fd, 0);

	if (mem == (void*) -1) {
		perror("Failed to allocate file backed memory using mmap\n");
		handle_error("mmap_fd");
	}

	printf("Successfully allocated file backed mmap memory %lu bytes @%p\n",
					 memsize, mem);
	sleep(1);

	if (munmap(mem, memsize)) {
		perror("Could not unmap and free file backed memory\n");
		handle_error("munmap");
	}

	exit(EXIT_SUCCESS);
}

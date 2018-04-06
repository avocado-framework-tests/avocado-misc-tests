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
 * Author: Harish <harish@linux.vnet.ibm.com>
 */

#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <errno.h>
#include <signal.h>

#define handle_error(msg) \
   do { perror(msg); exit(EXIT_FAILURE); } while (0)

static void
handler(int sig, siginfo_t *si, void *unused)
{
	printf("Got SIGSEGV at address: 0x%lx\n", (long) si->si_addr);
	exit(255);
}

int main(int argc, char **argv)
{
	if ((argc < 2) || (argc > 3)) {
		printf("bad args, usage: ./mprotect <nr-pages> <induce-err>\n");
		handle_error("Input");
	}

	unsigned long length = atol(argv[1]);
	unsigned long ps = getpagesize(), size , i, j = 0, iters = 1;
	char *seg;
	int fd, proto, ret, induce = 0, k = 0 ;
	struct sigaction sa;

	if (argc == 3)
		induce = atoi(argv[2]);

	fd = open("/dev/zero", O_RDWR);
	size = ps * length;

	sa.sa_flags = SA_SIGINFO;
	sigemptyset(&sa.sa_mask);
	sa.sa_sigaction = handler;
	if (sigaction(SIGSEGV, &sa, NULL) == -1)
		handle_error("sigaction");

	if ((seg = (char *)mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0)) == (void *)-1)
	{	
		printf("mmap failed %s", strerror(errno));
		close(fd);
		return 0;
	}
	ret = mprotect(seg, size , PROT_READ | PROT_WRITE);
	if (ret == -1)
               	handle_error("mprotect_out");
	memset(seg, 2, size);

	printf("\nmemset -> PASS\n");
	printf("mprotect start addr: 0x%lx\n", (long)seg);
	for (j = 0; j < size; j+=ps)
	{
		k = seg[j];
		if(k != 2)
			handle_error("memset");
		ret = mprotect((void *)&seg[j], seg[j], PROT_NONE);
		if (ret == -1)
        		handle_error("mprotect_in");
	}
	printf("mprotect end addr: 0x%lx\n", (long)&seg[j-ps]);
	printf("\nmprotect PROT_NONE per page -> PASS\n");
	if(induce){
		printf("Accessing last page with PROT_NONE, expecting SIGSEGV\n");
		k = seg[j-ps];
	}
	ret = mprotect(seg, size , PROT_READ);
	if (ret == -1)
               	handle_error("mprotect_out");

	printf("\nmprotect PROT_READ -> PASS\n");
	printf("Accessing last page 0x%lx after PROT_READ\n", &seg[j-ps]);
	k = seg[j-ps];
	if (k != 2)
		handle_error("wrong_val");
	else
		printf("\nREADING LAST PAGE -> PASS\n");
	printf("Test passed\n");
	return 0;
}

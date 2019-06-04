/*
 * compile with:
 *    cc -O2 mmaplarge.c -o mmaplarge
 * Run with:
 *    ./mmaplarge [size in TB (default 1TB)]
 *  Will take a few min to run
 *
 * Copyright (C) 2019 Michael Neuling <mikey@linux.ibm.com>, IBM
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version
 * 2 of the License, or (at your option) any later version.
 */

#include <stdlib.h>
#include <stdio.h>
#include <stddef.h>
#include <assert.h>
#include <unistd.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/wait.h>

#define ONEMB 0x100000

// 1MB default total
#define MAPSIZE_DEFAULT   ONEMB


// 1MB maps
#define MMAPSIZE 0x100000
#define PAGESIZE (getpagesize())

#define READ 0
#define WRITE 1

double t2d(struct timeval *t) {
	return t->tv_sec*1000000.0 + t->tv_usec;
}

int main (int argc, char *argv[])
{
	unsigned long mapsize = MAPSIZE_DEFAULT;
	unsigned long mapnum;
	unsigned long **maps;
	unsigned long pagespermap = MMAPSIZE/PAGESIZE;
	char *m;
	int i, j;
	char x;
	int fd[2];
	int pid;

	if (argc == 2) {
		mapsize = atol(argv[1]) * ONEMB;
	}
	mapnum = mapsize/MMAPSIZE;
        printf ("mapsize = %lu, pagespermap=%d\n", mapsize, pagespermap);

	if (pipe(fd))
		exit(1);

	pid = fork();
	if (pid < 0)
		exit(1);

	if (pid) {
	struct timeval before, after;
	double time;

	/* wait for child */
	read(fd[READ], &x, 1);

	printf("Waiting for child (%i) to exit\n", pid);
	gettimeofday(&before, NULL);
	wait(NULL);
	gettimeofday(&after, NULL);
	time = t2d(&after) - t2d(&before);
	printf("Time to kill: %fsec\n", time/1000000);
	printf("value of x = %d\n", x);
	exit(0);
	}

	maps = malloc(sizeof(unsigned long *)*mapnum);

	/* Maping data */
	printf("Mapping %liMB worth of pages\n", mapsize/ONEMB);
	for (i = 0 ; i < mapnum; i++) {
		maps[i] = mmap(NULL, MMAPSIZE, PROT_READ|PROT_WRITE,
		  MAP_PRIVATE | MAP_ANON, -1, 0);
		assert(maps[i]);
	}
	/* Reading every page in. This maps to the zero page so no
		* real memrory used
	*/
	printf("Touching pages\n", i);
	for (i = 0 ; i < mapnum; i++) {
		m =  (char *)maps[i];
		for(j = 0; j < pagespermap; j++) {
			m = (char *)maps[i] + j*PAGESIZE;
			x += *m; // read page
		}
	}

	printf("Waiting to be killed: x=%x\n", x);
	/* signal parent we're done */
	write(fd[WRITE], &x, 1);
	exit(0);
}


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
 *
 * Author:       Larry Woodman <lwoodman@redhat.com>
 * Modified By:  Harish <harish@linux.vnet.ibm.com>
 */

#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>
#include <stdio.h>

main(int argc,char *argv[])
{
        unsigned long size, psize, procs, itterations;
        char    *ptr;
        char    *i;
        int     pid, j, k, status;

        if ((argc <= 1)||(argc >4)) {
                printf("bad args, usage: forkoff <memsize MB> #children #itterations\n");
                exit(-1);
        }
        size = ((long)atol(argv[1])*1024*1024);
        psize = getpagesize();
        procs = atol(argv[2]);
        itterations = atol(argv[3]);
        printf("mmaping %ld anonymous bytes\n", size);
        ptr = (char *)mmap((void *)0, size, PROT_READ | PROT_WRITE, MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
        if ( ptr == (char *) -1 ) {
                printf("address = %lx\n", ptr);
                perror("");
        }
        k = procs;
        do{
                pid = fork();
                if (pid == -1) {
                        printf("fork failure\n");
                        exit(-1);
                } else if (!pid) {
			printf("PID %d touching %d pages\n", getpid(), size/psize);

                        for (j=0; j<itterations; j++) {
                                for (i = ptr; i < ptr + size - 1; i += psize) {
					*i=(char)'i';
                                }
                        }
			exit(0);
		}
	} while(--k);
	while (procs-- && wait(&status));
}

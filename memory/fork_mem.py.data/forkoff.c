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
#include <string.h>
#include <sys/wait.h>

int
main(int argc,char *argv[])
{
        unsigned long size, psize, procs, iterations;
        char    *ptr;
        char    *i;
        int     pid, j, k, status, maxpid=0;
        char    buf[32]={0x0};

        if ((argc <= 1)||(argc >4)) {
                printf("bad args, usage: forkoff <memsize MB> #children #iterations\n");
                exit(-1);
        }
	/* size of memory for each process */
        size = ((long)atol(argv[1])*1024*1024);
        
	/* default page size */
	psize = getpagesize();
	
	/* number of processes to be created */
        procs = atol(argv[2]);

	/* number of pages inside the mmap-ed memory to be touched */
        iterations = atol(argv[3]);

	/* check if the processes to be created don't exceed the max possible pid  */
        FILE *fd=fopen("/proc/sys/kernel/pid_max","r");
        fgets(buf,32,fd);
        maxpid=atol(buf);
        if ( procs > maxpid){
             printf("\nNumber of Children %lu provided is higher than maxpid supported on this system %d.. Exiting!!\n",procs,maxpid);
             exit(-1);
        }else{
             printf("\nMaxpid / Children supported on the system %d\n",maxpid);
        }
        fclose(fd);

        printf("mmaping %ld anonymous bytes\n", size);
        ptr = (char *)mmap((void *)0, size, PROT_READ | PROT_WRITE, MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
        if ( ptr == (char *) -1 ) {
                printf("address = %sx\n", ptr);
                perror("");
        }
		fflush(stdout);
        k = procs;
        do{
                pid = fork();
                if (pid == -1) {
                        printf("fork failure error %d: %s\n", errno, strerror(errno));
                        exit(-1);
                } else if (!pid) {
			printf("PID %d touching %lu pages\n", getpid(), iterations);

                        for (j=0; j<iterations; j++) {
                                for (i = ptr; i < ptr + size - 1; i += psize) {
					*i=(char)'i';
                                }
                        }
			exit(0);
		}
	} while(--k);
	while (procs-- && wait(&status));
	return 0;
}


/*
   munmap.c
   This is a macrobenchmark for TLB flush range testing.

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

   Copyright (C) Intel 2012
   Coypright Alex Shi alex.shi@intel.com 

   gcc -o munmap munmap.c -lrt -lpthread -O2

    #perf stat -e r881,r882,r884 -e r801,r802,r810,r820,r840,r880,r807 -e rc01 -e r4901,r4902,r4910,r4920,r4940,r4980 -e r5f01  -e rbd01,rdb20  -e r4f02 -e r8004,r8201,r8501,r8502,r8504,r8510,r8520,r8540,r8580  -e rae01,rc820,rc102,rc900 -e r8600  -e rcb10  ./munmap 
*/

#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/mman.h>
#include <time.h>
#include <sys/types.h>
#include <pthread.h>


#define PAGE_SIZE 	4096
#define HPAGE_SIZE 	4096*512

#ifndef MAP_HUGETLB
#define MAP_HUGETLB	0x40000
#endif


long getnsec(clockid_t clockid) {
        struct timespec ts;
        if (clock_gettime(clockid, &ts) == -1)
                perror("clock_gettime failed");
        return (long) ts.tv_sec * 1000000000 + (long) ts.tv_nsec;
}

//data for threads
struct data{
	int *readp;
	void *startaddr;
	int rw;
	int loop;
};
volatile int * threadstart;
//thread for memory accessing
void *accessmm(void *data){
	struct data *d = data;
	long *actimes;
	char x;
	int i, k;
	int randn[PAGE_SIZE];
	
	for (i=0;i<PAGE_SIZE; i++)
		randn[i] = rand();

	actimes = malloc(sizeof(long));

	while (*threadstart == 0 )
		usleep(1);

	if (d->rw == 0)
		for (*actimes=0; *threadstart == 1; (*actimes)++)
			for (k=0; k < *d->readp; k++)
				x = *(volatile char *)(d->startaddr + randn[k]%FILE_SIZE); 
	else
		for (*actimes=0; *threadstart == 1; (*actimes)++)
			for (k=0; k < *d->readp; k++)
				*(char *)(d->startaddr + randn[k]%FILE_SIZE) = 1; 
	return actimes;
}

int main(int argc, char *argv[])
{
        static  char            optstr[] = "n:l:p:w:ht:";
	int n = 8;	/* default flush entries number */
	int l = 1; 	/* default loop times */
	int p = 512;	/* default accessed page number, after munmap */
	int er = 0, rw = 0, h = 0, t = 0; /* d: debug; h: use huge page; t thread number */
	int pagesize = PAGE_SIZE; /*default for regular page */
	volatile char x;
	long protindex = 0;

	int i, j, k, c;
	void *m1, *startaddr;
	unsigned long *startaddr2[1024*512];
	volatile void *tempaddr;
	clockid_t clockid = CLOCK_MONOTONIC;
	unsigned long start, stop, mptime, actime;
	int randn[PAGE_SIZE];

	pthread_t	pid[1024];
	void * res;
	struct data data;

	for (i=0;i<PAGE_SIZE; i++)
		randn[i] = rand();

        while ((c = getopt(argc, argv, optstr)) != EOF)
                switch (c) {
                case 'n':
                        n = atoi(optarg);
                        break;
                case 'p':
                        p = atoi(optarg);
                        break;
                case 'h':
                        h = 1;
                        break;
                case 'w':
                        rw = atoi(optarg);
                        break;
                case 't':
                        t = atoi(optarg);
                        break;
                case '?':
                        er = 1;
                        break;
                }
        if (er) {
                printf("usage: %s %s\n", argv[0], optstr);
                exit(1);
	}

	//printf("my pid is %d n=%d p=%d t=%d\n", getpid(), n, p, t);	
	if (h == 0){
		startaddr = mmap(0, FILE_SIZE, PROT_READ|PROT_WRITE, MAP_ANONYMOUS | MAP_SHARED, -1, 0);
		for (j = 0; j < FILE_SIZE/PAGE_SIZE/n; j++) {
			startaddr2[j] = mmap(0, PAGE_SIZE*n, PROT_READ|PROT_WRITE, MAP_ANONYMOUS | MAP_SHARED, -1, 0);
			if (startaddr2[j] == MAP_FAILED) {
				perror("mmap");
				exit(1);
			}
			*startaddr2[j] = 1;
		}
		pagesize = PAGE_SIZE;
	} else {
		startaddr = mmap(0, FILE_SIZE, PROT_READ|PROT_WRITE, MAP_ANONYMOUS | MAP_SHARED | MAP_HUGETLB, -1, 0);
		for (j = 0; j < FILE_SIZE/HPAGE_SIZE/n; j++) {
			startaddr2[j] = mmap(0, HPAGE_SIZE*n, PROT_READ|PROT_WRITE, MAP_ANONYMOUS | MAP_SHARED, -1, 0);
			if (startaddr2[j] == MAP_FAILED) {
				perror("mmap");
				exit(1);
			}
			*startaddr2[j] = 1;
		}
		pagesize = HPAGE_SIZE;
	}
	if (startaddr == MAP_FAILED) {
		perror("mmap");
		exit(1);
	}

	start = getnsec(clockid);
	//access whole memory, will generate many page faults 
	for (tempaddr = startaddr; tempaddr < startaddr + FILE_SIZE; tempaddr += pagesize)
		memset((char *)tempaddr, 0, 1);
        stop = getnsec(clockid);
//	printf("get 256K pages with one byte writing uses %lums, %luns/time \n", 
//		(stop - start)/1000000, (stop-start)*pagesize/FILE_SIZE);

	//thread created, and goes to sleep
	threadstart = malloc(sizeof(int));
	*threadstart = 0;
	data.readp = &p; data.startaddr = startaddr; data.rw = rw; data.loop = l;
	for (i=0; i< t; i++)
		if(pthread_create(&pid[i], NULL, accessmm, &data))
			perror("pthread create");
	//wait for randn[] filling.
	if (t!=0)	sleep(1);

	mptime = actime = 0;
	if (t != 0)
		start = getnsec(clockid);
	//kick threads, let them running.
	*threadstart = 1;
	for (j = 0; j < FILE_SIZE/pagesize/n; j++) {

		if (t == 0)
			start = getnsec(clockid);

		if(munmap(startaddr2[j], n*pagesize)==-1) {
			perror("munmap");
			goto end;
		}
		if (t == 0) {
			stop = getnsec(clockid);
			mptime += stop - start;
		}

		if (t == 0) {
			// access p number pages 
			start = stop; 
			if (rw == 0)
				for (k=0; k < p; k++)
					x = *(volatile char *)(startaddr + randn[k]%FILE_SIZE);
			else
				for (k=0; k < p; k++)
					*(char *)(startaddr + randn[k]%FILE_SIZE) = 1;
			actime += getnsec(clockid) - start;
		} 
	}
	//to avoid accessmm miss *threadstart == 1
	usleep(10000);//sleep 10ms
	*threadstart = 0;
	if (t != 0) {
		stop = getnsec(clockid);
		mptime += stop - start;
	}

	//get threads' result.
	for (i=0; i< t; i++) {
		if (pthread_join(pid[i], &res))
			perror("pthread_join");
		actime += *(long*)res;
	}
	l = FILE_SIZE/pagesize/n;
end:
	if ( t == 0 ) 
	       	printf("munmap use %lums %luns/time, memory access uses %lums %luns/time \n",
			 mptime/1000000, mptime/(l), actime/1000000, actime/p/l);
	else
		printf("munmap use %lums %luns/time, memory access uses %ld times/thread/ms, cost %ldns/time\n",
			 mptime/1000000, mptime/(l), actime*p*1000000/t/mptime, mptime*t/(actime*p));
	exit(0);
}

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
 * Author: Santhosh G <santhog4@linux.vnet.ibm.com>
 *	Praveen K Pandey <praveen@linux.vnet.ibm.com>
 *	Harish S<harish@linux.vnet.ibm.com>
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/mman.h>
#include <asm/mman.h>
#include <sys/time.h>


/* In a single mmap call we can try to allocate approximately 16Gb
   So chunk size id chosen as 16G */

#define MAP_CHUNK_SIZE	 17179869184UL	 /* 16GB */


#define ADDR_MARK_128TB  (1UL << 47) /* First address beyond 128TB */


static char *hind_addr(void)
{
	int bits = 48 + rand() % 15;
	return (char *) (1UL << bits);
}


static int validate_addr(char *ptr, int high_addr)
{
	unsigned long addr = (unsigned long) ptr;

	if (high_addr) {
		if (addr < ADDR_MARK_128TB) {
			printf("in high Bad address %lx\n", addr);
			    return 1;
		}
		return 0;
	}

	if (addr > ADDR_MARK_128TB) {
		printf("in low Bad address %lx\n", addr);
		return 1;
	}
	return 0;
}

static int validate_lower_address_hint(void)
{
	char *ptr;

	ptr = mmap((void *) (1UL << 45), MAP_CHUNK_SIZE, PROT_READ |
		PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);

	if (ptr == MAP_FAILED)
		return 0;

	return 1;
}

int mmap_chunks_lower(unsigned long no_of_chunks, unsigned long hugetlb_arg)
{
	unsigned long i;
	char *ptr;

	for (i = 0; i < no_of_chunks; i++) {
		ptr = mmap(NULL, MAP_CHUNK_SIZE, PROT_READ | PROT_WRITE,
			MAP_PRIVATE | MAP_ANONYMOUS | hugetlb_arg, -1, 0);

		if (ptr == MAP_FAILED) {
		printf("Map failed address < 128TB %p \n", ptr);
			if (validate_lower_address_hint()){
				printf("\n Mmap failed !!! So Problem i = %d\n", i);
				exit(-1);
			}
		}
		if (validate_addr(ptr, 0)){
			printf("\n Address failed, in > 128Tb !!! So Problem \n");
			exit(-1);
		}
	}
	printf("< 128Tb: \n chunks allocated= %d \n\n",i);
	return 0;
}

int mmap_chunks_higher(unsigned long no_of_chunks, unsigned long hugetlb_arg)
{
	unsigned long i;
	char *hptr;
	char *hint;
	int mmap_args = 0;
	for (i = 0; i < no_of_chunks; i++){
		hint = hind_addr();
		hptr = mmap(hint, MAP_CHUNK_SIZE, PROT_READ | PROT_WRITE,
			MAP_PRIVATE | MAP_ANONYMOUS | hugetlb_arg, -1, 0);

		if (hptr == MAP_FAILED){
			printf("\n Map failed at address %p < 384TB in iteration = %d \n", hptr, i);
			exit(-1);   
		}

		if (validate_addr(hptr, 1)){
			printf("\n Address failed, not in > 128Tb iterator = %d\n", i);
			exit(-1);
		}
	}
	printf("> 128Tb: \n chunks allocated= %d \n", i);
}


void alloc_page_full()
{

	printf("Allocating default pagesize pages < 128TB \n");
	/* Note: Allocating a 16GB chunk less due to heap space required for other mappings */
	mmap_chunks_lower(8190, 0);
	
	printf("Allocating default pagesize pages > 128TB \n");
	mmap_chunks_higher(24575, 0);		
}

void alloc_page_full_reverse()
{

	printf("Allocating default pagesize pages > 128TB \n");
	mmap_chunks_higher(24575, 0);
	printf("Allocating default pagesize pages < 128TB \n");
	/* Note: Allocating a 16GB chunk less due to heap space required for other mappings */
	mmap_chunks_lower(8190, 0);
}

void alloc_huge_reverse(int chunks)
{
	printf("Allocating hugepage chunks > 128TB \n");
	mmap_chunks_higher(chunks/2, MAP_HUGETLB);
	printf("Allocating hugepage chunks < 128TB \n");
	mmap_chunks_lower(chunks/2, MAP_HUGETLB);
}

void alloc_huge(int chunks)
{
	printf("Allocating hugepage chunks < 128TB \n");
	mmap_chunks_lower(chunks/2, MAP_HUGETLB);
	printf("Allocating hugepage chunks > 128TB \n");
	mmap_chunks_higher(chunks/2, MAP_HUGETLB);
}

void alloc_huge_below_hint(int chunks)
{
	printf("Allocating hugepage chunks < 128TB \n");
	mmap_chunks_lower(chunks, MAP_HUGETLB);
}

void alloc_huge_above_hint(int chunks)
{
	printf("Allocating hugepage chunks > 128TB \n");
	mmap_chunks_higher(chunks, MAP_HUGETLB);
}
	
void alloc_16g(int chunks)
{
	printf("Allocating 16G chunks < 128TB \n");
	mmap_chunks_lower(chunks/2, (MAP_HUGETLB | (34 << 26)));

	printf("Allocating 16G chunks > 128TB \n");
	mmap_chunks_higher(chunks/2, (MAP_HUGETLB | (34 << 26)));
}

void alloc_16g_below_hint(int chunks)
{
	printf("Allocating 16G chunks < 128TB \n");
	mmap_chunks_lower(chunks, (MAP_HUGETLB | (34 << 26)));
}

void alloc_16g_above_hint(int chunks)
{
	printf("Allocating 16G chunks > 128TB \n");
	mmap_chunks_higher(chunks, (MAP_HUGETLB | (34 << 26)));
}

/* <128Tb contains 8192 16Gb chunks
   >128Tb - 512Tb i.e 384Tb contains 24576 16Gb chunks */

void fixed_position()
{
	/* In this function we mmap 8000 1Tb slice for 64k pages,
	1Tb slice free for proper alignment,
	1Tb slice for 16M hugepages , 1Tb slice for 16G hugepage
	in both address ranges*/

	/* 8192 16Gb chunks < 128Tb*/
	printf("Allocating 64k pages < 128TB \n");
	mmap_chunks_lower(8000, 0);
	printf("Allocating 16M chunks < 128TB \n");
	mmap_chunks_lower(64, MAP_HUGETLB);
	printf("Allocating 16G chunks < 128TB \n");
	mmap_chunks_lower(1, (MAP_HUGETLB | (34 << 26)));

	/* 24576 16Gb chunks in 128Tb - 512Tb*/
	printf("Allocating 64k pages > 128TB \n");
	mmap_chunks_higher(24384, 0);
	printf("Allocating 16M chunks > 128TB \n");
	mmap_chunks_higher(64, MAP_HUGETLB);
	printf("Allocating 16G chunks > 128TB \n");
	mmap_chunks_higher(1, (MAP_HUGETLB | (34 << 26)));
}

void mixed_position_16M()
{
	/* In this function we do try mmap 16M page
	in between 64k and 16G is mapped at last
	in both address ranges*/

	/* 8192 16Gb chunks < 128Tb*/

	printf("Allocating 64k pages < 128TB \n");
	mmap_chunks_lower(4000, 0);
	/* mmap 16M in between 64k */
	printf("Allocating 16M chunks < 128TB \n");
	mmap_chunks_lower(32, MAP_HUGETLB);
	printf("Allocating 64k pages < 128TB \n");
	mmap_chunks_lower(4000, 0);
	printf("Allocating 16M chunks < 128TB \n");
	mmap_chunks_lower(32, MAP_HUGETLB);
	printf("Allocating 16G chunks < 128TB \n");
	mmap_chunks_lower(1, (MAP_HUGETLB | (34 << 26)));

	/* 24576 16Gb chunks in 128Tb - 512Tb*/
	printf("Allocating 64k pages > 128TB \n");
	mmap_chunks_higher(12192, 0);
	/* mmap 16M in between 64k */
	printf("Allocating 16M chunks > 128TB \n");
	mmap_chunks_higher(32, MAP_HUGETLB);
	printf("Allocating 64k pages > 128TB \n");
	mmap_chunks_higher(12192, 0);
	printf("Allocating 16M chunks > 128TB \n");
	mmap_chunks_higher(32, MAP_HUGETLB);
	printf("Allocating 16G chunks > 128TB \n");
	mmap_chunks_higher(1, (MAP_HUGETLB | (34 << 26)));
}

void mixed_position_16G()
{
	/*In this function we do try mmap 16G page
	in between 64k pages and 16M is mapped at last
	in both address ranges */

	/* 8192 16Gb chunks < 128Tb*/

	printf("Allocating 64k pages < 128TB \n");
	mmap_chunks_lower(4000, 0);
	/* mmap 16G in between 64k */
	printf("Allocating 16G chunks < 128TB \n");
	mmap_chunks_lower(1, (MAP_HUGETLB | (34 << 26)));
	printf("Allocating 64k pages < 128TB \n");
	mmap_chunks_lower(4000, 0);
	printf("Allocating 16M chunks < 128TB \n");
	mmap_chunks_lower(64, MAP_HUGETLB);

	/* 24576 16Gb chunks in 128Tb - 512Tb*/
	printf("Allocating 64k pages > 128TB \n");
	mmap_chunks_higher(12192, 0);
	/* mmap 16G in between 64k */
	printf("Allocating 16G chunks > 128TB \n");
	mmap_chunks_higher(1, (MAP_HUGETLB | (34 << 26)));
	printf("Allocating 64k pages > 128TB \n");
	mmap_chunks_higher(12192, 0);
	printf("Allocating 16M chunks > 128TB \n");
	mmap_chunks_higher(64, MAP_HUGETLB);
}

int main(int argc, char *argv[])
{
	int option = 0;
	int scenario = 0, chunks = 0;
	int ret =0 ;
	if (argc < 3){
		printf("Usage <execname> -s <scenario_no> -n <nr_chunks>\n");
		exit(-1);
	}
	while (1) {
		option = getopt(argc, argv,"s:n:");
		if (option != -1){
			switch(option){
				case 's':
					scenario = atoi(optarg);
					break;
				case 'n':
					chunks = atoi(optarg);
					break;
				default:
					printf("Usage <execname> -s <scenario_no> -n <nr_hpages>\n");
					exit(-1);
				}
		}
		else
			break;
	}
	if(chunks)
		printf("%d 16G chunks can be allocated\n", chunks);

	switch (scenario){
	case 1 :
		printf("\nScenario 1 : Alloc default pagesize from 0-512 tb VA with above 128 first\n\n");
		alloc_page_full_reverse();
		break;
	case 2 :
		printf("\nScenario 2 : Alloc default page from 0-512 tb VA\n\n");
		alloc_page_full();
		break;
	case 3 :
		printf("\nScenario 3 : Get hugepage VA Below 128Tb mark \n\n");
		alloc_huge_below_hint(chunks);
		break;
	case 4 :
		printf("\nScenario 4 : Get hugepage VA Above 128Tb mark \n\n");
		alloc_huge_above_hint(chunks);
		break;
	case 5 :
		printf("\nScenario 5 : Get hugepage VA Above and Below 128Tb mark \n\n");
		alloc_huge_reverse(chunks);
		break;
	case 6 :
		printf("\nScenario 6 : Get hugepage VA Below and Above 128Tb mark \n\n");
		alloc_huge(chunks);
		break;
	case 7 :
		printf("\nScenario 7 : Get 16g hugepage VA Below 128T mark\n\n");
		alloc_16g_below_hint(chunks);
		break;
	case 8 :
		printf("\nScenario 8 : Get 16g hugepage VA Above 128T mark\n\n");
		alloc_16g_above_hint(chunks);
		break;
	case 9 :
		printf("\nScenario 9 : Get 16g hugepage VA below and Above 128T mark\n\n");
		alloc_16g(chunks);
		break;
	case 10 :
		printf("\nScenario 10 : Mix of all 64k 16M and 16G pages in VA\n\n");
		fixed_position();
		break;
	case 11 :
		printf("\nScenario 11 : Mix 16M in between 64k and 16G pages in VA\n\n");
		mixed_position_16M();
		break;
	case 12 :
		printf("\nScenario 12 : Mix 16G in between 64k and 16M pages in VA\n\n");
		mixed_position_16G();
		break;
	default:
		printf("Please Provide valid scenario\n");
		break;
	}
	printf("Test Passed!!\n");

	return 0;
}

#include <stdio.h>
#include <sys/mman.h>
#include <linux/mman.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <numa.h>
#include <numaif.h>
#include <hugetlbfs.h>

#define PATTERN		0xff
#define PAGE_SHIFT 12
#define ROUND_PAGES(memsize) ((memsize >> (PAGE_SHIFT)) << PAGE_SHIFT)
#define errmsg(x, ...) fprintf(stderr, x, ##__VA_ARGS__),exit(1)

#define HUGEPAGEFILE  "/sys/devices/system/node/node%d/hugepages/hugepages-%lukB/nr_hugepages"
#define OVERCOMMIT  "/sys/kernel/mm/hugepages/hugepages-%lukB/nr_overcommit_hugepages"
#define SCANTHP "/sys/kernel/mm/transparent_hugepage/khugepaged/scan_sleep_millisecs"

unsigned long total_mem = 0;
int max_node;
int nodes_to_use[2];

/* Does mmap for given size and returns address*/
void *mmap_memory(unsigned long size, int hugepage)
{
	void *mmap_pointer;
	int FLAGS = MAP_PRIVATE | MAP_ANONYMOUS;
        if (hugepage){
		FLAGS |= MAP_HUGETLB;
	}
	mmap_pointer = mmap(NULL, size, PROT_READ | PROT_WRITE, FLAGS, -1, 0);
	if ((!mmap_pointer) && (mmap_pointer != MAP_FAILED)) {
		perror("mmap");
		exit(-1);
	}
	return mmap_pointer;
}

/* Determines the Free memory in the system */ 
void get_total_mem_bytes()
{
	unsigned long vm_size = 0;
        char buff[256];
	FILE *meminfo = fopen("/proc/meminfo", "r");
	if(meminfo == NULL){
		printf("No Meminfo Information\n");
		exit(-1);
	}
	while(fgets(buff, sizeof(buff), meminfo)){
		unsigned long memsize;
		if(sscanf(buff, "MemFree: %lu kB", &memsize) == 1)
			total_mem = memsize * 1024.0;
	}
        if(fclose(meminfo) != 0)
		exit(-1);
}

/* Sets the nodes to be used in test which contains atleast 10% of total memory*/
void get_numa_nodes_to_use(unsigned long memory_to_use)
{
	unsigned long free_node_sizes;
	long node_size;
	int node_iterator, got_nodes = 0;
	/* Get 2 Nodes which contains given memory of total system*/
	for(node_iterator=0; node_iterator <= max_node; node_iterator++){
		node_size = numa_node_size(node_iterator,&free_node_sizes);
		if (node_size != -1)
			if ((free_node_sizes > memory_to_use) && (got_nodes <= 1))
				nodes_to_use[got_nodes++] = node_iterator;
	}
	/* Verify if we got 2 nodes to use */
	if (got_nodes == 2)
		printf("Nodes used in test %d %d \n", nodes_to_use[0], nodes_to_use[1]);
	else{
		printf("10 percent of total memory is not found in 2 nodes\n");
		exit(0);
	}
}

/* Returns number of pages used in numanode 'node' searched by a addr*/
unsigned long get_npages_from_numa_maps(void *addr, int node)
{
	int pid;
	char numa_maps_file[32], line[1024], addr_in_string[64], node_info[16], *ptr_addr_in_string, *string_ptr, *temp_str_ptr;
	unsigned long npages = 0;

	ptr_addr_in_string = addr_in_string;
	pid = getpid();
	snprintf(addr_in_string, sizeof(addr_in_string), "%p", addr);
	snprintf(numa_maps_file, sizeof(numa_maps_file), "/proc/%d/numa_maps", pid);
	snprintf(node_info, sizeof(node_info), "N%d=", node);

	/* Incremented 2 bytes to avoid 0x */
	ptr_addr_in_string += 2;
	FILE *numa_maps = fopen(numa_maps_file,"r");
	if (numa_maps ==NULL){
		exit(-1);
	}
	/* Parse each line from numa maps to get the no of pages used by the addr
	 * in the corresponding node */
	while(fgets(line, sizeof(line), numa_maps)){
		if (strstr(line, ptr_addr_in_string) != NULL){
			string_ptr = strtok(line, " ");
			while(string_ptr != NULL){
				temp_str_ptr = string_ptr;
				if(strstr(temp_str_ptr,node_info)){
					npages = strtoul((string_ptr + strlen(node_info)), NULL, 0);
					printf("%lu pages allocated in Node %d\n", npages, node);
					return npages;
				}
				string_ptr = strtok(NULL, " ");
			}
		}
	}
	return -1;
}

void lock_mem(void *mmap_pointer, unsigned long size)
{
	int lock;
	lock = mlock(mmap_pointer, size);
	if (lock != 0) {
		perror("lock");
		exit(-1);
	}
}

void unlock_mem(void *mmap_pointer, unsigned long memory)
{
	int unlock;
	unlock = munlock(mmap_pointer, memory);
	if (unlock != 0) {
		perror("munlock");
		exit(-1);
	}
}

/* Read and verify the pattern from given address for given size */
void read_memory(char *addr, int pattern, unsigned long size, unsigned long pagesize)
{
	unsigned long iterator;
	unsigned long read = 0;
	char val;
	for(iterator=0; iterator < size; iterator+=pagesize){
		val = addr[iterator];
		if (val != pattern) {
			printf("Iterator %lu\n", iterator);
			printf("Correctness failed at loop read\n"
                               "PATTERN MISMATCH OCCURED \n");
			exit(-1);
		}
		read++;
	}
	printf("%lu pages read and verified\n", read);
}

void write_read_pattern_numa_migration(unsigned long unit_memory, unsigned long page_size, int chunks, int thp, int hugepage, int overcommit)
{
        char *mmap_pointer[chunks], node0_buf[100], node1_buf[100], over_buf[100], scan_buf[100];
        unsigned long memory_to_use, npages;
        int i, j;
	FILE *fp1, *fp2, *fp3, *fp4;
	if(numa_available() == -1){
		printf("Numa library is not present");
		exit(-1);
	}
	memory_to_use = unit_memory / chunks;
	max_node = numa_max_node();
	get_numa_nodes_to_use(memory_to_use);
	memory_to_use = ROUND_PAGES(memory_to_use);
	printf("\nScenario : Numa Page Migration \n\n");
	printf("Using %lu Bytes for the test\n\n", unit_memory);
        if (thp){
		/* Make sure THP is enabled (set to "madvise" or "always" */
                printf("Making *khugepaged* aggressive\n");
		snprintf(scan_buf, sizeof scan_buf, SCANTHP);
		fp4 = fopen(scan_buf, "w");
		fprintf(fp4, "%d", 0);
                fclose (fp4);
	}
	for(i = 0; i < chunks; i++ ){
		unsigned long mask;
		unsigned long npages = 0, pages_numa_map = 0;
		int mbind_status, *status, *nodes;
	        void **addrs;
		/* Determine No of Pages */
		npages = memory_to_use / page_size;
		if (memory_to_use % page_size)
			npages = npages + 1;
		memory_to_use = npages * page_size;
		printf("\nChunk %d Memory %lu Bytes\n", i + 1, memory_to_use);
		printf("\nNumber of pages: %lu Page Size: %lu\n\n", npages, page_size);
		if (hugepage){
			snprintf(node0_buf, sizeof node0_buf, HUGEPAGEFILE, nodes_to_use[0], page_size / 1024);
		        fp1 = fopen(node0_buf, "w");
			snprintf(node1_buf, sizeof node1_buf, HUGEPAGEFILE, nodes_to_use[1], page_size / 1024);
			fp2 = fopen(node1_buf, "w");
			if (overcommit){
                		snprintf(over_buf, sizeof over_buf, OVERCOMMIT, page_size / 1024);
				fp3 = fopen(over_buf, "w");
			}
		        fprintf(fp1, "%lu", npages);
			fclose (fp1);
		}
		mmap_pointer[i] = mmap_memory(memory_to_use, hugepage);

        	if (thp){
			/* Block for THP */
	        	posix_memalign(mmap_pointer[i], memory_to_use, page_size);
			if( madvise(mmap_pointer[i], memory_to_use, MADV_HUGEPAGE) ){
                		perror("madvise");
                		exit(1);
        		}
		}
		/* Set nodemask for node 1 */
		mask = 0;
		mask |= 1UL << nodes_to_use[0];
        	/* Allocate in Node1 via mbind*/
	        printf("\nMapped memory at %p %lu \n", mmap_pointer[i], memory_to_use);
	        mbind_status = mbind(mmap_pointer[i], memory_to_use, MPOL_BIND, &mask, nodes_to_use[0] + 2, NULL);
        	if(mbind_status){
                	perror("mbind() fails");
	                exit(-1);
       		}

		/* Write Patterns in Node 1 */
		printf("Lock all mapped memory \n");
		lock_mem(mmap_pointer[i], memory_to_use);
		printf("Write into mapped memory \n");
	        memset(mmap_pointer[i], PATTERN, memory_to_use);
		pages_numa_map = get_npages_from_numa_maps(mmap_pointer[i], nodes_to_use[0]);
	        printf("Unlock all mapped memory \n");
		unlock_mem(mmap_pointer[i], memory_to_use);
		if((pages_numa_map == npages) && (pages_numa_map != -1)){
			printf("All pages have been allocated in node %d \n", nodes_to_use[0]);
		}else{
			printf("Pages are not allocated in node %d\n", nodes_to_use[0]);
			exit(-1);
		}
	
		if (hugepage){
			if(!overcommit){
		        	fprintf(fp2, "%lu", npages);
			}
			else{
				printf("Writing to overcommit memory for hugepages\n");
				fprintf(fp2, "%lu", (npages / 2) + 1);
				fprintf(fp3, "%lu", (npages / 2) + 1);
				fclose (fp3);
			}
			fclose (fp2);
		}
	        printf("\nMove pages from Node %d to Node %d \n",nodes_to_use[0], nodes_to_use[1]);
	        /* Move all pages to from node1 to node 2 via mbind */
	        addrs  = malloc(sizeof(char *) * npages + 1);
	        status = malloc(sizeof(char *) * npages + 1);
	        nodes  = malloc(sizeof(char *) * npages + 1);
	        for (j = 0; j < npages; j++) {
	        	addrs[j] = mmap_pointer[i] + j * page_size;
	                nodes[j] = nodes_to_use[1];
	                status[j] = 0;
	        }
		mbind_status = move_pages(0, npages, addrs, nodes, status, MPOL_MF_MOVE_ALL); 
		if(mbind_status){
	                perror("mbind() fails");
	                exit(-1);
	        }
		/* Read Patterns from Node 2 */
	        printf("Lock all mapped memory %p till\n", mmap_pointer[i]);
		lock_mem(mmap_pointer[i], memory_to_use);
	        printf("Reading from memory\n");
	        read_memory(mmap_pointer[i], PATTERN, memory_to_use, page_size);
		pages_numa_map = get_npages_from_numa_maps(mmap_pointer[i], nodes_to_use[1]);
		/* Check all pages are allocated in node we want */
		if((pages_numa_map == npages) && (pages_numa_map != -1)){
			printf("All pages have been allocated in node %d \n", nodes_to_use[1]);
		}else{
			printf("All pages are not allocated in node %d\n", nodes_to_use[1]);
			exit(-1);
		}
	       	printf("Unlock all mapped memory \n");
	        unlock_mem(mmap_pointer[i], memory_to_use);
	        printf("Unmapping Memory\n");
	        munmap(mmap_pointer[i], memory_to_use);
		if (hugepage){
			fp1 = fopen(node0_buf, "w");
			fp2 = fopen(node1_buf, "w");
		        fprintf(fp1, "%d", 0);
			fprintf(fp2, "%d", 0);
			fclose (fp1);
			fclose (fp2);
                	if (overcommit){
				fp3 = fopen(over_buf, "w");
				fprintf(fp3, "%d", 0);
				fclose (fp3);
			}
		}
		/* TODO: Reset all files with default values */
		free(addrs);
		free(status);
		free(nodes);
        }
	if (thp){
		printf("Re-setting scan seconds\n");
		fp4 = fopen(scan_buf, "w");
		fprintf(fp4, "%d", 1000);
                fclose (fp4);
	}
}

int main(int argc, char *argv[])
{
	int c;
	get_total_mem_bytes();
	printf("Total memory size %lu bytes \n", total_mem);
	int chunks = 1, hugepage = 0, overcommit = 0, thp = 0;
	unsigned long memory, pagesize;

	pagesize = (unsigned long)getpagesize();
	/* Using 10% of system memory */
        memory = (total_mem * 10) / 100;

        /* TODO: get no.of pages and work with those instead of memory*/
        while ((c = getopt(argc, argv, "n:oth")) != -1) {
                switch(c) {
                case 'n':
			chunks = strtoul(optarg, NULL, 10);
                        break;
                case 'o':
			overcommit = 1;
                        break;
                case 't':
			thp = 1;
                        break;
                case 'h':
			hugepage = 1;
			pagesize = gethugepagesize();
			/* Using 1% of system memory for hugepages*/
        		memory = (total_mem) / 100;
                        break;
                default:
                        errmsg("%s [-n <no-of-chunks] [-t fot THP] [-o for hugepage-overcommit] [-h for hugepage]\n", argv[0]);
                        break;
                }
        }
	if ((hugepage && thp) || (thp && overcommit))
		errmsg("Please use either Hugepage or THP\n");

	write_read_pattern_numa_migration(memory, pagesize, chunks, thp, hugepage, overcommit);
	printf("\nTest Passed!!\n");

	return 0;
}


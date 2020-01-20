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
 * Copyright: 2020 IBM
 * Author Harish<harish@linux.vnet.ibm.com>
 */


#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/errno.h>

#define PAGE_SIZE (64*1024)
#define MAP_SYNC        0x80000         /* perform synchronous page faults for the mapping */
#define MAP_SHARED_VALIDATE 0x03        /* share + validate extension flags */

void error(char *s, int eno)
{
        printf("%s with %s\n", s, strerror(eno));
        exit(1);
}

int main(int argc, char *argv[])
{
        int fd;
        void *a;

        fd = open(argv[1], O_RDWR | O_CREAT);
        if (fd < 0)
                error("Failed to open file", errno);
        a = mmap(NULL, PAGE_SIZE, PROT_READ|PROT_WRITE,
                 MAP_SHARED_VALIDATE | MAP_SYNC , fd, 0);

        if ((unsigned long)a == -1)
                error("Failed to mmap ", errno);

	/* faulting map_sync region */
        *(int *)a = 10;
        return 0;
}

/*
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *
 * See LICENSE for more details.
 *
 * Copyright: 2025 IBM
 * Author: SACHIN P B  <sachinpb@linux.ibm.com>
*/

#define _GNU_SOURCE
#include <linux/perf_event.h>
#include <linux/hw_breakpoint.h>
#include <sys/ioctl.h>
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/syscall.h>

#define HW_BREAKPOINT_LEN_512 512

static char c[1024];
static void multi_dawr_workload(void)
{
    volatile char *ptr = c + 8;
    ptr[0] = 0xAA;
    ptr[511] = 0xBB;
}

static int perf_process_event_open(int bp_type, __u64 addr, int len)
{
    struct perf_event_attr attr;
    memset(&attr, 0, sizeof(struct perf_event_attr));
    attr.type = PERF_TYPE_BREAKPOINT;
    attr.size = sizeof(struct perf_event_attr);
    attr.config = 0;
    attr.bp_type = bp_type;
    attr.bp_addr = addr;
    attr.bp_len = len;

    return syscall(__NR_perf_event_open, &attr, 0, -1, -1, 0);
}

int main()
{
    unsigned long long breaks = 0;
    int fd;
    __u64 addr = (__u64)&c + 8;
    size_t res;

    fd = perf_process_event_open(HW_BREAKPOINT_RW, addr, HW_BREAKPOINT_LEN_512);
    if (fd < 0) {
        perror("perf_process_event_open");
        return 1;
    }

    ioctl(fd, PERF_EVENT_IOC_RESET, 0);
    ioctl(fd, PERF_EVENT_IOC_ENABLE, 0);
    multi_dawr_workload();
    ioctl(fd, PERF_EVENT_IOC_DISABLE, 0);

    res = read(fd, &breaks, sizeof(breaks));
    if (res != sizeof(unsigned long long)) {
        perror("read failed");
        close(fd);
        return 1;
    }

    close(fd);

    if (breaks != 2) {
        printf("FAILED: unaligned_512bytes: %llu != 2\n", breaks);
        return 1;
    }

    printf("TEST Boundary check PASSED: unaligned_512bytes\n");
    return 0;
}

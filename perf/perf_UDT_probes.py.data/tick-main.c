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
 * Copyright: 2019 IBM
 * Author: Naveen kumar T <naveet89@in.ibm.com>
 */


#include <stdio.h>
#include <unistd.h>
#include "tick-dtrace.h"

int
main(int argc, char *argv[])
{
        int i;

        for (i = 0; i < 5; i++) {
                DTRACE_PROBE1(tick, loop1, i);
                if (TICK_LOOP2_ENABLED()) {
                        DTRACE_PROBE1(tick, loop2, i);
                }
                printf("hi: %d\n", i);
                sleep(1);
        }

        return (0);
}

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

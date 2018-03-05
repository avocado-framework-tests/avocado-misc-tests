#include <stdio.h>
#include <sys/platform/ppc.h>

int main(int argc, char** argv)
{
	uint64_t tb = __ppc_get_timebase();
	printf("timebase = %lx\n", tb);
	sleep(15);
	tb = __ppc_get_timebase();
	printf("timebase = %lx\n", tb);

	return 0;
}

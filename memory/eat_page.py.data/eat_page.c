#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <unistd.h>
#include <string.h>
#include <setjmp.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>

static sigjmp_buf envjmp;

static void write_oom_adjustment(const char *path, const char *str)
{
	int fd;

	if ((fd = open(path, O_WRONLY)) >= 0) {
		ssize_t ret = write(fd, str, strlen(str));
		(void)ret;
		(void)close(fd);
	}
}

static inline void set_oomadjustment(void)
{
	const bool high_priv = (getuid() == 0) && (geteuid() == 0);

	write_oom_adjustment("/proc/self/oom_adj", high_priv ? "-17" : "-16");
	write_oom_adjustment("/proc/self/oom_score_adj", high_priv ? "-1000" : "0");
}

static void handler_sigbus(int dummy)
{
	(void)dummy;

	siglongjmp(envjmp, 1);
}

int main(void)
{
	static struct sigaction new_action;
	size_t page_size = sysconf(_SC_PAGESIZE);
	size_t sz = page_size * 4;

	page_size = (page_size <= 0) ? 4096: page_size;

	if (geteuid()) {
		fprintf(stderr, "eat_page must be run with root privileges\n");
		exit(EXIT_FAILURE);
	}

	if (sigsetjmp(envjmp, 1))
		return EXIT_FAILURE;

	new_action.sa_handler = handler_sigbus;
	new_action.sa_flags = 0;
	if (sigaction(SIGBUS, &new_action, NULL) < 0)
		return EXIT_FAILURE;
	new_action.sa_handler = SIG_IGN;
	if (sigaction(SIGCHLD, &new_action, NULL) < 0)
		return EXIT_FAILURE;

	printf("eat_page will now mark pages as poisoned and consume memory..\n");

	set_oomadjustment();
	(void)sync();
	(void)setsid();
	(void)close(0);
	(void)close(1);
	(void)close(2);
	
	for (;;) {
		void *buf = mmap(NULL, sz, PROT_READ,
				MAP_ANONYMOUS | MAP_SHARED, -1, 0);
		if (buf == MAP_FAILED) {
			if (sz > page_size)
				sz >>= 1;
			continue;
		}
		if (sigsetjmp(envjmp, 1)) {
			(void)munmap((void *)buf, sz);
			continue;
		}
		(void)madvise(buf, sz, MADV_HWPOISON);
		(void)munmap((void *)buf, sz);
	}
	return EXIT_SUCCESS;
}

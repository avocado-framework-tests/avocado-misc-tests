/*
 * Wait System Call Stressor
 *
 * Copyright: 2024 IBM
 * Author: Aboorva Devarajan <aboorvad@linux.ibm.com>
 *
 * This program creates multiple processes that stress the wait system call
 * by continuously sending SIGSTOP/SIGCONT signals, exercising scheduler
 * load balancing functionality.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <errno.h>

#define TIMEOUT_INTERVAL (0.0025)
#define ONE_MILLIONTH (1.0E-6)
#define PROCESS_COUNT 100

pid_t spawnNewProcess(void (*func)(const pid_t pid), const pid_t pid_arg) {
	pid_t pid = fork();
	if (pid == 0) {
		func(pid_arg);
		_exit(EXIT_SUCCESS);
	}
	return pid;
}

void killerProcess(const pid_t pid) {
	pid_t parentPid = getppid();
	while (1) {
		//printf("Killer process with PID: %d is stopping process with PID: %d\n", getpid(), pid);
		kill(pid, SIGSTOP);
		sleep(0);
		kill(pid, SIGCONT);
	}
	printf("Killer process with PID: %d is sending SIGALRM to its parent\n", getpid());
	kill(getppid(), SIGALRM);
	_exit(EXIT_SUCCESS);
}

void runnerProcess(const pid_t pid) {
	(void)pid;
	while (1) {
		//printf("Runner process with PID: %d is pausing\n", getpid());
		pause();
	}
	printf("Runner process with PID: %d is sending SIGALRM to its parent\n", getpid());
	kill(getppid(), SIGALRM);
	_exit(EXIT_SUCCESS);
}

int stressWaitSystemCall(void) {
	int ret = EXIT_SUCCESS;
	pid_t runnerPid, killerPid, waitReturn;
	int options = WUNTRACED | WCONTINUED;
	runnerPid = spawnNewProcess(runnerProcess, 0);
	if (runnerPid < 0) {
		fprintf(stderr, "Error spawning runner process: %s\n", strerror(errno));
		return EXIT_FAILURE;
	}
	killerPid = spawnNewProcess(killerProcess, runnerPid);
	if (killerPid < 0) {
		fprintf(stderr, "Error spawning killer process: %s\n", strerror(errno));
		ret = EXIT_FAILURE;
	}
	do {
		int status;
		waitReturn = waitpid(runnerPid, &status, options);
		if ((waitReturn < 0) && (errno != EINTR) && (errno != ECHILD)) {
			break;
		}
		waitReturn = wait(&status);
		if ((waitReturn < 0) && (errno != EINTR) && (errno != ECHILD)) {
			break;
		}
	} while (1);
	return ret;
}

int main(void) {
	for (int i = 0; i < PROCESS_COUNT; i++) {
		pid_t pid = fork();
		if (pid == -1) {
			perror("fork");
			exit(EXIT_FAILURE);
		} else if (pid == 0) {
			printf("Main process has spawned a child with PID: %d\n", getpid());
			stressWaitSystemCall();
			exit(EXIT_SUCCESS);
		}
	}
	for (int i = 0; i < PROCESS_COUNT; i++) {
		printf("Main process is waiting for all children to exit\n");
		wait(NULL);
	}
	printf("All child processes have exited\n");
	return 0;
}


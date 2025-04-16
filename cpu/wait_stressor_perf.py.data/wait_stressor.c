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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <errno.h>

#define PROCESS_COUNT 100

pid_t spawnNewProcess(void (*func)(const pid_t pid), const pid_t pid_arg) {
	pid_t pid = fork();
	if (pid == -1) {
		/* Fork failed */
		return -1;
	} else if (pid == 0) {
		/* Child process */
		func(pid_arg);
		_exit(EXIT_SUCCESS);
	}
	/* Parent process - return child PID */
	return pid;
}

void killerProcess(const pid_t pid) {
	while (1) {
		kill(pid, SIGSTOP);
		sleep(0);
		kill(pid, SIGCONT);
	}
}

void runnerProcess(const pid_t pid) {
	(void)pid;
	while (1) {
		pause();
	}
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
		kill(runnerPid, SIGKILL);
		waitpid(runnerPid, NULL, 0);
		return EXIT_FAILURE;
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
	
	/* Cleanup: Kill both processes and wait for them */
	kill(killerPid, SIGKILL);
	kill(runnerPid, SIGKILL);
	waitpid(killerPid, NULL, 0);
	waitpid(runnerPid, NULL, 0);
	
	return ret;
}

int main(void) {
	for (int i = 0; i < PROCESS_COUNT; i++) {
		pid_t pid = fork();
		if (pid == -1) {
			perror("fork");
			exit(EXIT_FAILURE);
		} else if (pid == 0) {
			stressWaitSystemCall();
			exit(EXIT_SUCCESS);
		}
	}
	for (int i = 0; i < PROCESS_COUNT; i++) {
		wait(NULL);
	}
	printf("All %d child processes have exited\n", PROCESS_COUNT);
	return 0;
}

Performance Testing with perf
*****************************

This test case includes performance benchmarks using the perf tool to measure and analyze scheduling performance. Below are the commands used to perform these benchmarks along with their descriptions.

Command 1: perf stat -r 5 -a perf bench sched pipe -l 10000000
*********
This command measures the performance of the sched pipe benchmark with a specified loop count.

Prameter details:
****************
-> perf stat: Collects and displays performance statistics.
-> -r 5: Runs the benchmark 5 times and averages the results.
-> -a: Collects data system-wide.
-> perf bench sched pipe -l 10000000: Runs the scheduling pipe benchmark with 10,000,000 iterations.

This command provides an average performance measurement over 5 runs, giving a more stable and 
reliable set of statistics for the scheduling pipe benchmark with a high loop count.

Command 2: perf stat -n -r 5 perf bench sched pipe
*********
This command also measures the performance of the sched pipe benchmark but with a default loop count.

Prameter details:
****************
-> perf stat: Collects and displays performance statistics.
-> -n: Ensures that the results include a notation of how many times each event was recorded.
-> -r 5: Runs the benchmark 5 times and averages the results.
-> perf bench sched pipe: Runs the scheduling pipe benchmark with the default number of iterations.

This command is useful for obtaining a quick performance snapshot with the default settings, averaged over 5 runs for consistency.

Understanding the Output:
************************
The output will include various performance metrics such as the number of context switches, CPU cycles, instructions per cycle, and more.
By running these benchmarks multiple times, we can ensure that the results are averaged, providing a more accurate representation of the system's performance.

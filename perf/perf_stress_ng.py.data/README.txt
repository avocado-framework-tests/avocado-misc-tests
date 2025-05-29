Description:
This test is to compare CPU load percentage from vmstat and perf
command by running stress-ng in background.
The test collects vmstat and perf record data with CPU load
10, 50 and 80 by running it for 5 iterations.

Steps followed:
Run stress-ng in background with CPU load 10, 50 and 80.
Run perf record to collect CPU load for 5 iterations.
Run vmstat to collect CPU load for 5 iterations.
Compare both results.

Pre-requisite:
1. Install psutil using pip
   # pip3 install psutil
2. Install perf, gcc and stress-ng packages

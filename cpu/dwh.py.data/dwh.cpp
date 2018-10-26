/*
    dwh is a test program to run a task with large (or small) numbers of
    pthreads, including worker and dedicated I/O threads. It's purpose
    is to generate heavy workloads for a single task. Combining memory
    alloc/read/write/free, CPU arithmetic and lock controlled random file
    async I/O. During which it will set the task signal mask repeatedly
    without changing the value (the goal was to test for a problem case
    caused by wasted effort setting the signal mask resulting in system
    failure). Multiple instances can be run at the same time on the same
    host. I/O is with shared lock reads and exclusive lock writes.
    Regardless of the intended purpose the signal mask action could be
    replaced (case 5 and case 6 in WorkerThreadStart() with something
    else to perform during configurable muti-threaded, async-I/O load
    using the source as one example of pthreads, worker & I/O thread,
    64-bit async-I/O with r/w file locking, in a single task.
    Copyright (C) 2018  David A. Mair <dmair@suse.com


    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.


    Compile example on linux:

        g++ -O3 -D_FILE_OFFSET_BITS=64 -Wall -Werror -pthread -lrt -o dwh dwh.cpp

    Then the output file dwh can be run with --help for information.

    Example usage:

        ./dwh --minthreads 500 --maxthreads 575 --iothreads 50 --maxmem 1G
            --maxiosize 1M --shortthreads --time 200 dwh.test

    That command-line will run dwh with the following configuration:

    At least 500 threads (--minthreads)
    Limit total threads to no more than 575 at any time (--maxthreads)
        If no value is specified for --maxthreads the default is the
        --minthreads value
    Use 50 threads for dedicated I/O operations (--iothreads)
        These are included in the instantaneous thread count limit of
        --maxthreads
    Don't use more than 1GiB of memory for processing (--maxmem)
    Perform test I/O using blocks no larger than 1MiB (--maxiosize)
        Consider that the sum of memory used by all threads is the
        limit imposed by --maxmem. Threads only use one block at a time
        so it has to be possible for the number of threads multiplied by
        the --maxiosize value to be less than or equal to the --maxmem
        value at all times.
    Allow worker threads to end and new ones to be created (--shortthreads)
        At any instant the absolute thread count may be less than --minthreads
        Without this or by using --longthreads all started threads run until
        program exit (or until they fail on their own)
    Run the test case for 200 seconds (--time)
        Initialization time is not included and may take several seconds
        There is no live output when the test is running and succeeding
    The last argument shown is the file to use for performing the I/O
        Don't run multiple instances with the same test file, each instance
        creates an empty file and pre-populates it and the locking is per-
        task only.

    Also:

    To choose between setting the signal mask using pthreads or libc use
    --sigmaskthread or --sigmasktask respectively (the default is pthreads)

    To choose your own maximum size for the test data file use --maxfilesize
    with an argument specifying how large, e.g. --maxfilesize 10G; or
    --maxfilesize 500M; etc.

    While settings like 500 threads are realistic test cases for a system
    with 8 processors the number should at least exceed the number of CPUs
    on the host system for the test case to be functional and should
    probably be significantly larger (though CPUs * 500/8 does not indicate
    a ratio model for all environments). It will require some experimentation
    while monitoring actual host processor loading.

    The default timeout for individual I/O operations is 3s but can be set to
    a preferred number of seconds using --iotimeout <num> where <num> is the
    required I/O timeout in seconds.

    Note that sending a SIGUSR1 to a running instance will cause it to end
    on demand and clean-up as-in a normal exit, e.g.:

    ps -A | grep dwh
    14727 ?        00:00:00 dwh
    kill -USR1 14727

    Sending a SIGKILL will cause it to be terminated without cleanup. That
    should, at worst, only leave the test file undeleted with no other
    waste.

    It should also respond to Ctrl-C to exit if it has exceeded the --time
    argument by an amount that suggests failure.

*/

#include <stdbool.h>
#include <ctype.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <cstdlib>
#include <string>
#include <getopt.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <aio.h>
#include <pthread.h>
#include <semaphore.h>
#include <signal.h>
#include <atomic>
#include <time.h>

/* Set true to get extra diagnostic information on program operation while
 * running. It results in a lot of output so if interested in viewing only
 * a limited number of diagnostic oputput cases change their conditional to
 * if (!Diagnose) for the duration of the diagnosis to only see those
 * diagnostic messages while running then restore the conditionals to
 * if (Diagnose) once resolved. */
bool Diagnose = false;

/* Global "switch" to make all threads end themselves */
bool EndAllThreads = false;

/* Global "switch" to stop I/O being queued (but letting pending cases finish) */
bool EndAllIO = false;

/* Global number of active pthreads */
std::atomic<unsigned int> nThreads(0);
std::atomic<unsigned int> nIOThreads(0);
std::atomic<int> nIOTasks(0);
std::atomic<int> nQueuedIOTasks(0);
std::atomic<int> nTriedIOTasks(0);
std::atomic<unsigned int> nPeakThreads(0);
std::atomic<unsigned int> nTotalThreads(0);
std::atomic<unsigned int> nTotalIOThreads(0);
std::atomic<int> threadNum(0);

/* Global thread info */
struct thread_info *iotinfo = NULL;
struct thread_info *wktinfo = NULL;

/* Global access control for wktinfo */
pthread_mutex_t wktilock;

/* Global thread limits */
unsigned int maxthreads = 0;
unsigned int minthreads = 0;
unsigned int iothreads = 0;

/* Global work done info */
std::atomic<unsigned long long> memUsed(0);
std::atomic<unsigned long long> totalRead(0);
std::atomic<unsigned long long> totalWrite(0);
std::atomic<unsigned long long> totalTriedIORead(0);
std::atomic<unsigned long long> totalTriedIOWrite(0);
std::atomic<unsigned long long> totalIORead(0);
std::atomic<unsigned long long> totalIOWrite(0);
std::atomic<unsigned long long> pendingIOReads(0);
std::atomic<unsigned long long> pendingIOWrites(0);
std::atomic<unsigned long long> pendingIODone(0);

/* Global runtime limit (seconds) */
unsigned int maxruntime = 20;

/* Global memory limits */
unsigned long long maxMem = 0;
unsigned long long maxIOSize = 1 * 1024 * 1024;

/* Global signal mask */
static  sigset_t sigmask;
std::atomic<int> sigStop(0);
std::atomic<int> nSigMaskSets(0);
std::atomic<unsigned long long> totalTriedSigWaits(0);
std::atomic<unsigned long long> totalLongSigWaits(0);
std::atomic<unsigned long long> totalShortSigWaits(0);
std::atomic<double> elapsedSigWaits(0.0);
std::atomic<double> elapsedGoodSigWaits(0.0);

/* Did we show help */
bool helpShown = false;

/* Flag set by ‘--verbose’ (assume not verbose) */
static int verbose_flag = 0;

/* Flag set by '--shortthreads' (assume threads end and new ones replace them) */
static int short_threads = 1;
#define RESTART_SCOPE (RAND_MAX / 800)

/* Flag set by '--sigmasktask' (assume not, i.e. --sigmaskthread) */
static int sigmask_threads = 1;

/* I/O filename/stream/size/timeouts/failures */
#define DEFAULT_ASYNC_IO_TIMEOUT ((time_t)3)
time_t ioTimeout = DEFAULT_ASYNC_IO_TIMEOUT;
unsigned long long maxFileSize = 0;
unsigned long long fileSize = 0;
std::atomic<unsigned long long> failedReads(0);
std::atomic<unsigned long long> failedWrites(0);
std::atomic<unsigned long long> incompleteReads(0);
std::atomic<unsigned long long> incompleteWrites(0);
std::atomic<unsigned long long> timeoutReads(0);
std::atomic<unsigned long long> timeoutWrites(0);
std::atomic<unsigned long long> underRead(0);
std::atomic<unsigned long long> underWrite(0);
std::string ioFilename;
FILE *ioReadStream = NULL;
FILE *ioWriteStream = NULL;

/* Global access control for read/write queues */
pthread_mutex_t iordlock;
pthread_mutex_t iowrlock;
pthread_mutex_t iodnlock;
pthread_mutex_t iorsklock;
pthread_mutex_t iowsklock;

/* Flags for initialized objects */
#define INIT_OBJ_NONE 0
#define INIT_WKTILOCK 1
#define INIT_IORDLOCK 2
#define INIT_IOWRLOCK 4
#define INIT_IODNLOCK 8
#define INIT_IORSKLOCK 16
#define INIT_IOWSKLOCK 32
unsigned int initObjects = INIT_OBJ_NONE;

struct option long_options[] = {
        {"verbose", no_argument, &verbose_flag, 1},
        {"brief", no_argument, &verbose_flag, 0},
        {"shortthreads", no_argument, &short_threads, 1},
        {"longthreads", no_argument, &short_threads, 0},
        {"sigmaskthread", no_argument, &sigmask_threads, 1},
        {"sigmasktask", no_argument, &sigmask_threads, 0},
        {"help", no_argument, 0, 'h'},
        {"iothreads", required_argument, 0, 'i'},
        {"maxmem", required_argument, 0, 'm'},
        {"minthreads", required_argument, 0, 'n'},
        {"iotimeout", required_argument, 0, 'o'},
        {"maxthreads", required_argument, 0, 'x'},
        {"maxiosize", required_argument, 0, 'S'},
        {"maxfilesize", required_argument, 0, 'F'},
        {"time", required_argument, 0, 't'},
        {0, 0, 0, 0}
    };

struct thread_info {    /* Used as argument to thread_start() */
           pthread_t thread_id;        /* ID returned by pthread_create() */
           int       thread_num;       /* Application-defined thread # */
           sem_t     my_sem;           /* Application-defined semaphore */
           int       my_fd;            /* Thread specific file descriptor */
           char     *argv_string;      /* From command-line argument */
    };

struct io_queue_node {
        struct io_queue_node *prev;
        struct io_queue_node *next;
        sem_t *my_sem;              /* Application-defined semaphore */
        int my_fd;                  /* Thread specific file descriptor */
        void *io_buffer;
        size_t io_len;
        size_t io_done;
    };

struct io_queue_node *io_readQHead = NULL;
struct io_queue_node *io_readQTail = NULL;
struct io_queue_node *io_writeQHead = NULL;
struct io_queue_node *io_writeQTail = NULL;
struct io_queue_node *io_doneQHead = NULL;
struct io_queue_node *io_doneQTail = NULL;

/* Prototypes */
time_t GetElapsedFrom(time_t someTime);

void ShowHelp(void)
{
    /* Help must exist alone */
    if (minthreads || maxthreads || iothreads || verbose_flag)
    {
        puts("-h/--help must be the only argument");
        return;
    }

    putchar('\n');
    puts("Usage: dwh --minthreads <num> [OPTION]... file");
    puts("Attempt to simulate high thread count single task asynchronous I/O task.");
    putchar('\n');
    puts("  -n, --minthreads <num>  Set minimum number of threads to use (Mandatory)");
    puts("  -x, --maxthreads <num>  Set maximum number of threads to use (defaults to min)");
    puts("  -i, --iothreads <num>   Set number of dedicated I/O threads to use (default 0)");
    puts("      --shortthreads      Let threads exit and new ones start");
    puts("      --longthreads       All threads run to program exit");
    puts("      --sigmaskthread     Use pthreads library to set signal mask");
    puts("      --sigmasktask       Use libc to set signal mask");
    puts("  -m, --maxmem <num>      Set a maximum amount of memory to use");
    puts("  -F, --maxfilesize <num> Limit the maximum size of the test file");
    puts("                          (defaults to 2 x maxmem)");
    puts("  -S, --maxiosize <num>   Set a maximum memory to use for I/O tasks (default 1M)");
    puts("  -o, --iotimeout <num>   Set a time limit for I/O reads and writes (default 3s)");
    puts("  -t, --time <num>        How long (seconds) program should run for (default 20)");
    puts("      --verbose           Show more information while running");
    puts("      --brief             Show limited information while running");
    puts("  --help                  Show program information");
    putchar('\n');
    puts("If iothreads is not specified or zero is used then I/O is not performed.");
    putchar('\n');
    helpShown = true;
}

/* calloc that adds space to store the allocation size so that the total can
 * be summed on alloc and each free can subtract the original alloc size */
void *CountingCalloc(size_t nmem, size_t size)
{
    unsigned long long sz;
    void *mem;
    unsigned long long *pSz;

    sz = nmem * size;
    memUsed += sz;
    if ((maxMem > 0) && (memUsed > maxMem))
    {
        memUsed -= sz;
        return NULL;
    }
    mem = calloc(1, sz + sizeof(sz));
    if (mem == NULL)
    {
        memUsed -= sz;
        return NULL;
    }
    pSz = (unsigned long long *)mem;
    pSz[0] = sz;

    if (Diagnose)
        printf("Counting calloc of %p, size %llu, showing %p\n", mem, sz, &pSz[1]);

    return (void *)&pSz[1];
}

/* free for the calloc that stores the alloc size */
void CountingFree(void *mem)
{
    unsigned long long *pSz;

    if (Diagnose)
        printf("Counting free of %p\n", mem);
    if (mem != NULL)
    {
        pSz = (unsigned long long *)((unsigned long long)mem - sizeof(unsigned long long));
        if (Diagnose)
            printf("Accessing %p for size (%llu)\n", pSz, pSz[0]);
        memUsed -= pSz[0];
        free(pSz);
    }
}

/* Random integer generator with a maximum limit. To be used for selecting
 * an operation (activity) to perform in a set of capabilities */
int getActivity(unsigned nActivities, int noise)
{
    unsigned s;
    time_t tv;

    tv = time(NULL);
    if (tv == ((time_t)-1))
    {
        return -1;
    }
    s = (unsigned)noise + (unsigned)tv;
    srand(s);

    return rand() % nActivities;
}

/* Get an unsigned int from a string text */
unsigned int strtoui(const char *s)
{
    unsigned long lresult = std::stoul(s, 0, 10);
    unsigned int result = lresult;

    if (result != lresult)
        result = 0;

    return result;
}

/* Given a memory size in text that can include a scale initial (k, M, G)
 *  return the numeric value as an unsigned long long */
unsigned long long memsztoull(char *s)
{
    int ln;
    char chMult;
    unsigned long long mult = 1;
    unsigned long long result = 0;

    /* We can have one trailing character providing a multiplier */
    if (s)
    {
        ln = strlen(s);
        if (ln > 1)
        {
            chMult = s[ln - 1];
            switch (chMult)
            {
                case 'k':
                case 'K':
                    mult = 1024;
                    s[ln - 1] = '\0';
                    break;

                case 'M':
                    mult = 1024 * 1024;
                    s[ln - 1] = '\0';
                    break;

                case 'G':
                    mult = 1024 * 1024 * 1024;
                    s[ln - 1] = '\0';
                    break;

                default:
                    break;
            }
        }

        result = strtoull(s, 0, 10);
        result *= mult;
    }

    return result;
}

/* Given a double, modify it to the binary range (0..1024) and return the
 * scale multiplier (K, M, G, etc) for the original value */
bool doubleToScale(double *x, char *scale)
{
    bool result = true;
    double orig;

    if ((x == NULL) || (scale == NULL))
        return false;

    orig = *x;
    *scale = 0;
    while ((*x >= 1024.0) && (*scale != 'Z') && result)
    {
        *x /= 1024.0;
        switch(*scale)
        {
            case 0:
                *scale = 'K';
                break;

            case 'K':
                *scale = 'M';
                break;

            case 'M':
                *scale = 'G';
                break;

            case 'G':
                *scale = 'T';
                break;

            case 'T':
                *scale = 'P';
                break;

            case 'P':
                *scale = 'E';
                break;

            case 'E':
                *scale = 'Z';
                break;

            default:
                *x = orig;
                *scale = 0;
                result = false;
                break;
        }
    }

    return result;
}

/* Given a double, modify it to the decimal range (0...1000) and return the
 * scale multiplier (...n, u, m, k, M, G, ...) for the original value */
bool doubleToDecimalScale(double *x, char *scale)
{
    bool result = true;
    double orig;

    if ((x == NULL) || (scale == NULL))
        return false;

    orig = *x;
    *scale = 0;
    if (*x >= 0.0)
    {
        while ((*x >= 1000.0) && (*scale != 'Z') && result)
        {
            *x /= 1000.0;
            switch(*scale)
            {
                case 0:
                    *scale = 'k';
                    break;

                case 'K':
                    *scale = 'M';
                    break;

                case 'M':
                    *scale = 'G';
                    break;

                case 'G':
                    *scale = 'T';
                    break;

                case 'T':
                    *scale = 'P';
                    break;

                case 'P':
                    *scale = 'E';
                    break;

                case 'E':
                    *scale = 'Z';
                    break;

                default:
                    *x = orig;
                    *scale = 0;
                    result = false;
                    break;
            }
        }
    }
    else
    {
        while ((*x < 0.0) && (*scale != 'f') && result)
        {
            *x *= 1000.0;
            switch(*scale)
            {
                case 0:
                    *scale = 'm';
                    break;

                case 'm':
                    *scale = 'u';
                    break;

                case 'u':
                    *scale = 'n';
                    break;

                case 'n':
                    *scale = 'p';
                    break;

                case 'p':
                    *scale = 'f';
                    break;

                default:
                    *x = orig;
                    *scale = 0;
                    result = false;
                    break;
            }
        }
    }

    return result;
}

/* Avoid repeating the code for showing statistics with scale names
 * prompt is the text prefix for the statistic (don't include " = "
 * on the end.
 * indent says the column to place the equals sign at
 * dVal is the value to show
 * unit is text for the unit type, e.g. "B"(Bytes), "B/s" (Bytes per-second), etc
 * binMult is true if the display is to be binary scale, e.g. MiB rather than MB
 * highScale set true to show scale names for values greater than 0.0
 * lowScale set true to show scale names for values less than 0.0
 * If both highScale and lowScale are true (the default argument values) then
 * the scale will be provided (if possible) to output dVal between 1 and
 * 1000/1024 as-needed.
 */
void showScaledData(const char *prompt, int indent, double dVal, const char *unit, bool binMult, bool highScale = true, bool lowScale = true)
{
    bool scaled;
    char mChar;
    int i, spaces;
    double myVal;

    if (prompt != NULL)
    {
        spaces = indent - strlen(prompt) - 2;
        if (spaces > 0)
        {
            for (i = 0; i < spaces; i++)
            {
                putchar(' ');
            }
            printf("%s = ", prompt);

            myVal = dVal;
            mChar = 0;
            scaled = false;
            if (binMult)
            {
                if (lowScale && (myVal < 0.0))
                    scaled = doubleToScale(&myVal, &mChar);
                else if (highScale && (myVal > 0.0))
                    scaled = doubleToScale(&myVal, &mChar);
            }
            else
            {
                if (lowScale && (myVal < 0.0))
                    scaled = doubleToDecimalScale(&myVal, &mChar);
                else if (highScale && (myVal > 0.0))
                    scaled = doubleToDecimalScale(&myVal, &mChar);
            }

            if (scaled)
            {
                if (binMult)
                    printf("%g %ci%s\n", myVal, mChar, unit);
                else
                    printf("%g %c%s\n", myVal, mChar, unit);
            }
            else
            {
                printf("%g %s\n", myVal, unit);
            }
        }
    }
}

/* Given pointers to timespecs x and y store the difference between them in
 * timespec result */
int timespec_elapsed(struct timespec *result, struct timespec *x, struct timespec *y)
{
    if ((x == NULL) || (y == NULL) || (result == NULL))
        return 1;

    /* Perform the carry for the later subtraction by updating y. */
    if (x->tv_nsec < y->tv_nsec) {
        int nsec = (y->tv_nsec - x->tv_nsec) / 1000000000 + 1;
        y->tv_nsec -= 1000000000 * nsec;
        y->tv_sec += nsec;
    }
    if (x->tv_nsec - y->tv_nsec > 1000000000) {
        int nsec = (x->tv_nsec - y->tv_nsec) / 1000000000;
        y->tv_nsec += 1000000000 * nsec;
        y->tv_sec -= nsec;
    }

    /* Compute the time remaining to wait.
    tv_usec is certainly positive. */
    result->tv_sec = x->tv_sec - y->tv_sec;
    result->tv_nsec = x->tv_nsec - y->tv_nsec;

    /* Return 1 if result is negative. */
    return x->tv_sec < y->tv_sec;
}

/* Given a pointer to a timespec return the elapsed time between it and now
 * as a double */
double timespec_elapsed_from(struct timespec *when)
{
    int s;
    struct timespec currentTime, elapsedTime;
    double dElapsed = -1.0;
    double b;

    if (when == NULL)
    {
        return dElapsed;
    }

    s = clock_gettime(CLOCK_REALTIME, &currentTime);
    if (s == 0)
    {
        if (timespec_elapsed(&elapsedTime, &currentTime, when) == 0)
        {
            dElapsed = elapsedTime.tv_sec;
            b = elapsedTime.tv_nsec;
            b /= 1.0e9;
            dElapsed += b;
        }
    }

    return dElapsed;
}

/* Verify the command-line provides valid settings */
bool VerifySettings()
{
    /* We must have threads */
    if (minthreads == 0)
    {
        printf("Not enough threads (%d), use --minthreads <num>\n", minthreads);
        return false;
    }
    /* Max threads can't be lower than min threads */
    if (maxthreads < minthreads)
    {
        printf("Max threads (%d) must be greater than or equal to Min threads (%d), use --maxthreads <num>\n",
               maxthreads, minthreads);
        return false;
    }
    /* I/O threads come from all threads and must leave some */
    if (iothreads >= minthreads)
    {
        printf("I/O threads (%d) must be less than Min Threads (%d), use --iothreads <num>\n",
               iothreads, minthreads);
        return false;
    }
    /* Time must be greater than zero */
    if (maxruntime < 1)
    {
        printf("Runtime (--time <num>) must be greater than zero (%u)\n",
               maxruntime);
        return false;
    }
    /* There must be an I/O filename target */
    if (ioFilename.length() < 1)
    {
        printf("No I/O filename specified\n");
        return false;
    }
    /* Max I/O Size must fit inside Max Memory */
    if ((maxMem != 0) && (maxIOSize > maxMem))
    {
        printf("Maximum I/O size (%llu) must be no more than Maximum memory (%llu)\n",
               maxIOSize, maxMem);
        return false;
    }
    /* Max I/O size has to be less than 2GB, really? */
    if (maxIOSize > (unsigned long long)0x7FFFFFFF)
    {
        printf("Maximum I/O size (%llu) must be less than 2GB\n",
               maxIOSize);
        return false;
    }
    /* Force a supported async I/O timeout if necessary */
    if (ioTimeout < (time_t)1)
    {
        printf("Unsupported I/O timeout (%ld), forcing %ld\n",
               ioTimeout, DEFAULT_ASYNC_IO_TIMEOUT);
        ioTimeout = DEFAULT_ASYNC_IO_TIMEOUT;
    }

    return true;
}

/* Parse the command-line arguments */
bool ParseArgs(int argc, char *argv[])
{
    int c;
    int option_index = 0;

    while (1) {
        c = getopt_long(argc, argv, "i:x:n:m:h", long_options, &option_index);
        if (c == -1)
            break;

        switch (c)
        {
            case 0:
                /* If this option set a flag, do nothing else now. */
                if (long_options[option_index].flag != 0)
                    break;
                if (verbose_flag)
                {
                    printf ("option %s", long_options[option_index].name);
                    if (optarg)
                        printf (" with arg %s", optarg);
                    printf ("\n");
                }
                break;

            case 'h':
                if (verbose_flag)
                    printf ("option -h\n");
                ShowHelp();
                return false;

            case 'i':
                if (verbose_flag)
                    printf ("option -i with value `%s'\n", optarg);
                iothreads = strtoui(optarg);
                break;

            case 'm':
                if (verbose_flag)
                    printf ("option -m with value `%s'\n", optarg);
                maxMem = memsztoull(optarg);
                break;

            case 'n':
                if (verbose_flag)
                    printf ("option -n with value `%s'\n", optarg);
                minthreads = strtoui(optarg);
                if (maxthreads == 0)
                    maxthreads = minthreads;
                break;

            case 'o':
                if (verbose_flag)
                    printf("option -o with value `%s'\n", optarg);
                ioTimeout = strtoui(optarg);
                break;

            case 't':
                if (verbose_flag)
                    printf("option -t with value `%s'\n", optarg);
                maxruntime = strtoui(optarg);
                break;

            case 'x':
                if (verbose_flag)
                    printf ("option -x with value `%s'\n", optarg);
                maxthreads = strtoui(optarg);
                break;

            case 'F':
                if (verbose_flag)
                    printf ("option -F with value `%s'\n", optarg);
                maxFileSize = memsztoull(optarg);
                break;

            case 'S':
                if (verbose_flag)
                    printf ("option -S with value `%s'\n", optarg);
                maxIOSize = memsztoull(optarg);
                break;

            default:
                return false;
        }
    }
    if (verbose_flag)
    {
        /* Instead of reporting '--verbose' and '--brief' as they are encountered,
        we report the final status resulting from them. */
        if (verbose_flag)
            puts ("verbose flag is set");
        else
            puts ("verbose flag is not set");
    }

    if (verbose_flag)
    {
        /* Instead of reporting '--shortthreads' and '--longthreads' as they are encountered,
        we report the final status resulting from them. */
        if (short_threads)
            puts ("Worker threads start and stop while program runs");
        else
            puts ("Worker threads are started at launch and left running");
    }

    if (verbose_flag)
    {
        /* Instead of reporting '--sigmaskthread' and '--sigmasktask' as they are encountered,
        we report the final status resulting from them. */
        if (sigmask_threads)
            puts ("Set signal mask using pthread_sigmask");
        else
            puts ("Set signal mask using sigprocmask");
    }

    /* Any remaining arguments */
    if (optind < argc)
    {
        ioFilename = argv[optind];
        if (verbose_flag)
        {
            printf ("non-option ARGV-elements: ");
            while (optind < argc)
                printf ("%s ", argv[optind++]);
            putchar ('\n');
        }
    }

    putchar('\n');
    printf(" Max Threads: %u\n", maxthreads);
    printf(" Min Threads: %u\n", minthreads);
    printf(" I/O Threads: %u\n", iothreads);
    putchar ('\n');
    printf("     Run for: %u s\n", maxruntime);
    putchar('\n');
    printf("  Max Memory: %llu", maxMem);
    if (maxMem == 0)
        puts(" (No limit)");
    putchar('\n');
    printf("Max I/O size: %llu\n", maxIOSize);
    printf(" I/O timeout: %ld s\n", ioTimeout);
    printf("    I/O file: %s\n", ioFilename.c_str());
    putchar('\n');

    /* Get Started */

    return VerifySettings();
}

/* Initialize our global synchronization objects */
bool setupSyncObjects(void)
{
    if (pthread_mutex_init(&wktilock, NULL) != 0)
    {
        printf("wktinfo mutex setup failed\n");
        return false;
    }
    initObjects |= INIT_WKTILOCK;

    if (pthread_mutex_init(&iordlock, NULL) != 0)
    {
        printf("I/O read mutex setup failed\n");
        return false;
    }
    initObjects |= INIT_IORDLOCK;

    if (pthread_mutex_init(&iowrlock, NULL) != 0)
    {
        printf("I/O write mutex setup failed\n");
        return false;
    }
    initObjects |= INIT_IOWRLOCK;

    if (pthread_mutex_init(&iodnlock, NULL) != 0)
    {
        printf("I/O done mutex setup failed\n");
        return false;
    }
    initObjects |= INIT_IODNLOCK;

    if (pthread_mutex_init(&iorsklock, NULL) != 0)
    {
        printf("I/O seek/read mutex setup failed\n");
        return false;
    }
    initObjects |= INIT_IORSKLOCK;

    if (pthread_mutex_init(&iowsklock, NULL) != 0)
    {
        printf("I/O seek/write mutex setup failed\n");
        return false;
    }
    initObjects |= INIT_IOWSKLOCK;

    return true;
}

/* Cleanup our global synchronization objects */
bool destroySyncObjects(void)
{
    if (initObjects & INIT_IOWSKLOCK)
    {
        if (pthread_mutex_destroy(&iowsklock) != 0)
        {
            printf("I/O seek/write mutex destroy failed\n");
            return false;
        }
        initObjects ^= INIT_IOWSKLOCK;
    }

    if (initObjects & INIT_IORSKLOCK)
    {
        if (pthread_mutex_destroy(&iorsklock) != 0)
        {
            printf("I/O seek/read mutex destroy failed\n");
            return false;
        }
        initObjects ^= INIT_IORSKLOCK;
    }

    if (initObjects & INIT_IODNLOCK)
    {
        if (pthread_mutex_destroy(&iodnlock) != 0)
        {
            printf("I/O done mutex destroy failed\n");
            return false;
        }
        initObjects ^= INIT_IODNLOCK;
    }

    if (initObjects & INIT_IOWRLOCK)
    {
        if (pthread_mutex_destroy(&iowrlock) != 0)
        {
            printf("I/O write mutex destroy failed\n");
            return false;
        }
        initObjects ^= INIT_IOWRLOCK;
    }

    if (initObjects & INIT_IORDLOCK)
    {
        if (pthread_mutex_destroy(&iordlock) != 0)
        {
            printf("I/O read mutex destroy failed\n");
            return false;
        }
        initObjects ^= INIT_IORDLOCK;
    }

    if (initObjects & INIT_WKTILOCK)
    {
        if (pthread_mutex_destroy(&wktilock) != 0)
        {
            printf("wktinfo mutex destroy failed\n");
            return false;
        }
        initObjects ^= INIT_WKTILOCK;
    }

    return true;
}

/* Initialize the test data file */
bool setupDataFile(void)
{
    size_t s;
    unsigned long long writeSize;
    unsigned long long curSize;
    unsigned char *fillData = NULL;

    if ((ioReadStream == NULL) && (ioWriteStream == NULL))
    {
        printf("Pre-populating I/O file %s\n (This may take a short time)\n", ioFilename.c_str());
        if (ioFilename.length() == 0)
            return false;

        ioWriteStream = fopen(ioFilename.c_str(), "w+");
        if (ioWriteStream == NULL)
            return false;

        ioReadStream = fopen(ioFilename.c_str(), "r");
        if (ioReadStream == NULL)
            return false;

        /* Initialize the file to twice the memory limit or 6G if no limit */
        if (maxFileSize != 0)
            fileSize = maxFileSize;
        else
        {
            fileSize = maxMem;
            fileSize *= 2;
        }
        if (fileSize == 0)
        {
            /* 6GiB if nothing specified */
            fileSize = 1024 * 1024;
            fileSize *= 1024;
            fileSize *= 6;
        }
        writeSize = 1024 * 1024;
        writeSize *= 10;
        if (writeSize > fileSize)
            writeSize = fileSize;
        fillData = (unsigned char *)calloc(1, writeSize);
        if (fillData == NULL)
        {
            fileSize = 0;
            return false;
        }

        curSize = 0;
        while (curSize <= fileSize)
        {
            s = fwrite(fillData, writeSize, 1, ioWriteStream);
            if (s < 1)
            {
                fileSize = 0;
                free(fillData);
                fillData = NULL;
                return false;
            }

            curSize += writeSize;
        }
    }
    if (fillData != NULL)
    {
        free(fillData);
        fillData = NULL;
    }

    return true;
}

/* Cleanup the test data file */
bool cleanupDataFile(void)
{
    bool result = true;

    while (nThreads > 0)
    {
        sleep(1);
    }
    if (ioReadStream != NULL)
    {
        if (fclose(ioReadStream) != 0)
            if (result)
                result = false;
    }
    if (ioWriteStream != NULL)
    {
        if (fclose(ioWriteStream) != 0)
            if (result)
                result = false;
        if (remove(ioFilename.c_str()) != 0)
            if (result)
                result = false;
    }

    return result;
}

/* Indicate all pthreads should exit then wait for them to finish */
void EndPThreads(void)
{
    if (Diagnose)
        printf("Ending all threads (%d)\n", nThreads.load(std::memory_order_relaxed));
    EndAllThreads = true;
    do
    {
        sleep(1);
    } while (nThreads.load(std::memory_order_relaxed) > 0);

    /* Free the thread info structures */
    CountingFree(iotinfo);
    iotinfo = NULL;
    CountingFree(wktinfo);
    wktinfo = NULL;
}

/* Clear an unknown I/O queue for which the caller performs the lock/unlock
 * and supplies pointers to the head and tail node variables. Returns the
 * number of nodes freed */
unsigned long long clearAnIOQueue(struct io_queue_node **qHead, struct io_queue_node **qTail)
{
    unsigned long long nodesFreed = 0;
    io_queue_node *node;

    while (*qHead != NULL)
    {
        node = *qHead;
        *qHead = node->next;
        if (*qHead != NULL)
        {
            (*qHead)->prev = NULL;
        }
        else
        {
            *qTail = NULL;
        }
        free(node);
        node = NULL;
        nodesFreed++;
    }
    *qHead = NULL;
    *qTail = NULL;

    return nodesFreed;
}

/* Lock the read queue */
bool readQLock()
{
    if (pthread_mutex_lock(&iordlock) == 0)
    {
        return true;
    }

    return false;
}

/* Unlock the read queue */
bool readQUnlock()
{
    if (pthread_mutex_unlock(&iordlock) == 0)
    {
        return true;
    }

    return false;
}

/* Return true if the read queue is empty */
bool isReadQEmpty(void)
{
    bool result = false;

    if (readQLock())
    {
        if (io_readQHead == NULL)
            result = true;

        if (!readQUnlock())
        {
            printf("Failed to exit I/O read lock critical section (isReadQEmpty), exiting\n");
            EndAllThreads = true;
        }
    }
    else
    {
        result = (pendingIOReads.load(std::memory_order_relaxed) == 0);
        if (Diagnose)
            printf("Failed to enter I/O read critical section (isReadQEmpty), using read count %llu\n", pendingIOReads.load(std::memory_order_relaxed));
    }

    return result;
}

/* Take the head node off the read queue */
io_queue_node *getIOReadNode(void)
{
    io_queue_node *result = NULL;

    if (readQLock())
    {
        if (Diagnose)
        {
            printf("read queue LOCKED for get\n");
            printf("Read queue %p/%p\n", io_readQHead, io_readQTail);
        }
        if (io_readQHead != NULL)
        {
            if (Diagnose)
                printf("Read queue POPULATED\n");
            result = io_readQHead;
            io_readQHead = result->next;
            if (io_readQHead != NULL)
            {
                io_readQHead->prev = NULL;
            }
            else
            {
                io_readQTail = NULL;
            }
            result->prev = NULL;
            result->next = NULL;
            pendingIOReads--;
        }
        else
        {
            if (Diagnose)
                printf("Read queue EMPTY\n");
        }

        if (!readQUnlock())
        {
            printf("Failed to exit I/O read lock critical section, exiting\n");
//            free(result);
//            result = NULL;
            EndAllThreads = true;
        }
        else
        {
            if (Diagnose)
                printf("read queue UNLOCKED get\n");
        }
    }
    else
    {
        if (Diagnose)
            printf("Failed to lock read queue\n");
    }

    return result;
}

/* Add a node to the read queue (at the tail) */
bool queueIORead(io_queue_node *node)
{
    bool result = false;

    /* Process if I/O not finished yet */
    if (!EndAllIO)
    {
        if (node != NULL)
        {
            if (Diagnose)
                printf("Queueing a READ\n");
            if (readQLock())
            {
                if (Diagnose)
                    printf("Read queue LOCKED\n");
                if (io_readQHead != NULL)
                {
                    if (Diagnose)
                        printf("Adding node to POPULATED queue\n");
                    node->prev = io_readQTail;
                    node->next = NULL;
                    io_readQTail = node;
                    node->prev->next = node;
                }
                else
                {
                    if (Diagnose)
                        printf("Adding node to EMPTY queue\n");
                    node->prev = NULL;
                    node->next = NULL;
                    io_readQHead = node;
                    io_readQTail = node;
                }
                pendingIOReads++;
                if (Diagnose)
                    printf("Read queue %p/%p\n", io_readQHead, io_readQTail);

                if (readQUnlock())
                {
                    if (Diagnose)
                        printf("Read queue UNLOCKED\n");
                    result = true;
                }
                else
                {
                    printf("Failed to exit I/O read lock critical section, exiting\n");
                    EndAllThreads = true;
                }
            }
        }
        else
        {
            if (Diagnose)
                printf("Attempt to queue NULL for read\n");
        }
    }

    return result;
}

/* Remove and free all nodes present on the read queue */
void clearIOReadQ(void)
{
    unsigned long long nodesFreed;

    if (readQLock())
    {
        nodesFreed = clearAnIOQueue(&io_readQHead, &io_readQTail);
        pendingIOReads -= nodesFreed;

        if (!readQUnlock())
        {
            printf("Failed to exit I/O read lock critical section, exiting\n");
            EndAllThreads = true;
        }
    }
}

/* Lock the write queue */
bool writeQLock()
{
    if (pthread_mutex_lock(&iowrlock) == 0)
    {
        return true;
    }

    return false;
}

/* Unlock the write queue */
bool writeQUnlock()
{
    if (pthread_mutex_unlock(&iowrlock) == 0)
    {
        return true;
    }

    return false;
}

/* Return true of the write queue is empty */
bool isWriteQEmpty(void)
{
    bool result = false;

    if (writeQLock())
    {
        if (io_writeQHead == NULL)
            result = true;

        if (!writeQUnlock())
        {
            printf("Failed to exit I/O read lock critical section (isWriteQEmpty), exiting\n");
            EndAllThreads = true;
        }
    }
    else
    {
        result = (pendingIOWrites.load(std::memory_order_relaxed) == 0);
        if (Diagnose)
            printf("Failed to enter I/O write critical section (isWriteQEmpty), using write count %llu\n", pendingIOWrites.load(std::memory_order_relaxed));
    }

    return result;
}

/* Take the head node off the write queue */
io_queue_node *getIOWriteNode()
{
    io_queue_node *result = NULL;

    if (writeQLock())
    {
        if (io_writeQHead != NULL)
        {
            result = io_writeQHead;
            io_writeQHead = result->next;
            if (io_writeQHead != NULL)
            {
                io_writeQHead->prev = NULL;
            }
            result->prev = NULL;
            result->next = NULL;
            pendingIOWrites--;
        }

        if (!writeQUnlock())
        {
            printf("Failed to exit I/O write lock critical section, exiting\n");
            EndAllThreads = true;
        }
    }

    return result;
}

/* Add a node to the write queue (at the tail) */
bool queueIOWrite(io_queue_node *node)
{
    bool result = false;

    /* Process if I/O not finished yet */
    if (!EndAllIO)
    {
        if (node != NULL)
        {
            if (Diagnose)
                printf("Queueing a WRITE\n");
            if (writeQLock())
            {
                if (Diagnose)
                    printf("Write queue LOCKED\n");
                if (io_writeQHead != NULL)
                {
                    if (Diagnose)
                        printf("Adding node to POPULATED queue\n");
                    node->prev = io_writeQTail;
                    node->next = NULL;
                    io_writeQTail = node;
                    node->prev->next = node;
                }
                else
                {
                    if (Diagnose)
                        printf("Adding node to EMPTY queue\n");
                    node->prev = NULL;
                    node->next = NULL;
                    io_writeQHead = node;
                    io_writeQTail = node;
                }
                pendingIOWrites++;

                if (writeQUnlock())
                {
                    if (Diagnose)
                        printf("Write queue UNLOCKED\n");
                    result = true;
                }
                else
                {
                    printf("Failed to exit I/O read lock critical section, exiting\n");
                    EndAllThreads = true;
                }
            }
        }
        else
        {
            if (Diagnose)
                printf("Attempt to queue NULL for read\n");
        }
    }

    return result;
}

/* Remove and free all nodes present on the read queue */
void clearIOWriteQ(void)
{
    unsigned long long nodesFreed;

    if (writeQLock())
    {
        nodesFreed = clearAnIOQueue(&io_writeQHead, &io_writeQTail);
        pendingIOWrites -= nodesFreed;

        if (!writeQUnlock())
        {
            printf("Failed to exit I/O read lock critical section, exiting\n");
            EndAllThreads = true;
        }
    }
}

/* Lock the I/O done queue */
bool doneQLock()
{
    if (pthread_mutex_lock(&iodnlock) == 0)
    {
        return true;
    }

    return false;
}

/* Unlock the I/O done queue */
bool doneQUnlock()
{
    if (pthread_mutex_unlock(&iodnlock) == 0)
    {
        return true;
    }

    return false;
}

/* Return true if the I/O done queue is empty */
bool isDoneQEmpty(void)
{
    bool result = false;

    if (doneQLock())
    {
        if (io_doneQHead == NULL)
            result = true;

        if (!doneQUnlock())
        {
            printf("Failed to exit I/O done lock critical section (isDoneQEmpty), exiting\n");
            EndAllThreads = true;
        }
    }
    else
    {
        result = (pendingIODone.load(std::memory_order_relaxed) == 0);
        if (Diagnose)
            printf("Failed to enter I/O done critical section (isDoneQEmpty), using done count %llu\n", pendingIODone.load(std::memory_order_relaxed));
    }

    return result;
}

/* Assuming a node in the I/O done queue, remove it alone */
bool getIODoneNode(io_queue_node *node)
{
    bool result = false;

    if (doneQLock())
    {
        if ((node != NULL) && (io_doneQHead != NULL))
        {
            /* NB: Not checking which list it is on, just a list, caller is in control */
            if ((node->next != NULL) || (node->prev != NULL)
                    || ((io_doneQHead == node) && (io_doneQTail == node)))
            {
                /* Extract the node from the list */
                if (node->prev != NULL)
                    node->prev->next = node->next;
                else
                    io_doneQHead = node->next;
                if (node->next != NULL)
                    node->next->prev = node->prev;
                else
                    io_doneQTail = node->prev;

                node->prev = NULL;
                node->next = NULL;
                pendingIODone--;

                result = true;
            }
        }

        if (!doneQUnlock())
        {
            printf("Failed to exit I/O done lock critical section, exiting\n");
            EndAllThreads = true;
        }
    }

    return result;
}

/* Add a node to the I/O done queue */
bool queueIODone(io_queue_node *node)
{
    bool result = false;
    int ts;

    if (node != NULL)
    {
        if (doneQLock())
        {
            if (Diagnose)
                printf("I/O Done queue LOCKED\n");
            if (io_doneQHead != NULL)
            {
                if (Diagnose)
                    printf("Placing node on POPULATED done queue\n");
                node->prev = io_doneQTail;
                node->next = NULL;
                io_doneQTail = node;
                if (node->prev != NULL)
                    node->prev->next = node;
            }
            else
            {
                if (Diagnose)
                    printf("Placing node on EMPTY done queue\n");
                node->prev = NULL;
                node->next = NULL;
                io_doneQHead = node;
                io_doneQTail = node;
            }
            pendingIODone++;
            if (node->my_sem != NULL)
            {
                if (Diagnose)
                    printf("Signaling I/O waiter\n");
                ts = sem_post(node->my_sem);
                if (ts != 0)
                {
                    if (Diagnose)
                        printf("Failed to signal I/O waiter, exiting\n");
                    EndAllThreads = true;
                }
            }
            else
                if (Diagnose)
                    printf("No I/O waiter to signal\n");

            if (doneQUnlock())
            {
                if (Diagnose)
                    printf("I/O done queue UNLOCKED\n");
                result = true;
            }
            else
            {
                printf("Failed to leave I/O done lock critical section, exiting\n");
                EndAllThreads = true;
            }
        }
    }
    else
    {
        if (Diagnose)
            printf("Attempt to place NULL node on I/O done queue\n");
    }

    return result;
}

/* Remove all nodes from the done queue and free each one */
void clearIODoneQ(void)
{
    unsigned long long nodesFreed;

    if (doneQLock())
    {
        nodesFreed = clearAnIOQueue(&io_doneQHead, &io_doneQTail);
        pendingIODone -= nodesFreed;

        if (!doneQUnlock())
        {
            printf("Failed to exit I/O read lock critical section, exiting\n");
            EndAllThreads = true;
        }
    }
}

/* Return true if any of the I/OI queues are populated */
bool wasIOPending(void)
{
    if (!isReadQEmpty() || !isWriteQEmpty() || !isDoneQEmpty())
    {
        printf("wasIOPending() YES");
        return true;
    }

    return false;
}

/* Is any I/O pending service (to perform or cleanup) */
bool isIOPending(void)
{
    if (isReadQEmpty())
    {
        if (isWriteQEmpty())
        {
            if (isDoneQEmpty())
            {
                if (Diagnose)
                {
                    printf("I/O QUEUES EMPTY (NO WORK)\n");
                    //(void)wasIOPending();
                }
                return false;
            }
            else
            {
                if (Diagnose)
                    printf("Done queue WTD\n");
                return true;
            }
        }
        else
        {
            if (Diagnose)
                printf("Write queue WTD\n");
            return true;
        }
    }
    else
    {
        if (Diagnose)
            printf("Read queue WTD\n");
        return true;
    }

    return true;
}

/* Empty all the IO queues */
void clearIOQueues(void)
{
    clearIOReadQ();
    clearIOWriteQ();
    clearIODoneQ();
}

/* If there is pending I/O, let it finish */
void EndIOTasks(void)
{
    /* Stop new I/O */
    EndAllIO = true;

    if (Diagnose)
    {
        putchar('\n');
        puts("I/O cleanup:");
    }

    /*
     * Wait for I/O to end itself:
     * If there are remaining worker threads (to clear "done" I/O)
     * If there are read, write or done requests pending service
     */
    while ((nThreads > nIOThreads) && isIOPending())
    {
        if (Diagnose && verbose_flag)
        {
            if (nThreads > nIOThreads)
            {
                printf("Worker threads available ");
            }
            if (isIOPending())
            {
                printf("I/O is pending ");
            }
            if ((nThreads > nIOThreads) && isIOPending())
            {
                printf("WAITING");
            }
            putchar('\n');
        }
        /* Cancel if there is pending read or write but no I/O threads */
        if ((nIOThreads < 1) && !(isReadQEmpty() && isWriteQEmpty()))
            break;

        sleep(1);
        if (Diagnose)
        {
            printf("   I/O threads = %d\n", nIOThreads.load(std::memory_order_relaxed));
            printf("       threads = %d\n", nThreads.load(std::memory_order_relaxed));
            if (verbose_flag)
            {
                if (!isReadQEmpty())
                {
                    printf("         Reads = %llu\n", pendingIOReads.load(std::memory_order_relaxed));
                    if (pendingIOReads.load(std::memory_order_relaxed) == 0)
                    {
                        printf("Queue head = %p\n", (void *)io_readQHead);
                    }
                }
                if (!isWriteQEmpty())
                {
                    printf("        Writes = %llu\n", pendingIOWrites.load(std::memory_order_relaxed));
                    if (pendingIOReads.load(std::memory_order_relaxed) == 0)
                    {
                        printf("Queue head = %p\n", (void *)io_writeQHead);
                    }
                }
                if (!isDoneQEmpty())
                {
                    printf("          Done = %llu\n", pendingIODone.load(std::memory_order_relaxed));
                    if (pendingIOReads.load(std::memory_order_relaxed) == 0)
                    {
                        printf("Queue head = %p\n", (void *)io_doneQHead);
                    }
                }
            }
            else
            {
                if (!isReadQEmpty())
                    printf("R/");
                if (!isWriteQEmpty())
                    printf("W/");
                if (!isDoneQEmpty())
                    printf("D");
            }
            putchar('\n');
        }
    }
}

/* Perform an asynchronous read of bufLen bytes for the supplied file at the
 * location pos with a timeout in timeout */
size_t asyncRead(int fd, void *buffer, off64_t pos, size_t bufLen, time_t timeout)
{
    bool timedOut = false;
    size_t result = (size_t)-1;
    int err;
    time_t start, tElapsed;
    struct aiocb64 aiocb;

    memset(&aiocb, 0, sizeof(aiocb));

    aiocb.aio_fildes = fd;
    aiocb.aio_buf = buffer;
    aiocb.aio_offset = pos;
    aiocb.aio_nbytes = bufLen;

    start = time(NULL);
    if (aio_read64(&aiocb) == -1)
    {
        if (verbose_flag)
        {
            if (Diagnose)
                printf("Asynchronous read error: %s\n", strerror(errno));

            return result;
        }
    }

    /* Wait until read completes or timeout */
    while ((err = aio_error64(&aiocb)) == EINPROGRESS)
    {
        sleep(1);
        if (start == (time_t)-1)
            break;
        tElapsed = GetElapsedFrom(start);
        if (tElapsed >= timeout)
        {
            timedOut = true;
            break;
        }
    }

    if (err == 0)
    {
        result = aio_return64(&aiocb);
    }
    else
    {
        while ((err = aio_cancel64(fd, &aiocb)) == AIO_NOTCANCELED)
        {
            if (Diagnose)
                printf("Unable to cancel timed-out read\n");

            sleep(1);
        }
        if (err == AIO_ALLDONE)
        {
            result = aio_return64(&aiocb);
        }
        else
        {
            if (timedOut)
                timeoutReads++;
        }
    }

    if (result == (size_t)-1)
    {
        failedReads++;
    }
    else
    {
        if (result != bufLen)
        {
            incompleteReads++;
            underRead += (bufLen - result);
        }
    }

    return result;
}

/* Given an I/O queue node perform a read for it */
bool ioFileRead(io_queue_node *node)
{
    int fs = -2;
    off64_t pos, rs = 0;
    off64_t ra = (off64_t)-5;
    struct flock fLock;

    if ((ioReadStream == NULL) || (node == NULL))
        return false;
    if (node->my_fd == -1)
        return false;
    if ((node->io_buffer == NULL) || (node->io_len < 1))
        return false;

    pos = fileSize - node->io_len - 1;
    pos = (rand() * pos) / RAND_MAX;
    /* Lock our read region */
    fLock.l_type = F_RDLCK;
    fLock.l_whence = SEEK_SET;
    fLock.l_start = pos;
    fLock.l_len = node->io_len;
    fLock.l_pid = 0;
    fs = fcntl(node->my_fd, F_OFD_SETLKW, &fLock);
    if (fs != -1)
    {
        if (Diagnose)
        {
            if (fileSize < (pos + node->io_len))
            {
                printf("Attempting data file read of %lu bytes at offset %ld in %llu Byte file\n",
                        node->io_len, pos, fileSize);
            }
        }
        totalTriedIORead += node->io_len;
        rs = asyncRead(node->my_fd, node->io_buffer, pos, node->io_len, ioTimeout);
        ra = rs;
        if (ra != (off64_t)-1)
        {
            node->io_done = node->io_len;
        }
        else
        {
            ra = -1;
        }

        /* Unlock our read region */
        fLock.l_type = F_UNLCK;
        fLock.l_whence = SEEK_SET;
        fLock.l_start = pos;
        fLock.l_len = node->io_len;
        fLock.l_pid = 0;
        fs = fcntl(node->my_fd, F_OFD_SETLKW, &fLock);
        if (fs == -1)
        {
            printf("Failed to unlock data file read lock, exiting\n");
            EndAllThreads = true;
            ra = -2;
        }
    }
    else
    {
        if (Diagnose)
            printf("Failed to obtain data file %lu byte read lock (%ld/%lu) - %d\n",
                    node->io_len, pos, sizeof(fLock.l_start), errno);
        ra = -3;
    }

    nIOTasks++;
    if ((fs != 0) || (ra < 0))
        return false;

    return true;
}

/* Perform an asynchronous write of bufLen bytes for the supplied file at the
 * location pos with a timeout in timeout */
size_t asyncWrite(int fd, void *buffer, off64_t pos, size_t bufLen, time_t timeout)
{
    bool timedOut = false;
    size_t result = (size_t)-1;
    int err;
    time_t start, tElapsed;
    struct aiocb64 aiocb;

    memset(&aiocb, 0, sizeof(aiocb));

    aiocb.aio_fildes = fd;
    aiocb.aio_buf = buffer;
    aiocb.aio_offset = pos;
    aiocb.aio_nbytes = bufLen;

    start = time(NULL);
    if (aio_write64(&aiocb) == -1)
    {
        if (verbose_flag)
        {
            if (Diagnose)
                printf("Asynchronous write error: %s\n", strerror(errno));

            return result;
        }
    }

    /* Wait until read completes or timeout */
    while ((err = aio_error64(&aiocb)) == EINPROGRESS)
    {
        sleep(1);
        if (start == (time_t)-1)
            break;
        tElapsed = GetElapsedFrom(start);
        if (tElapsed >= timeout)
        {
            timedOut = true;
            break;
        }
    }

    if (err == 0)
    {
        result = aio_return64(&aiocb);
    }
    else
    {
        while ((err = aio_cancel64(fd, &aiocb)) == AIO_NOTCANCELED)
        {
            if (Diagnose)
            {
                printf("Unable to cancel timed-out write\n");
            }
            sleep(1);
        }
        if (err == AIO_ALLDONE)
        {
            result = aio_return64(&aiocb);
        }
        else
        {
            if (timedOut)
                timeoutWrites++;
        }
    }

    if (result == (size_t)-1)
    {
        failedWrites++;
    }
    else
    {
        if (result != bufLen)
        {
            incompleteWrites++;
            underWrite += (bufLen - result);
        }
    }

    return result;
}

/* Given an I/O node perform a write for it */
bool ioFileWrite(io_queue_node *node)
{
    int fs = -2;
    size_t pos, ws = 0;
    size_t ra = -5;
    struct flock fLock;

    if (node == NULL)
        return false;
    if (node->my_fd == -1)
        return false;
    if ((node->io_buffer == NULL) || (node->io_len < 1))
        return false;

    pos = fileSize - node->io_len - 1;
    pos = (rand() * pos) / RAND_MAX;
    /* Lock our write region */
    fLock.l_type = F_WRLCK;
    fLock.l_whence = SEEK_SET;
    fLock.l_start = pos;
    fLock.l_len = node->io_len;
    fLock.l_pid = 0;
    fs = fcntl(node->my_fd, F_OFD_SETLKW, &fLock);
    if (fs != -1)
    {
        if (Diagnose)
        {
            if (fileSize < (pos + node->io_len))
            {
                printf("Attempting data file write of %lu bytes at offset %ld in %llu Byte file\n",
                        node->io_len, pos, fileSize);
            }
        }
        totalTriedIOWrite += node->io_len;
        ws = asyncWrite(node->my_fd, node->io_buffer, pos, node->io_len, ioTimeout);
        ra = ws;
        if (ra != (size_t)-1)
        {
            node->io_done = node->io_len;
        }
        else
        {
            ra = -1;
        }

        /* Unlock our write region */
        fLock.l_type = F_UNLCK;
        fLock.l_whence = SEEK_SET;
        fLock.l_start = pos;
        fLock.l_len = node->io_len;
        fLock.l_pid = 0;
        fs = fcntl(node->my_fd, F_OFD_SETLKW, &fLock);
        if (fs == -1)
        {
            printf("Failed to unlock data file write lock, exiting\n");
            EndAllThreads = true;
            ra = -2;
        }
    }
    else
    {
        if (Diagnose)
            printf("Failed to obtain data file %lu byte write lock (%lu/%lu) - %d\n",
                    node->io_len, pos, sizeof(fLock.l_start), errno);
        ra = -3;
    }

    nIOTasks++;
    if ((fs != 0) || (ra < 0))
        return false;

    return true;
}

/* I/O thread function */
void *IOThreadStart(void *arg)
{
    struct thread_info *mytinfo = (struct thread_info *)arg;
    unsigned long long p;
    int activity;
    io_queue_node *node;

    nTotalThreads++;
    nThreads++;
    nIOThreads++;
    nTotalIOThreads++;

    if (arg == NULL)
    {
        printf("I/O thread started with no arguments, exiting\n");
        EndAllThreads = true;
        return NULL;
    }
    if (Diagnose)
        printf("I/O thread %d: top of stack near %p; argv_pointer=%p\n",
                   mytinfo->thread_num, &p, mytinfo->argv_string);

    if (sem_init(&mytinfo->my_sem, 0, 0) != 0)
    {
        printf("Failed to initialize semaphore for I/O thread %d, exiting", mytinfo->thread_num);
        EndAllThreads = true;
        return NULL;
    }

    /* Get our own stream handle */
    mytinfo->my_fd = open(ioFilename.c_str(), O_RDWR | O_LARGEFILE);
    if (mytinfo->my_fd == -1)
    {
        printf("Failed to open file for I/O thread %d, exiting", mytinfo->thread_num);
        EndAllThreads = true;
        return NULL;
    }

    while (!EndAllThreads)
    {
        activity = getActivity(2, mytinfo->thread_num);
        switch(activity)
        {
            /* Read */
            case 0:
                node = getIOReadNode();
                if (node != NULL)
                {
                    node->my_fd = mytinfo->my_fd;
                    nTriedIOTasks++;
                    if (!ioFileRead(node))
                    {
                        if (verbose_flag)
                            printf("Read (node) failure of size %lu\n", node->io_len);
                    }
                    node->my_fd = -1;
                    if (queueIODone(node))
                    {
                        node = NULL;
                    }
                    else
                    {
                        printf("Failed to queue read I/O done (%lu/%lu), exiting\n", node->io_done, node->io_len);
                        EndAllThreads = true;
                    }
                }
                else
                {
                    sleep(1);
                }
                break;

            /* Write */
            case 1:
                node = getIOWriteNode();
                if (node != NULL)
                {
                    node->my_fd = mytinfo->my_fd;
                    nTriedIOTasks++;
                    if (!ioFileWrite(node))
                    {
                        if (verbose_flag)
                            printf ("Write (node) failure of size %lu\n", node->io_len);
                    }
                    node->my_fd = -1;
                    if (queueIODone(node))
                    {
                        node = NULL;
                    }
                    else
                    {
                        printf("Failed to queue write I/O done (%lu/%lu), exiting\n", node->io_done, node->io_len);
                        EndAllThreads = true;
                    }
                }
                else
                {
                    sleep(1);
                }
                break;

            default:
                sleep(1);
                break;
        }
    };

    /* No more I/O */
    if (mytinfo->my_fd != -1)
    {
        if (close(mytinfo->my_fd) != 0)
        {
            printf("Failed to close I/O file for I/O thread %d, exiting", mytinfo->thread_num);
            EndAllThreads = true;
        }
        mytinfo->my_fd = -1;
    }


    if (sem_destroy(&mytinfo->my_sem) != 0)
    {
        printf("Failed to destroy semaphore for I/O thread %d, exiting", mytinfo->thread_num);
        EndAllThreads = true;
    }

    if (Diagnose)
        printf("I/O thread %d ending\n", mytinfo->thread_num);

    mytinfo->thread_num = 0;

    nIOThreads--;
    nThreads--;

    return NULL;
}

/* Create and initialize all I/O threads */
int SetupIOThreads(void)
{
    int s, t;
    unsigned int tnum;
    pthread_attr_t attr;

    s = pthread_attr_init(&attr);
    if (s != 0)
        return s;

    iotinfo = (struct thread_info *)CountingCalloc(iothreads, sizeof(struct thread_info));
    if (iotinfo == NULL)
        return -1;

    /* Create one thread for each I/O thread */
    for (tnum = 0; tnum < iothreads; tnum++)
    {
        t = threadNum++;
        iotinfo[tnum].thread_num = t;
        iotinfo[tnum].argv_string = NULL;
        s = pthread_create(&iotinfo[tnum].thread_id, &attr, IOThreadStart, &iotinfo[tnum]);
        if (s != 0)
            return s;
    }

    s = pthread_attr_destroy(&attr);
    if (s != 0)
        return s;

    return 0;
}

    /* Default signal mask */
void setupDefaultSigMask(void)
{
    sigemptyset(&sigmask);
    sigaddset(&sigmask, SIGQUIT);
    sigaddset(&sigmask, SIGUSR1);
}

/* Reset the signal mask (after the first case it is without changing it) */
bool setSigMask(void)
{
    int s;

    if (sigmask_threads)
    {
        s = pthread_sigmask(SIG_BLOCK, &sigmask, NULL);
    }
    else
    {
        s = sigprocmask(SIG_BLOCK, &sigmask, NULL);
    }
    nSigMaskSets++;

    return (s == 0);
}

/* Worker thread function */
void *WorkerThreadStart(void *arg)
{
    unsigned long long p;
    bool ab = false;
    bool cd = false;
    bool memQueued, longWait;
    bool endMe = false;
    int activity, s, scs, iotype;
    unsigned long long avail, ts, sum, num, pos;
    unsigned long long sz = 0;
#if 0
    unsigned long long dv;
#endif
    double dVal, dElapsed;
    void *myMem = NULL;
    unsigned long long *wspace;
    struct thread_info *mytinfo = (struct thread_info *)arg;
    siginfo_t sigs;
    struct timespec waitfor, start;
    struct timeval ;
    io_queue_node *node;

    nTotalThreads++;
    nThreads++;

    if (Diagnose)
        printf("Worker thread %d: top of stack near %p; argv_pointer=%p\n",
                   mytinfo->thread_num, &p, mytinfo->argv_string);

    if (sem_init(&mytinfo->my_sem, 0, 0) != 0)
    {
        printf("Failed to initialize semaphore for worker thread %d, exiting", mytinfo->thread_num);
        EndAllThreads = true;
        goto workerFinished;
    }
    memQueued = false;

    /* Work loop */
    while (!EndAllThreads && !endMe)
    {
        /* Get a random activity identity to perform */
        activity = getActivity(8, mytinfo->thread_num);
        switch(activity)
        {
            case 0:
                /* Allocate some memory */
                if (myMem == NULL)
                {
                    if (maxMem != 0)
                    {
                        ab = true;
                        avail = maxMem - memUsed.load(std::memory_order_relaxed);
                        sz = (rand() * maxIOSize) / RAND_MAX;
                    }
                    else
                    {
                        ab = false;
                        avail = memUsed.load(std::memory_order_relaxed);
                        sz = (rand() * maxIOSize) / RAND_MAX;
                    }
                    if (sz == 0)
                    {
                        if (avail > 4096)
                        {
                            cd = true;
                            sz = 4096;
                        }
                        else
                        {
                            cd = false;
                            sz = avail / 2;
                            if (sz == 0)
                            {
                                sz = 8;
                            }
                        }
                    }
/* This block and the #if 0 excluded dv variable above are for diagnosing the
 * selection of a size to use for a memory allocation for a thread insance.
 * The diagnosis would show the path taken and the size value generated. It
 * is not required when no problems are expected */
#if 0
                    if (maxMem)
                    {
                        ab = true;
                        dv = 4;
                        if (dv > ts)
                        {
                            dv = ts - 1;
                        }
                        if (ts > 1)
                        {
                            cd = true;
                            sz = (maxMem - memUsed.load(std::memory_order_relaxed)) / (ts / (1 + rand() % dv));
                        }
                        else
                        {
                            cd = false;
                            sz = (maxMem - memUsed.load(std::memory_order_relaxed)) / (1 + rand() % 4);
                        }
                    }
                    else
                    {
                        ab = false;
                        dv = 6;
                        if (dv > ts)
                        {
                            dv = ts - 1;
                        }
                        if (ts > 1)
                        {
                            cd = true;
                            sz = memUsed.load(std::memory_order_relaxed) / (ts / (1 + rand() % dv));
                        }
                        else
                        {
                            cd = false;
                            sz = memUsed.load(std::memory_order_relaxed) / (1 + rand() % 6);
                        }
                    }
                    if (sz == 0)
                        sz = 4096;
#endif

                    myMem = CountingCalloc(1, sz);
                    if (myMem == NULL)
                    {
                        printf("Worker thread %d: failed to allocate %llu bytes (",
                                    mytinfo->thread_num, sz);
                        if (ab)
                            putchar('A');
                        else
                            putchar('B');
                        putchar('/');
                        if (cd)
                            putchar('A');
                        else
                            putchar('B');
                        puts(")\n");
                    }
                    else
                    {
                        if (Diagnose)
                        {
                            dVal = memUsed.load(std::memory_order_relaxed);
                            showScaledData("Memory used", 24, dVal, "B", true);
                        }
                    }
                }
                break;

            case 1:
                /* Free any memory we have allocated */
                if (myMem != NULL)
                {
                    CountingFree(myMem);
                    myMem = NULL;
                    sz = 0;
                    if (Diagnose)
                    {
                        dVal = memUsed.load(std::memory_order_relaxed);
                        showScaledData("Memory used", 24, dVal, "B", true);
                    }
                }
                break;

            case 2:
                /* Zero any memory we have allocated (write) */
                if ((myMem != NULL) && (sz > 0))
                {
                    memset(myMem, 0, sz);
                    totalWrite += sz;
                }
                break;

            case 3:
                /* Read any memory we have allocated */
                if ((myMem != NULL) && (sz > sizeof(sum)))
                {
                    sum = 0;
                    num = sz / sizeof(sum);
                    wspace = (unsigned long long *)myMem;
                    for (pos = 0; pos < num; pos++)
                    {
                        sum += wspace[pos];
                    }
                    totalRead += (num * sizeof(sum));
                }
                break;

            case 4:
                /* End this thread, another can be started by main if it's not the only one */
                if (((nThreads - nIOThreads) > 1) && (rand() < RESTART_SCOPE))
                {
                    if (Diagnose)
                        printf("Ending thread number %d (%d of %d)\n", mytinfo->thread_num, (nThreads - nIOThreads), nTotalThreads.load(std::memory_order_relaxed));
                    endMe = true;
                }
                break;

            /* Use two actions for (ultimately) the set signal mask so that
             * it has double the probablity of the other actions */
            case 5:
            case 6:
                /* Set the signal mask */
                if (rand() % 8)
                {
                    waitfor.tv_sec = 0;
                    waitfor.tv_nsec = 100000;
                    longWait = false;
                }
                else
                {
                    waitfor.tv_sec = 1;
                    waitfor.tv_nsec = 0;
                    longWait = true;
                }
                totalTriedSigWaits++;
                dElapsed = 0.0;
                scs = clock_gettime(CLOCK_REALTIME, &start);
                s = sigtimedwait(&sigmask, &sigs, &waitfor);
                if (scs == 0)
                {
                    dElapsed = timespec_elapsed_from(&start);
                    if (dElapsed < 0.0)
                    {
                        dElapsed = 0.0;
                    }
                }
                if (s == -1)
                {
                    elapsedSigWaits = elapsedSigWaits + dElapsed;
                    if (longWait)
                        totalLongSigWaits++;
                    else
                        totalShortSigWaits++;
                    /* Reset the signal mask without changing it */
                    (void)setSigMask();
                }
                else
                {
                    elapsedGoodSigWaits = elapsedGoodSigWaits + dElapsed;
                    if (s == SIGUSR1)
                    {
                        sigStop++;
                    }
                }
                break;

            case 7:
                /* Perform an I/O operation using an I/O thread */
                if ((myMem != NULL) && (nIOThreads > 0))
                {
                    /* Let an I/O thread use our buffer */
                    node = (io_queue_node *)calloc(1, sizeof(*node));
                    if (node != NULL)
                    {
                        node->io_buffer = myMem;
                        node->io_len = (sz * rand()) / RAND_MAX;
                        if (node->io_len < 1)
                            node->io_len = 1;
                        node->my_sem = &mytinfo->my_sem;
                        iotype = getActivity(2, mytinfo->thread_num);
                        if (iotype == 0)
                        {
                            if (queueIORead(node))
                                nQueuedIOTasks++;
                        }
                        else
                        {
                            if (queueIOWrite(node))
                                nQueuedIOTasks++;
                        }
                        memQueued = true;

                        /* Wait for completion */
                        do
                        {
                            ts = sem_trywait(node->my_sem);
                            if (ts == 0)
                            {
                                if (verbose_flag)
                                    printf("read/write waiter notified I/O complete\n");
                                /* Remove the buffer from the I/O done queue */
                                if (getIODoneNode(node))
                                {
                                    memQueued = false;
                                    if (iotype == 0)
                                        totalIORead += node->io_done;
                                    else
                                        totalIOWrite += node->io_done;
                                    free(node);
                                    node = NULL;
                                }
                                else
                                {
                                    printf("read/write wait for completion fails to find node on done queue, exiting\n");
                                    /* End program on failure to get node back */
                                    EndAllThreads = true;
                                }
                            }
                            else
                            {
                                sleep(1);
                            }
                        } while (!EndAllThreads && (ts != 0));
                    }
                }
                break;

            default:
                if (Diagnose)
                    printf("Worker thread %d: IDLE (memory used is %llu)\n",
                            mytinfo->thread_num, memUsed.load(std::memory_order_relaxed));
                sleep(1 + (rand() % 2));
                break;
        }
    };

    /* Free any memory we have allocated, it will not be on an I/O queue */
    if ((myMem != NULL) && !memQueued)
    {
        CountingFree(myMem);
        myMem = NULL;
    }

    /* Finished with our thread semaphore */
    if (sem_destroy(&mytinfo->my_sem) != 0)
    {
        printf("Failed to destroy semaphore for worker thread %d, exiting", mytinfo->thread_num);
        EndAllThreads = true;
    }

workerFinished:
    if (Diagnose)
        printf("Worker thread %d ending\n", mytinfo->thread_num);


    /* This thread is finished with it's thread_info */
    mytinfo->thread_num = 0;

    nThreads--;

    return NULL;
}

/* Find an unused thread number
 * Caller must hold wktilock */
int getUnusedWorkerThreadNum(void)
{
    int wNum, maxworkers;

    if (Diagnose)
        printf("Finding an unused worker\n");
    maxworkers = maxthreads - iothreads;

    /* Trawl through wktinfo looking for a zero thread_num */
    for (wNum = 0; wNum < maxworkers; wNum++)
    {
        if (wktinfo[wNum].thread_num == 0)
        {
            if (Diagnose)
                printf("Found unused worker %d\n", wNum);
            return wNum;
        }
    }

    return -1;
}

/* Create and initialize a single worker thread
 * use wNum to specify a thread number in the worker thread info data or
 * specify wNum as -1 to let one be chosen from those not used */
int startOneWorkerThread(int wNum, pthread_attr_t *attr)
{
    int result, s, t;

    result = -1;

    /* We need to lock the worker thread info data so that we can find an
     * unused one or modify the one we are interested in  */
    if (pthread_mutex_lock(&wktilock) == 0)
    {
        if (wNum < 0)
            wNum = getUnusedWorkerThreadNum();
        if (wNum >= 0)
        {
            t = threadNum++;
            wktinfo[wNum].thread_num = t;
            wktinfo[wNum].argv_string = NULL;
            s = pthread_create(&wktinfo[wNum].thread_id, attr, WorkerThreadStart, &wktinfo[wNum]);
            if (s != 0)
            {
                if (verbose_flag)
                    printf("Failed to create thread number %d\n", wktinfo[wNum].thread_num);

                wktinfo[wNum].thread_num = 0;
                return s;
            }
            if (nThreads > nPeakThreads)
                nPeakThreads = nThreads.load(std::memory_order_relaxed);
            result = 0;
        }

        /* Finished with the worker thread info */
        if (pthread_mutex_unlock(&wktilock) != 0)
        {
            if (Diagnose)
                printf("Unlock critical section of getUnusedWorkThreadNum failed\n");
        }
    }

    return result;
}

/* Launch initial worker threads */
int SetupWorkerThreads(void)
{
    int s, minworkers, maxworkers, tnum;
    pthread_attr_t attr;

    s = pthread_attr_init(&attr);
    if (s != 0)
    {
        if (verbose_flag)
            printf("Failed to initialize thread attr\n");
        return s;
    }

    minworkers = minthreads - iothreads;
    maxworkers = maxthreads - iothreads;

    /* Allocate memory to store thread_info data for the maximum worker
     * threads */
    wktinfo = (struct thread_info *)CountingCalloc(maxworkers, sizeof(struct thread_info));
    if (wktinfo == NULL)
    {
        if (verbose_flag)
            printf("Failed to allocate memory for thread info data\n");
        (void)pthread_attr_destroy(&attr);
        return -1;
    }

    /* Create one thread for each worker */
    for (tnum = 0; tnum < minworkers; tnum++)
    {
        s = startOneWorkerThread(tnum, &attr);
        if (s != 0)
        {
            if (verbose_flag)
                printf("Failed to create thread number %d\n", wktinfo[tnum].thread_num);
            (void)pthread_attr_destroy(&attr);
            return s;
        }
    }

    printf("All %d workers created\n", minworkers);

    s = pthread_attr_destroy(&attr);
    if (s != 0)
    {
        if (verbose_flag)
            printf("Failed to destroy thread attr\n");
        return s;
    }

    return 0;
}

/* Given a start and finish time return the duration between them */
time_t GetElapsed(time_t start, time_t finish)
{
    time_t result = (time_t)-1;

    if ((start != (time_t)-1) && (finish != (time_t)-1))
    {
        result = finish;
        result -= start;
        if ((result >= (time_t)0) && (result < (time_t)1))
            result = 1;

        if (result < (time_t)0)
            result = (time_t)-1;
    }

    return result;
}

/* Given a time return the duration between it and now */
time_t GetElapsedFrom(time_t someTime)
{
    time_t curTime = time(NULL);

    return GetElapsed(someTime, curTime);
}

/* Display function for thread and memory results */
void showThreadAndMemoryData(double dElapsed)
{
    int totalWorkers;
    double dVal;

    puts("Thread/Memory Data:");
    printf("         Total threads = %d\n", nTotalThreads.load(std::memory_order_relaxed));
    printf("          Peak threads = %d\n", nPeakThreads.load(std::memory_order_relaxed));
    printf("       End I/O threads = %d\n", nIOThreads.load(std::memory_order_relaxed));
    printf("           End threads = %d\n", nThreads.load(std::memory_order_relaxed));
    dVal = memUsed.load(std::memory_order_relaxed);
    showScaledData("End memory used", 24, dVal, "B", true);
    dVal = totalRead.load(std::memory_order_relaxed);
    showScaledData("Bytes read", 24, dVal, "B", true);
    dVal = totalWrite.load(std::memory_order_relaxed);
    showScaledData("Bytes written", 24, dVal, "B", true);
    printf("           Signal wait = %llu times\n", totalTriedSigWaits.load(std::memory_order_relaxed));
    totalWorkers = (nTotalThreads - nTotalIOThreads);
    dVal = totalTriedSigWaits.load(std::memory_order_relaxed);
    dVal /= totalWorkers;
    printf("    Signal wait (mean) = %g times/thread\n", dVal);
    printf("       Set signal mask = %d times\n", nSigMaskSets.load(std::memory_order_relaxed));
    if (Diagnose)
    {
        printf("                  Long = %llu times\n", totalLongSigWaits.load(std::memory_order_relaxed));
        printf("                 Short = %llu times\n", totalShortSigWaits.load(std::memory_order_relaxed));
    }
    dVal = nSigMaskSets.load(std::memory_order_relaxed);
    dVal /= totalWorkers;
    printf("Set signal mask (mean) = %g times/thread\n", dVal);
    if (Diagnose)
    {
        dVal = totalLongSigWaits.load(std::memory_order_relaxed);
        dVal /= totalWorkers;
        printf("                  Long = %g times/thread\n", dVal);
        dVal = totalShortSigWaits.load(std::memory_order_relaxed);
        dVal /= totalWorkers;
        printf("                 Short = %g times/thread\n", dVal);
    }
    dVal = elapsedSigWaits.load(std::memory_order_relaxed);
    showScaledData("Signal Wait Time", 24, dVal, "s", false, false);
    dVal /= totalWorkers;
    showScaledData("(No signal)", 24, dVal, "s/thread", false, false);
    dVal = elapsedGoodSigWaits.load(std::memory_order_relaxed);
    showScaledData("Wait on issued signals", 24, dVal, "s", false, false);
    dVal /= totalWorkers;
    showScaledData("(Signal)", 24, dVal, "s/thread", false, false);
    putchar('\n');
    if (dElapsed != 0.0)
    {
        dVal = totalRead.load(std::memory_order_relaxed);
        dVal /= dElapsed;
        showScaledData("Mem Read rate", 24, dVal, "B/s", true);
        dVal = totalWrite.load(std::memory_order_relaxed);
        dVal /= dElapsed;
        showScaledData("Mem Write rate", 24, dVal, "B/s", true);
        dVal = totalRead.load(std::memory_order_relaxed);
        dVal += totalWrite.load(std::memory_order_relaxed);
        dVal /= dElapsed;
        showScaledData("Abs Mem rate", 24, dVal, "B/s", true);
        putchar('\n');
    }
}

/* Display function for I/O results */
void showIOData(const char *place, double dElapsed)
{
    unsigned long long ullVal;
    double dVal;

    printf("I/O Data");
    if (place != NULL)
        printf(" %s\n", place);
    putchar('\n');

    dVal = totalTriedIORead.load(std::memory_order_relaxed);
    showScaledData("Tried I/O reads", 24, dVal, "B", true);
    dVal = totalIORead.load(std::memory_order_relaxed);
    showScaledData("I/O reads", 24, dVal, "B", true);
    ullVal = failedReads.load(std::memory_order_relaxed);
    if (ullVal != 0)
    {
        printf("          Failed reads = %llu\n", ullVal);
    }
    ullVal = timeoutReads.load(std::memory_order_relaxed);
    if (ullVal != 0)
    {
        printf("         Timeout reads = %llu\n", ullVal);
    }
    ullVal = incompleteReads.load(std::memory_order_relaxed);
    if (ullVal != 0)
    {
        printf("      Incomplete reads = %llu\n", ullVal);
    }
    dVal = underRead.load(std::memory_order_relaxed);
    if (dVal != 0.0)
    {
        showScaledData("Under read", 24, dVal, "B", true);
    }
    dVal = totalTriedIOWrite.load(std::memory_order_relaxed);
    showScaledData("Tried I/O writes", 24, dVal, "B", true);
    dVal = totalIOWrite.load(std::memory_order_relaxed);
    showScaledData("I/O writes", 24, dVal, "B", true);
    ullVal = failedWrites.load(std::memory_order_relaxed);
    if (ullVal != 0)
    {
        printf("         Failed writes = %llu\n", ullVal);
    }
    ullVal = timeoutWrites.load(std::memory_order_relaxed);
    if (ullVal != 0)
    {
        printf("        Timeout writes = %llu\n", ullVal);
    }
    ullVal = incompleteWrites.load(std::memory_order_relaxed);
    if (ullVal != 0)
    {
        printf("     Incomplete writes = %llu\n", ullVal);
    }
    dVal = underWrite.load(std::memory_order_relaxed);
    if (dVal != 0.0)
    {
        showScaledData("Under write", 24, dVal, "B", true);
    }
    printf("        I/O read nodes = %llu remaining\n", pendingIOReads.load(std::memory_order_relaxed));
    printf("       I/O write nodes = %llu remaining\n", pendingIOWrites.load(std::memory_order_relaxed));
    printf("        I/O done nodes = %llu remaining\n", pendingIODone.load(std::memory_order_relaxed));
    putchar('\n');
    if (dElapsed != 0.0)
    {
        dVal = totalIORead.load(std::memory_order_relaxed);
        dVal /= dElapsed;
        showScaledData("I/O read rate", 24, dVal, "B/s", true);
        dVal = totalIOWrite.load(std::memory_order_relaxed);
        dVal /= dElapsed;
        showScaledData("I/O write rate", 24, dVal, "B/s", true);
        dVal = totalIORead.load(std::memory_order_relaxed);
        dVal += totalIOWrite.load(std::memory_order_relaxed);
        dVal /= dElapsed;
        showScaledData("Abs I/O rate", 24, dVal, "B/s", true);
        putchar('\n');
    }
}

/* Show all the test results */
void showTestResult(double dElapsed)
{
    showThreadAndMemoryData(dElapsed);
    showIOData("(final)", dElapsed);
    putchar('\n');
}


int main(int argc, char*argv[])
{
    int s;
    unsigned int i;
    double dVal, dElapsed;
    time_t start, tElapsed;
    pthread_attr_t attr;

    printf("\nTEST PROGRAM\n");

    /* Handle the command-line (includes validity verification and handling of --help) */
    if (!ParseArgs(argc, argv))
    {
        /* Nothing to do, but was help asked for? */
        if (helpShown)
            /* Yes, good command-line */
            exit(0);
        /* No, bad command-line */
        abort();
    }

    start = (time_t)-1;
    tElapsed = start;
    dElapsed = 0.0;

    /* Initialize the signal mask */
    setupDefaultSigMask();
    if (!setSigMask())
        goto finished;

    if (!setupSyncObjects())
    {
        goto finished;
    }

    if (!setupDataFile())
    {
        printf("Failed to setup data file %s\n", ioFilename.c_str());
        goto finished;
    }

    /* Setup any requested I/O threads */
    if (iothreads > 0)
    {
        if (SetupIOThreads() == 0)
        {
            while (nIOThreads < iothreads)
                sleep(1);
        }
    }
    printf("   Current I/O threads = %d\n", nIOThreads.load(std::memory_order_relaxed));
    dVal = memUsed.load(std::memory_order_relaxed);
    showScaledData("Memory used", 24, dVal, "B", true);

    /* Setup requested worker threads */
    if (SetupWorkerThreads() == 0)
    {
        while (nThreads.load(std::memory_order_relaxed) <= nIOThreads)
            sleep(1);
    }
    else
    {
        printf("Failed to setup worker threads\n");
    }
    putchar('\n');

    /* Ready to start, threads do almost all of the activity, main just waits
     * to end them all at the timeout or start new ones if there is capacity
     * and opportunity */
    printf("TESTING\n");
    start = time(NULL);
    tElapsed = (time_t)0;
    printf("       Current threads = %d\n", nThreads.load(std::memory_order_relaxed));
    dVal = memUsed.load(std::memory_order_relaxed);
    showScaledData("Memory used", 24, dVal, "B", true);
    putchar('\n');
    i = 0;
    while((tElapsed < (time_t)maxruntime) || ((tElapsed == (time_t)-1) && (i < maxruntime)))
    {
        if (sigStop.load(std::memory_order_relaxed))
        {
            printf("Stopped by signal\n");
            break;
        }

        /* If we have worker threads able to exit before program exit then
         * create a new thread at random if there's capacity in the settings */
        if (short_threads && (!EndAllThreads) && (nThreads < maxthreads) && (rand() >= RESTART_SCOPE))
        {
            if (verbose_flag)
                printf("Want to start another thread\n");
            s = pthread_attr_init(&attr);
            if (s == 0)
            {
                if (verbose_flag)
                    printf("Starting a new worker thread\n");
                s = startOneWorkerThread(-1, &attr);
                if (s != 0)
                {
                    if (verbose_flag)
                        printf("Failed to start a new thread\n");
                }
                s = pthread_attr_destroy(&attr);
                if (s != 0)
                {
                    if (verbose_flag)
                        printf("Failed to destroy thread attr for a new thread\n");
                    break;
                }
            }
            else
            {
                if (verbose_flag)
                    printf("Failed to initialize thread attr for a new worker\n");
            }
        }

        sleep(1);
        tElapsed = GetElapsedFrom(start);
        i++;
        if (Diagnose)
            printf("TICK (%d with %d threads) elapsed %ld, max %d\n", i, nThreads.load(std::memory_order_relaxed), tElapsed, maxruntime);
    }
    if (Diagnose)
        printf("FINISHING (CLEANUP)\n");

    /* If there is pending I/O, let it finish before killing threads */
    EndIOTasks();
    tElapsed = GetElapsedFrom(start);
    if (Diagnose)
        printf("FINISHING (ENDED I/O)\n");

    /* Now end all the threads */
    EndPThreads();
    if (Diagnose)
        printf("FINISHING (ENDED THREADS)\n");

    /* If we get here there should be no running threads that compete for the
     * nodes on the queues, no pending I/O for execution or completion and no
     * I/O threads */

finished:
    /* If the computed elapsed time is invalid use the number of runtime
     * loop iterations as-if they were seconds and if that isn't usable
     * assume 1 second */
    if (tElapsed != (time_t)-1)
    {
        tElapsed = (time_t)i;
        dElapsed = (int)tElapsed;
        if (dElapsed <= 0.0)
            dElapsed = 1.0;
    }
    putchar('\n');

    showIOData("(before cleanup)", 0.0);
    clearIOQueues();
    if (!cleanupDataFile())
        printf("  Failed to close/delete data file %s\n", ioFilename.c_str());

    (void)destroySyncObjects();

    showTestResult(dElapsed);

    exit(0);
}

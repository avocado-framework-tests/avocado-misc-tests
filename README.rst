Avocado Misc Tests
==================

This repository is dedicated to host any tests written using the Avocado[1]
API. It is being initially populated with tests ported from autotest
client tests repository, but it's not limited by that.

Once you have the avocado installed, you can run the tests like below::

    $ avocado run avocado-misc-tests/perf/stress.py
    JOB ID     : 0018adbc07c5d90d242dd6b341c87972b8f77a0b
    JOB LOG    : $HOME/avocado/job-results/job-2016-01-18T15.32-0018adb/job.log
    TESTS      : 1
     (1/1) avocado-misc-tests/perf/stress.py:Stress.test: PASS (62.67 s)
    RESULTS    : PASS 1 | ERROR 0 | FAIL 0 | SKIP 0 | WARN 0 | INTERRUPT 0
    JOB HTML   : $HOME/avocado/job-results/job-2016-01-18T15.32-0018adb/html/results.html
    TIME       : 62.67 s


Tests are be organized per category basis, each category with its own
directory.  Additionally, the tests are categorized by the use of the
following tags[2] by functional area:

* cpu - Exercises a system's CPU
* net - Exercises a system's network devices or networking stack
* storage - Exercises a system's local storage
* fs - Exercises a system's file system

Tags by architecture:

* x86_64 - Requires a x86_64 architecture
* power - Requires a Power architecture

Tags by access privileges:

* privileged - requires the test to be run with the most privileged,
  unrestricted privileges.  For Linux systems, this usually means the
  root account

References:
-----------

1. https://github.com/avocado-framework/avocado
2. http://avocado-framework.readthedocs.io/en/latest/WritingTests.html#categorizing-tests

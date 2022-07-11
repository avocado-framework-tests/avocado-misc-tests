Avocado Misc Tests
==================

This repository is dedicated to host any tests written using the Avocado[1]
API. It is being initially populated with tests ported from autotest
client tests repository, but it's not limited by that.

Once you have the avocado installed, you can run the tests like below::

    $ avocado run  avocado-misc-tests/generic/stress.py
    JOB ID     : 0018adbc07c5d90d242dd6b341c87972b8f77a0b
    JOB LOG    : $HOME/avocado/job-results/job-2016-01-18T15.32-0018adb/job.log
    TESTS      : 1
     (1/1) avocado-misc-tests/generic/stress.py:Stress.test: PASS (62.67 s)
    RESULTS    : PASS 1 | ERROR 0 | FAIL 0 | SKIP 0 | WARN 0 | INTERRUPT 0
    JOB HTML   : $HOME/avocado/job-results/job-2016-01-18T15.32-0018adb/html/results.html
    TIME       : 62.67 s

To run test that requires paramters, you'll need to populated the provided YAML
files in the corresponding ``*.py.data`` directory. In each directory, there
should be a README explaining what each parameter cooresponds to. Once you have
the YAML file populated you can run the test like below::

  # avocado run  avocado-misc-tests/io/common/bootlist_test.py -m avocado-misc-tests/io/common/bootlist_test.py.data/bootlist_test_network.yaml
  JOB ID     : bd3c103f1b2fff2d35b507f83a03d1ace4a008c5
  JOB LOG    : /root/avocado-fvt-wrapper/results/job-2021-04-15T14.33-bd3c103/job.log
   (1/3) avocado-misc-tests/io/common/bootlist_test.py:BootlisTest.test_normal_mode;run-8e25: PASS (0.99 s)
   (2/3) avocado-misc-tests/io/common/bootlist_test.py:BootlisTest.test_service_mode;run-8e25: PASS (0.69 s)
   (3/3) avocado-misc-tests/io/common/bootlist_test.py:BootlisTest.test_both_mode;run-8e25: PASS (1.36 s)
  RESULTS    : PASS 3 | ERROR 0 | FAIL 0 | SKIP 0 | WARN 0 | INTERRUPT 0 | CANCEL 0
  JOB HTML   : /root/avocado-fvt-wrapper/results/job-2021-04-15T14.33-bd3c103/results.html
  JOB TIME   : 13.43 s

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
Note*
* --test-runner runner  need to passed as avocado `run` command line as it default lagacy runner as most of the test in avocado misc test wrote in way to execute sequential manner so newer avocado (aka avocado 91 onwards we need to pass this option explicitly as implicit it uses nrunner)  
exmaple can be like ::

  # avocado run --test-runner runner avocado-misc-tests/generic/stress.py
  JOB ID     : 0018adbc07c5d90d242dd6b341c87972b8f77a0b
  JOB LOG    : $HOME/avocado/job-results/job-2021-11-12T10.32-001adw/job.log
  TESTS      : 1
  (1/1) avocado-misc-tests/generic/stress.py:Stress.test: PASS (62.67 s)
  RESULTS    : PASS 1 | ERROR 0 | FAIL 0 | SKIP 0 | WARN 0 | INTERRUPT 0
  JOB HTML   : $HOME/avocado/job-results/job--2021-11-12T10.32-001adw//html/results.html
  TIME       : 69.67 s

* For more details please refer 3rd point in References section.

References:
-----------

1. https://github.com/avocado-framework/avocado
2. https://avocado-framework.readthedocs.io/en/77.0/guides/writer/chapters/writing.html#categorizing-tests
3. https://avocado-framework.readthedocs.io/en/91.0/guides/contributor/chapters/runners.html

Contact information:
--------------------



If looking for help like the real-time discussion  we are available on the IRC channel  based on time zone 


IRC channel: irc.oftc.net #avocadoTest

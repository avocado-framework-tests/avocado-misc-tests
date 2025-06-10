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

To run test that requires parameters, you'll need to populated the provided YAML
files in the corresponding ``*.py.data`` directory. In each directory, there
should be a README explaining what each parameter corresponds to. Once you have
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
* Most of these tests in the repository still support serial run (test scenarios) Please use --max-parallel-tasks=1 command line param which restricts nrunner to execute tests in serial flow

Examples can be like::

 #avocado run --max-parallel-tasks=1 ras_lsvpd.py 
  JOB ID     : 6d7ad4e91fb1fbedf7959dd15ce2ff1181872245
  JOB LOG    : /root/avocado-fvt-wrapper/results/job-2023-01-02T22.51-6d7ad4e/job.log
  (1/6) ras_lsvpd.py:RASToolsLsvpd.test_vpdupdate: STARTED
  (1/6) ras_lsvpd.py:RASToolsLsvpd.test_vpdupdate: PASS (5.93 s)
  (2/6) ras_lsvpd.py:RASToolsLsvpd.test_lsvpd: STARTED
  (2/6) ras_lsvpd.py:RASToolsLsvpd.test_lsvpd: PASS (94.53 s)
  (3/6) ras_lsvpd.py:RASToolsLsvpd.test_lscfg: STARTED
  (3/6) ras_lsvpd.py:RASToolsLsvpd.test_lscfg: PASS (0.63 s)
  (4/6) ras_lsvpd.py:RASToolsLsvpd.test_lsmcode: STARTED
  (4/6) ras_lsvpd.py:RASToolsLsvpd.test_lsmcode: PASS (0.72 s)
  (5/6) ras_lsvpd.py:RASToolsLsvpd.test_lsvio: STARTED
  (5/6) ras_lsvpd.py:RASToolsLsvpd.test_lsvio: PASS (0.41 s)
  (6/6) ras_lsvpd.py:RASToolsLsvpd.test_locking_mechanism: STARTED
  (6/6) ras_lsvpd.py:RASToolsLsvpd.test_locking_mechanism: PASS (2.40 s)
  RESULTS    : PASS 6 | ERROR 0 | FAIL 0 | SKIP 0 | WARN 0 | INTERRUPT 0 | CANCEL 0
  JOB HTML   : /root/avocado-fvt-wrapper/results/job-2023-01-02T22.51-6d7ad4e/results.html
  JOB TIME   : 233.35 s  

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

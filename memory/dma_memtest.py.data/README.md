Overview
----------
dma_memtest is a test case that verifies the correctness of DMA transfers between memory and a DMA-capable device. It also tests the memory subsystem against heavy IO and DMA operations.

It is implemented based on the work of Doug Leford (http://people.redhat.com/dledford/memtest.shtml).

The test uses a series of DMA transfers to write data to a buffer in memory and then read it back, comparing the original data with the data read back from the buffer. The test is designed to detect any errors or inconsistencies in the DMA transfer process, which can be caused by a variety of factors such as hardware failures, driver bugs, or configuration issues.


Prerequisites
--------------
* To run dma_memtest, you will need a Linux system with a DMA-capable device and the appropriate device driver installed. You will also need Python 3.x and the avocado-framework package installed.


* The free disk space on the system must be 1.5 times the free primary memory on the system in order for the test to run.
Example : For 100G memory there should be at least 150G disk

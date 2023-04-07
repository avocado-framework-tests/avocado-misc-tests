Overview
----------
eatmemory is a test case that is designed to consume a specified amount of memory on a system to test the behavior of swap and the system in general when there is little free memory available with it. This can be useful for testing the memory capacity of a system or for stressing the system in order to measure its performance under heavy loads. Based on the size of memory supplied to this test, it allocates memory using the malloc() and then uses on memset() on it to make sure the page fault occurs.

Source : https://github.com/julman99/eatmemory/ (Julio Viera <julio.viera@gmail.com>)


Prerequisites
--------------
* To run eatmemory, you will need a Linux system with Python 3.x and the avocado-framework package installed.

* By default memory to test is 95% of the system's free memory. If you want to change that you can change the memory_to_test parameter in the yaml file.
For example : memory_to_test: '1G'
In this case the test runs on 1 GB memory of the system's entire memory.
Please make sure you don't pass the entire memory available in the system that could cause unexpected results or system OOM (out-of-memory).

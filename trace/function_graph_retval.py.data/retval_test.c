#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Avocado Test");
MODULE_DESCRIPTION("Test module for function graph return value tracing");

/* 
 * Test function that returns a specific value - noinline to ensure it
 * appears in trace 
 */
noinline int test_retval_func(int input)
{
    pr_info("test_retval: called with input=%d\n", input);
    return input * 2 + 42;
}

/* 
 * Another test function with different return value - noinline to ensure
 * it appears in trace 
 */
noinline long test_retval_large(void)
{
    pr_info("test_retval: returning large value\n");
    return 0x123456789ABCDEF0L;
}

/* Function that returns zero - noinline to ensure it appears in trace */
noinline int test_retval_zero(void)
{
    pr_info("test_retval: returning zero\n");
    return 0;
}

/* Function that returns negative - noinline to ensure it appears in trace */
noinline int test_retval_negative(void)
{
    pr_info("test_retval: returning negative\n");
    return -42;
}

static int __init test_retval_init(void)
{
    int result;
    long large_result;
    
    pr_info("test_retval: module loaded\n");
    
    /* Call test functions to generate trace data */
    result = test_retval_func(10);
    pr_info("test_retval: func(10) returned %d\n", result);
    
    large_result = test_retval_large();
    pr_info("test_retval: large() returned 0x%lx\n", large_result);
    
    result = test_retval_zero();
    pr_info("test_retval: zero() returned %d\n", result);
    
    result = test_retval_negative();
    pr_info("test_retval: negative() returned %d\n", result);
    
    return 0;
}

static void __exit test_retval_exit(void)
{
    pr_info("test_retval: module unloaded\n");
}

module_init(test_retval_init);
module_exit(test_retval_exit);

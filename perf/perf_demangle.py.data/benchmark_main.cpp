#include <benchmark/benchmark.h>

static __attribute__ ((noinline)) int my_really_big_function()
{
    for(size_t i = 0; i < 1000; ++i)
    {
        benchmark::DoNotOptimize(i % 5);
    }
    return 0;
}

static __attribute__ ((noinline)) void caller1()
{
    for(size_t i = 0; i < 1000; ++i)
    {
        benchmark::DoNotOptimize(my_really_big_function());
        benchmark::DoNotOptimize(i % 5);
    }
}

static __attribute__ ((noinline)) void myfun(benchmark::State& state)
{
    while(state.KeepRunning())
    {
        caller1();
    }
}

BENCHMARK(myfun);
BENCHMARK_MAIN();
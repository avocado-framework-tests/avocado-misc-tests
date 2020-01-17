BIN=numa_test
OFFL=softoffline
BENCH=bench_movepages
all: ${BIN} ${OFFL} ${BENCH}

%: %.c util.c
	cc -o $@ $^ -lpthread -lnuma -lhugetlbfs

clean:
	rm ${BIN} ${OFFL} ${BENCH}

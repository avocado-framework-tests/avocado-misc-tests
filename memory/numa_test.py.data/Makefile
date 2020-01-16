BIN=numa_test
OFFL=softoffline
all: ${BIN} ${OFFL}

%: %.c util.c
	cc -o $@ $^ -lpthread -lnuma -lhugetlbfs

clean:
	rm ${BIN} ${OFFL}

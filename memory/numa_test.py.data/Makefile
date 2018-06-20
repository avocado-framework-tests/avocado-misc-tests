BIN=numa_test
all: ${BIN}

%: %.c util.c
	cc -o $@ $^ -lpthread -lnuma -lhugetlbfs

clean:
	rm ${BIN}

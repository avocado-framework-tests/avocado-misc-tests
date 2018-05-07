BIN=numa_test
all: ${BIN}

%: %.c util.c
	cc -o $@ $^ -lpthread -lnuma

clean:
	rm ${BIN}

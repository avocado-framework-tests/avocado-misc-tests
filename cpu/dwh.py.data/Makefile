all: dwh

dwh: dwh.cpp
	g++ -O3 -D_FILE_OFFSET_BITS=64 -std=c++11 -Wall -Werror -lrt -pthread -o $@ dwh.cpp

clean:
	rm dwh

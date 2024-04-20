CUDA_HOME=/usr/local/cuda

all:	dgemm sgemm

dgemm:  xgemm.c
	gcc -DXGEMM_DOUBLE -DUSE_CUBLAS -DUSE_DOUBLE xgemm.c -I$(CUDA_HOME)/include -I. -o dgemm -L$(CUDA_HOME)/lib64 -lcudart -lcublas -lnvidia-ml -lm

sgemm:  xgemm.c
	gcc -DXGEMM_SINGLE -DUSE_CUBLAS -DUSE_DOUBLE xgemm.c -I$(CUDA_HOME)/include -I. -o sgemm -L$(CUDA_HOME)/lib64 -lcudart -lcublas -lnvidia-ml -lm

short_sg:
	./sgemm -m8000 -n5000 -k8000 -i1 -l1
short_dg:
	./dgemm -m8000 -n5000 -k8000 -i1 -l1

long_sg:
	./sgemm -m8000 -n5000 -k8000 -i100 -l100
long_dg:
	./dgemm -m8000 -n5000 -k8000 -i100 -l100

clean:
	rm -f dgemm sgemm

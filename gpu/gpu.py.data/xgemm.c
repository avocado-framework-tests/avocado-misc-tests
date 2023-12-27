/*
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See LICENSE for more details.
 * Copyright: 2017 IBM
 * Author: Pradeep Rammana - pradeep.ramanna@ibm.com
 */
#ifdef USE_MPI
#include <mpi.h>
#endif
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
#include <dlfcn.h>
#include <ctype.h>
#include <math.h>
#include <cuda_runtime.h>
#include <cublas.h>
#include <nvml.h>

#ifdef XGEMM_DOUBLE
#define mytype double
#define mygemm cublasDgemm
#endif

#ifdef XGEMM_SINGLE
#define mytype float
#define mygemm cublasSgemm
#endif

#define SWITCH_CHAR '-'

#define CHECK_CUDART(x) do { \
  cudaError_t res = (x); \
  if(res != cudaSuccess) { \
    fprintf(stderr, "%d : %s : CUDART: %s = %d (%s) at (%s:%d)\n", rank, host_name, #x, res, cudaGetErrorString(res),__FILE__,__LINE__); \
    exit(1); \
  } \
} while(0)

#define CHECK_CUBLAS(x) do { \
  cublasStatus_t cublasStatus = (x); \
  if(cublasStatus != CUBLAS_STATUS_SUCCESS) { \
    fprintf(stderr, "%d : %s : CUBLAS: %s = %d at (%s:%d)\n", rank, host_name, #x, cublasStatus,__FILE__,__LINE__); \
    exit(1); \
  } \
} while(0)

#define imin(a,b) (((a)<(b))?(a):(b))
#define imax(a,b) (((a)>(b))?(a):(b))

#define NSTREAMS (32)

int checkC(int m, int n, mytype *C);
double maxVariance = 0.0;
#ifdef XGEMM_DOUBLE
double allowedVariance = 1.0e-9;
#else
double allowedVariance = 1.0e-3;
#endif

int stringCmp( const void *a, const void *b)
{
     return strcmp(a,b);
}

int main(int argc, const char *argv[])
{

  unsigned int m, n, k, chunk;
  int dev,c,d,ntimes,loop,iter,pass;
  long long int i;
  size_t buffer_size;
  mytype *A,*B,*C, *Cz;
  mytype *A_d,*B_d[NSTREAMS],*C_d[NSTREAMS];
  size_t free_bytes, total_bytes;
  cudaEvent_t ev_start, ev_end;
  cudaStream_t stream[NSTREAMS];
  float gflops, ms;
  int nn, nq0=0, counter=0;
  struct cudaDeviceProp props;
  char mybus[16];
  unsigned int temp, power, clock, pcie_width, pcie_gen;
  unsigned int max_temp, max_power, min_clock, min_pcie_width, min_pcie_gen;
  nvmlReturn_t ret;
  nvmlDevice_t nvmldev;
#ifdef USE_MPI
  char host_name[MPI_MAX_PROCESSOR_NAME];
  char (*host_names)[MPI_MAX_PROCESSOR_NAME];
  MPI_Comm nodeComm;
#else
  char host_name[20]="local";
#endif
  int proc, name_len, color;
  int rank, nprocs, local_rank, local_procs;
  size_t bytes;

#ifdef USE_MPI
  MPI_Init(&argc, (char***)&argv);
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Comm_size(MPI_COMM_WORLD, &nprocs);
  MPI_Get_processor_name(host_name,&name_len);
//print to identify hanged nodes later
  printf("%d %s HERE\n",rank,host_name);

  bytes = nprocs * sizeof(char[MPI_MAX_PROCESSOR_NAME]);
  host_names = (char (*)[MPI_MAX_PROCESSOR_NAME]) malloc(bytes);
  strcpy(host_names[rank], host_name);
  for (proc=0; proc<nprocs; proc++)
  {
     MPI_Bcast(&(host_names[proc]),MPI_MAX_PROCESSOR_NAME, MPI_CHAR, proc, MPI_COMM_WORLD);
  }
  qsort(host_names, nprocs,  sizeof(char[MPI_MAX_PROCESSOR_NAME]), stringCmp);
  color = 0;
  for (proc=0; proc<nprocs; proc++)
  {
     if(proc>0&&strcmp(host_names[proc-1], host_names[proc])) color++;
     if(strcmp(host_name, host_names[proc]) == 0) break;
  }
  MPI_Comm_split(MPI_COMM_WORLD, color, 0, &nodeComm);
  MPI_Comm_rank(nodeComm, &local_rank);
  MPI_Comm_size(nodeComm, &local_procs);
#else
  rank=0; nprocs=1; local_rank=0;
#endif
  if(rank==0) printf("\n");
  if(rank==0) printf("# DGEMM COPY TEST\n");
  if(rank==0) printf("# Command line options: -m<size> -n<size> -k<size> -d<device> -i<iterations> -l<loops-per-iteration>\n");

  m = 53760; n = 7680; k = 768; d = local_rank; ntimes = 40; loop = 15;

  while (argc) {
        if (*argv[0] == SWITCH_CHAR) {
            switch (*(argv[0]+1)) {
            case 'm':
                m = (int)atoi(argv[0]+2);
                break;
            case 'n':
                n = (int)atoi(argv[0]+2);
                break;
            case 'k':
                k = (int)atoi(argv[0]+2);
                break;
            case 'd':
                d = (int)atoi(argv[0]+2);
                break;
            case 'i':
                ntimes = (int)atoi(argv[0]+2);
                break;
            case 'l':
                loop = (int)atoi(argv[0]+2);
                break;
            }
        }
        argc -= 1;
        argv++;
  }

  CHECK_CUDART( cudaSetDevice(d) );
  CHECK_CUDART( cudaGetDevice(&dev) );
  CHECK_CUDART( cudaGetDeviceProperties(&props, dev) );

  chunk = 128; // 128 * props.multiProcessorCount;

  buffer_size = (size_t)((size_t)(NSTREAMS*k*chunk) + (size_t)(NSTREAMS*chunk*m));

  sprintf(&mybus[0], "%04x:%02x:%02x.0", props.pciDomainID, props.pciBusID, props.pciDeviceID);

  nvmlInit();
  nvmlDeviceGetHandleByPciBusId(mybus, &nvmldev);

  CHECK_CUDART( cudaMalloc((void **)&A_d, m*k*sizeof(mytype)) );
  for(i=0;i<NSTREAMS;i++) { CHECK_CUDART( cudaMalloc((void **)&B_d[i], k*chunk*sizeof(mytype)) ); }
  for(i=0;i<NSTREAMS;i++) { CHECK_CUDART( cudaMalloc((void **)&C_d[i], m*chunk*sizeof(mytype)) ); }
  CHECK_CUDART( cudaMallocHost((void **)&A,  m*k*sizeof(mytype)) );
  CHECK_CUDART( cudaMallocHost((void **)&B,  n*k*sizeof(mytype)) );
  CHECK_CUDART( cudaMallocHost((void **)&C,  (size_t)m*(size_t)n*sizeof(mytype)) );
  CHECK_CUDART( cudaMallocHost((void **)&Cz, (size_t)m*(size_t)n*sizeof(mytype)) );
  CHECK_CUDART( cudaMemGetInfo(&free_bytes, &total_bytes) );

  for(i=0; i<m*k; i++){
    double r1 = (mytype)(1.+rand())/(mytype)(RAND_MAX+1.);
    double r2 = (mytype)(1.+rand())/(mytype)(RAND_MAX+1.);
    A[i] = (mytype)(sqrt(-10.0*log(r1))*cos(2.0*M_PI*r2)); 
  }
  for(i=0; i<n*k; i++){
    double r1 = (mytype)(1.+rand())/(mytype)(RAND_MAX+1.);
    double r2 = (mytype)(1.+rand())/(mytype)(RAND_MAX+1.);
    B[i] = (mytype)(sqrt(-10.0*log(r1))*cos(2.0*M_PI*r2));     
  }
  for(i=0; i<m*n; i++){
    C[i] = Cz[i] = 0.0;
  }

  CHECK_CUDART( cudaMemcpy(A_d, A, m*k*sizeof(mytype),cudaMemcpyHostToDevice) );
  CHECK_CUDART( cudaEventCreate(&ev_start) );
  CHECK_CUDART( cudaEventCreate(&ev_end) );
  for(i=0;i<NSTREAMS;i++) CHECK_CUDART( cudaStreamCreate(&stream[i]) );


  if(rank==0){
    printf("# Running on %d '%s'\n", nprocs, props.name);
    printf("# SMs = %d\n", props.multiProcessorCount);
    printf("# clock = %d\n", props.clockRate);
    printf("# GPU memory used: %d MB (free: %d MB)\n\n", (int)((sizeof(mytype)*buffer_size)>>20), (int)(free_bytes>>20));
  }

  if(rank==0){
    printf("# warmup... \n");
  }

  nq0=0,counter=0;
  while( (nn = n - nq0)>0 ){
    nn = imin( nn, chunk );
    cublasSetKernelStream( stream[counter%NSTREAMS] );
    CHECK_CUDART( cudaMemcpyAsync(  B_d[counter%NSTREAMS], B+(size_t)nq0*(size_t)k, nn*k*sizeof(mytype), cudaMemcpyHostToDevice, stream[counter%NSTREAMS] ) );
    CHECK_CUDART( cudaMemcpyAsync(  C_d[counter%NSTREAMS], Cz+(size_t)nq0*(size_t)m, nn*m*sizeof(mytype), cudaMemcpyHostToDevice, stream[counter%NSTREAMS] ) );
    mygemm('N', 'T', m, nn, k, 1.0, A_d, m, B_d[counter%NSTREAMS], nn, -1.0, C_d[counter%NSTREAMS], m);
    CHECK_CUDART( cudaMemcpyAsync(  C+(size_t)nq0*(size_t)m, C_d[counter%NSTREAMS], nn*m*sizeof(mytype), cudaMemcpyDeviceToHost, stream[counter%NSTREAMS] ) );     
    nq0 += nn;
    counter++;
  }
  nq0=0; counter=0;
  while( (nn = n - nq0)>0 ){
    nn = imin( nn, chunk );
    cublasSetKernelStream( stream[counter%NSTREAMS] );
    CHECK_CUDART( cudaMemcpyAsync(  B_d[counter%NSTREAMS], B+(size_t)nq0*(size_t)k, nn*k*sizeof(mytype), cudaMemcpyHostToDevice, stream[counter%NSTREAMS] ) );
    CHECK_CUDART( cudaMemcpyAsync(  C_d[counter%NSTREAMS], C+(size_t)nq0*(size_t)m, nn*m*sizeof(mytype), cudaMemcpyHostToDevice, stream[counter%NSTREAMS] ) );
    mygemm('N', 'T', m, nn, k, 1.0, A_d, m, B_d[counter%NSTREAMS], nn, -1.0, C_d[counter%NSTREAMS], m);   
    CHECK_CUDART( cudaMemcpyAsync(  C+(size_t)nq0*(size_t)m, C_d[counter%NSTREAMS], nn*m*sizeof(mytype), cudaMemcpyDeviceToHost, stream[counter%NSTREAMS] ) );
    nq0 += nn;
    counter++;
  }

  if(rank==0){
    printf("# Starting Test \n\n");
    printf("GPU\t\titer\tM\tN\tK\tloops\tms\t\tgflops\tclock\ttemp\tpower\tpcie\tgen\n");
  }
  for(iter = 0; iter<ntimes; iter++)
  {
    CHECK_CUDART( cudaEventRecord(ev_start, 0) );
    for(i = 0; i<loop; i++)
    {
      min_clock = 9999; max_temp = 0; max_power = 0; min_pcie_width = 9999; min_pcie_gen = 9999; 
      counter=0; nq0=0;
      while( (nn = n - nq0)>0 ){
        nn = imin( nn, chunk );
        cublasSetKernelStream( stream[counter%NSTREAMS] );
        CHECK_CUDART( cudaMemcpyAsync(  B_d[counter%NSTREAMS], B+(size_t)nq0*(size_t)k, nn*k*sizeof(mytype), cudaMemcpyHostToDevice, stream[counter%NSTREAMS] ) );
        CHECK_CUDART( cudaMemcpyAsync(  C_d[counter%NSTREAMS], Cz+(size_t)nq0*(size_t)m, nn*m*sizeof(mytype), cudaMemcpyHostToDevice, stream[counter%NSTREAMS] ) );
        mygemm('N', 'T', m, nn, k, 1.0, A_d, m, B_d[counter%NSTREAMS], nn, -1.0, C_d[counter%NSTREAMS], m);   
        CHECK_CUDART( cudaMemcpyAsync(  C+(size_t)nq0*(size_t)m, C_d[counter%NSTREAMS], nn*m*sizeof(mytype), cudaMemcpyDeviceToHost, stream[counter%NSTREAMS] ) );
        nq0 += nn;
        counter++;
      }
      CHECK_CUDART( cudaEventRecord(ev_end, stream[counter%NSTREAMS]) );

      counter=0; nq0=0;
      while( (nn = n - nq0)>0 ){
        nn = imin( nn, chunk );
        cublasSetKernelStream( stream[counter%NSTREAMS] );
        CHECK_CUDART( cudaMemcpyAsync(  B_d[counter%NSTREAMS], B+(size_t)nq0*(size_t)k, nn*k*sizeof(mytype), cudaMemcpyHostToDevice, stream[counter%NSTREAMS] ) );
        CHECK_CUDART( cudaMemcpyAsync(  C_d[counter%NSTREAMS], C+(size_t)nq0*(size_t)m, nn*m*sizeof(mytype), cudaMemcpyHostToDevice, stream[counter%NSTREAMS] ) );
        mygemm('N', 'T', m, nn, k, 1.0, A_d, m, B_d[counter%NSTREAMS], nn, -1.0, C_d[counter%NSTREAMS], m);
        CHECK_CUDART( cudaMemcpyAsync(  C+(size_t)nq0*(size_t)m, C_d[counter%NSTREAMS], nn*m*sizeof(mytype), cudaMemcpyDeviceToHost, stream[counter%NSTREAMS] ) );
        nq0 += nn;
        counter++;
      }
      CHECK_CUDART(cudaEventSynchronize(ev_end));

      ret = nvmlDeviceGetClockInfo(nvmldev, NVML_CLOCK_SM, &clock);
      if (NVML_SUCCESS != ret) fprintf(stderr,"node %s Can't get GPU clock: %s\n", host_name, nvmlErrorString(ret));
  
      ret = nvmlDeviceGetTemperature(nvmldev, NVML_TEMPERATURE_GPU, &temp);
      if (NVML_SUCCESS != ret) fprintf(stderr,"node %s Can't get GPU temp: %s\n", host_name, nvmlErrorString(ret));
  
/* XXX
      ret = nvmlDeviceGetPowerUsage(nvmldev, &power);
      if (NVML_SUCCESS != ret) fprintf(stderr,"node %s Can't get GPU power: %s\n", host_name, nvmlErrorString(ret));
*/
 
      ret = nvmlDeviceGetCurrPcieLinkWidth(nvmldev, &pcie_width);
      if (NVML_SUCCESS != ret) fprintf(stderr,"node %s Can't get GPU PCIe link width: %s\n", host_name, nvmlErrorString(ret));

      ret = nvmlDeviceGetCurrPcieLinkGeneration(nvmldev, &pcie_gen);
      if (NVML_SUCCESS != ret) fprintf(stderr,"node %s Can't get GPU PCIe link width: %s\n", host_name, nvmlErrorString(ret));

      min_clock = imin( clock, min_clock );
      max_temp = imax( temp, max_temp ); 
      max_power = imax( power, max_power );
      min_pcie_width = imin( pcie_width, min_pcie_width );
      min_pcie_gen = imin( pcie_gen, min_pcie_gen );
    }

    CHECK_CUDART( cudaEventRecord(ev_end, 0) );
    CHECK_CUDART( cudaEventSynchronize(ev_end) );
    CHECK_CUDART( cudaEventElapsedTime(&ms, ev_start, ev_end) );
    gflops = 2.0*loop*(1.0e-6*m*n*(2.0*k+1.0))/ms;
    if(gflops<1100){
      printf("\033[0;31m%s\t%d\t%d\t%d\t%d\t%d\t%5.1f\t\t%5.1f\t%d\t%d\t%d\tx%d\t%d\033[0m\n",
             mybus, iter,m, n, k, loop, ms, gflops,min_clock,max_temp,max_power/1000,min_pcie_width,min_pcie_gen);
      fflush(stdout);
    }else{
      printf("%s\t%d\t%d\t%d\t%d\t%d\t%5.1f\t\t%5.1f\t%d\t%d\t%d\tx%d\t%d\n",
             mybus, iter, m, n, k, loop, ms, gflops,min_clock,max_temp,max_power/1000,min_pcie_width,min_pcie_gen);

      fflush(stdout);

    }
  }

#ifdef USE_MPI
//print to identify hanged nodes
  printf("%d %s HERE\n",rank,host_name);


  MPI_Barrier(MPI_COMM_WORLD);
#endif

  CHECK_CUDART( cudaDeviceSynchronize() );
  if(rank==0) printf("\n# checking result... \n");

  pass = 1;
  for(i=0; i<m*n; i++) 
      if(fabs(C[i]) > allowedVariance) 
          pass = 0;
  checkC(m,n,C);
  printf("maxVariance = %g\n",maxVariance);

  //MPI ALLREDUCE test result ? or print failed hostnames

  if(pass==1) printf("# %s PASSED...\n",mybus);
  else        printf("!!!! %s FAILED !!!!\n",mybus); 

  if(rank==0) printf("# test complete...\n");
#ifdef USE_MPI
  MPI_Finalize();
#endif
  return 0;
}

int
checkC(int m, int n, mytype *C)
{
    int ii;

    for (ii=0; ii<m*n; ii++){
        if (C[ii] != 0.0){
          //printf("%10d  %10d  %10d  %g\n",ii,ii/m,ii%n,C[ii]);
            if (fabs((double)C[ii]) > maxVariance){
                maxVariance = (double)C[ii];
              //printf("new max: %10d  %10d  %10d  %g\n",ii,ii/m,ii%n,C[ii]);
            }
        }
        C[ii] = 0.0;
    }
}

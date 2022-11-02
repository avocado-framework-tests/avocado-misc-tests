#!/bin/bash
#Updated Script (15oct 23:53)
for i in `seq 1 1000`;
do
	time ppc64_cpu --smt=2
	ppc64_cpu --info
	sleep 2
	ppc64_cpu --smt
	time ppc64_cpu --smt=off
	ppc64_cpu --info
	sleep 2
	ppc64_cpu --smt
	time ppc64_cpu --smt=2
	ppc64_cpu --info
	sleep 2
	ppc64_cpu --smt
	time ppc64_cpu --smt=4
	ppc64_cpu --info
	sleep 2
	ppc64_cpu --smt
	time ppc64_cpu --smt=8
	ppc64_cpu --info
	sleep 2
	ppc64_cpu --smt
	time ppc64_cpu --smt=4
	ppc64_cpu --info
	sleep 2
	ppc64_cpu --smt
	time ppc64_cpu --smt=8
	ppc64_cpu --info
	sleep 2
	ppc64_cpu --smt
done

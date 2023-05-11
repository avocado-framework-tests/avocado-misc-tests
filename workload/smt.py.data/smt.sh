#!/bin/bash
#Updated Script (26Apr/2023 15:23)
for i in `seq 1 10000`;
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
        time ppc64_cpu --smt=on
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

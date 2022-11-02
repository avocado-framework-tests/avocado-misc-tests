set -x
while [ 1 ]
do
ppc64_cpu --offline-cores=0,1
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --online-cores=0,1
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --offline-cores=2,3,1,0,15,14,13,12,11
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --online-cores=2,3,15,14,13,12,11
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --offline-cores=4,5,6,7,8,9,10
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --online-cores=4,5,6,7
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --offline-cores=10,11,13,15
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --online-cores=8,9,10,11
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --offline-cores=8,9,10,11
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2

ppc64_cpu --cores-on=all
ppc64_cpu --cores-on
ppc64_cpu --info
sleep 2
done

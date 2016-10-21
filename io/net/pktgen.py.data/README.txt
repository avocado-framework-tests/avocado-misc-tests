This program generates network traffic packets. The number of packets, 
host and other inputs can be given in the yaml file.
REQUIRED INPUTS:
The following inputs are required to run the program 
else the test will take the default values.  
1. Network interface
2. No of packets to be generated
3. Clone_skb count
4. Host physical address
5. Host IP
6. Directory to store the results.
NOTE:
1. If the values in the yaml file are not specified, the default values will 
be taken.
2. If packtgen module is not found or the network is not reachable it will
skip the test.

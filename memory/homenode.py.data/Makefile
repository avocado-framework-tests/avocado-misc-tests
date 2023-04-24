
all : homenode

homenode : homenode.c
	gcc homenode.c -o $@ -lnuma -lhugetlbfs

clean :
	rm homenode

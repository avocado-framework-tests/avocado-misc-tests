all : node_move_pages

node_move_pages : node_move_pages.c
	gcc node_move_pages.c -o $@ -lhugetlbfs -lnuma

clean :
	rm node_move_pages

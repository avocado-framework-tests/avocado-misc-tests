all : node_move_pages

node_move_pages : node_move_pages.c
ifdef HAVE_HUGETLB_HEADER
        gcc node_move_pages.c -o $@ -lhugetlbfs -lnuma
else
        gcc node_move_pages.c -o $@ -lnuma
endif

clean :
	rm node_move_pages

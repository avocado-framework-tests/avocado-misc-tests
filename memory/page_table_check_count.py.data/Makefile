CC     ?= gcc
CFLAGS  = -Wall -Werror -O2 -std=gnu11

TARGETS = ptc_pte ptc_pmd ptc_bug

all: $(TARGETS)

ptc_pte: ptc_pte.c
	$(CC) $(CFLAGS) -o $@ $<

ptc_pmd: ptc_pmd.c
	$(CC) $(CFLAGS) -o $@ $<

ptc_bug: ptc_bug.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGETS)

.PHONY: all clean

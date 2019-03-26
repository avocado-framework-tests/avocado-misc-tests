#include <stdio.h>
void doit( int i ) {
	printf("i's addr : %p  i : %ld\n", &i, i);
}
int main() {
	doit(42);
	return 0;
}

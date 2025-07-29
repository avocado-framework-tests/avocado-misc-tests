#include <stdio.h>
int main() {
    int val = 100;
    int *ptr = &val;
    *ptr += 5;
    printf("%p\n", ptr);
    return 0;
}

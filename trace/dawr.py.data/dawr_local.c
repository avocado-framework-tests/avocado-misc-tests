#include <stdio.h>
int main() {
    int local = 42;
    local += 1;
    printf("%p\n", &local);
    return 0;
}

#include <stdio.h>

int arr[5] = {1, 2, 3, 4, 5};

int main() {
    arr[2] += 10;
    printf("%p\n", &arr[2]);
    return 0;
}

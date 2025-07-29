#include <stdio.h>

struct Data {
    int x;
    int y;
};

int main() {
    struct Data d = {10, 20};
    d.y += 5;
    printf("%p\n", &d.y);
    return 0;
}

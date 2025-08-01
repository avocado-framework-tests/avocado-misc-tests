/*
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *
 * See LICENSE for more details.
 *
 * Copyright: 2025 IBM
 * Author: SACHIN P B  <sachinpb@linux.ibm.com>
*/

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

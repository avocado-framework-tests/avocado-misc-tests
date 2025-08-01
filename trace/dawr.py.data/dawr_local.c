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
int main() {
    int local = 42;
    local += 1;
    printf("%p\n", &local);
    return 0;
}

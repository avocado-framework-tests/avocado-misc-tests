# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: 2022 IBM
# Author: Akanksha J N <akanksha@linux.ibm.com>

#include<stdio.h>
int a=10;
int b=50;
int c=100;
int main()
{	a+=10;
	b+=10;
	c+=10;
	printf("%p, %p ,%p/n", &a, &b, &c);
	return 0;
}

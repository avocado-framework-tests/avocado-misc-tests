#!/bin/bash
#author : Miklos Szeredi <mszeredi@redhat.com>
# TODO : will remove this file when it hosted in any test repo
TESTROOT=/var/tmp/test-root
SUBDIR=$TESTROOT/sub/dir

prepare()
{
	rm -rf $TESTROOT
	mkdir -p $SUBDIR

	for (( i = 0; i < 1000; i++ )); do
		for ((j = 0; j < 1000; j++)); do
			if test -e $SUBDIR/$i.$j; then
				echo "This should not happen!"
				exit 1
			fi
		done
		printf "%i (%s) ...\r" $((($i + 1) * $j)) `grep dentry /proc/slabinfo | sed -e "s/dentry *\([0-9]*\).*/\1/"`
	done
}

prepare
printf "\nStarting shrinking\n"
time rmdir $TESTROOT 2> /dev/null

prepare
printf "\nStarting parallel shrinking\n"
time (rmdir $SUBDIR & rmdir $TESTROOT 2> /dev/null & wait)

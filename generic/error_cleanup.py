#! /usr/bin/env python

from avocado import Test
from avocado import main


class error_cleanup(Test):
    """
    Raise an exception during tearDown()
    """

    def test(self):
        pass

    def tearDown(self):
        self.error("Test a bug in tearDown()")


if __name__ == "__main__":
    main()

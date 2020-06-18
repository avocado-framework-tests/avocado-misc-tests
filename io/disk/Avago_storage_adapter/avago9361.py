#!/usr/bin/env python

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
#
# Copyright: 2016 IBM
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
This scripts runs test on LSI9361
"""

from avocado import Test
from avocado.utils import process


class Avago9361(Test):

    """
    Here test cases related to LSI9361 adapter will be run
    """

    def setUp(self):
        """
        All basic set up for test case are done here
        """

        self.controller = int(self.params.get('controller', default='0'))
        self.tool_location = str(self.params.get('tool_location'))
        self.option = str(self.params.get('option'))
        self.value = str(self.params.get('value'))
        self.extra = str(self.params.get('extra'))
        self.show = self.params.get('show', default=True)

        cmd = "%s -v" % self.tool_location
        self.check_pass(cmd, "version of the tool")
        cmd = "%s show ctrlcount" % self.tool_location
        self.check_pass(cmd, "controleer count")
        cmd = "%s /c%d show" % (self.tool_location, self.controller)
        self.check_pass(cmd, "adapter details")
        cmd = "%s /c%d show all" % (self.tool_location, self.controller)
        self.check_pass(cmd, "'show all' o/p of the adapter")

    def test(self):
        """
        Function to set all adjustable values of the adapter
        """
        if self.show:
            cmd = "%s /c%d show %s" % (self.tool_location,
                                       self.controller, self.option)
            self.check_pass(cmd, "%s" % self.option)

        if self.extra == 'state':
            cmd = "%s /c%d set %s state=%s" % (self.tool_location,
                                               self.controller, self.option,
                                               self.value)
        else:
            cmd = "%s /c%d set %s=%s" % (self.tool_location,
                                         self.controller, self.option,
                                         self.value)
        if self.extra == 'type':
            cmd += " type=all"
        self.check_pass(cmd, "setting %s as %s" % (self.option,
                                                   self.value))

    def check_pass(self, cmd, errmsg):
        """
        Helper function to check, if the cmd is passed or failed
        """
        res = process.run(cmd, ignore_status=True, shell=True)
        if 'not support' in res.stdout_text:
            self.cancel('%s not supported' % errmsg)
        if res.exit_status != 0:
            self.fail('%s failed' % errmsg)

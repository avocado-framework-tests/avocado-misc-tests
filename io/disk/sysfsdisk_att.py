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
# Copyright: 2023 IBM
# Author: Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>

"""
Check all sysfs queue attributes by reading or writing different values
"""

import os
from avocado import Test
from avocado.utils import genio


class SysfsDisk_Att(Test):

    """
    Checks all Sysfs_Queue attributes
    """

    def setUp(self):
        """
        Reading required arguments from yaml file
        Setting up file paths
        """
        self.disk = self.params.get("disk", default="")
        if not self.disk:
            self.cancel("No disk input, please update yaml with disk")
        self.disk = self.disk.split("/")[-1]
        self.queue_param_disk_dir = os.path.join("/sys/block",
                                                 self.disk, "queue")
        self.attribute_name = self.params.get("attribute_name",
                                              default="None")
        self.attribute_values = self.params.get("values").split(" ")

    def test(self):
        """
        Read sysfs disk queue readable attributes
        Check sysfs disk queue attributes with different values
        """
        self.read_file_attributes()
        attribute_file = os.path.join(self.queue_param_disk_dir,
                                      self.attribute_name)
        for attribute_val in self.attribute_values:
            self.log.info(f"Writing value {attribute_val} to file {attribute_file}")
            genio.write_file(attribute_file, str(attribute_val))
            attribute_file_val = genio.read_file(attribute_file).rstrip("\n")
            if attribute_val != attribute_file_val:
                self.fail(f"{attribute_file} file updation with value"
                          f"{attribute_val} failed")

    def read_file_attributes(self):
        """
        Reads file content of all files in a directory
        f_name function accepts path and then returns absolute path
        Iterates through all files in a directory
        Tuple Format:(File Name, Value in File)
        Example: [(file1,file1_value),(file2,file2_value),........,(filen,filen_value)]
        """
        self.log.info(f"Reading attributes values from directory {self.queue_param_disk_dir}")

        def f_name(file_name):
            return os.path.join(self.queue_param_disk_dir, file_name)

        self.log.info([(each_file,
                      self.catch(lambda: genio.read_file(f_name(each_file)).rstrip("\n")))
                      for each_file in os.listdir(self.queue_param_disk_dir)
                      if os.access(f_name(each_file), os.R_OK) and
                      os.path.isfile(f_name(each_file))])

    def catch(self, func, handle=lambda excep: excep, *args, **kwargs):
        """
        Defined to handle exception while reading a file
        """
        try:
            self.fail("Found an exception while reading attribute from file")
            return func(*args, **kwargs)
        except Exception as exce:
            return handle(exce)

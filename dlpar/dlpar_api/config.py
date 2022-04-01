#!/usr/bin/env python
#
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
# Copyright: 2021 IBM
# Author: Ricardo Salveti <rsalveti@linux.vnet.ibm.com>
# Based on the config parser of the trac system, made by Christopher Lenz
# <cmlenz@gmx.de>

"""
Wrapper around ConfigParser to handle DLPAR testcases configuration.
"""
from configparser import ConfigParser, NoOptionError, NoSectionError
from os import path

__all__ = ['TestConfig']


class TestConfig:
    """Base class of the configuration parser"""

    def __init__(self, filename="dlpar.conf"):
        self.filename = filename
        if not path.isfile(self.filename):
            raise IOError("File '%s' not found" % (self.filename))
        self.parser = ConfigParser()
        self.parser.read(self.filename)

    def get(self, section, name, default=None):
        """Get the value of a option.

        Section of the config file and the option name.
        You can pass a default value if the option doesn't exist.
        """
        if not self.parser.has_section(section):
            raise NoSectionError("No section: %s" % section)
        elif not self.parser.has_option(section, name):
            if not default:
                raise NoOptionError("No option: %s" % name)
            else:
                return default
        return self.parser.get(section, name)

    def set(self, section, option, value):
        """
        Set an option.

        This change is not persistent unless saved with 'save()'.
        """
        if not self.parser.has_section(section):
            self.parser.add_section(section)
        return self.parser.set(section, option, value)

    def remove(self, section, option):
        """Remove an option."""
        if self.parser.has_section(section):
            self.parser.remove_option(section, option)

    def save(self):
        """Save the configuration file with all modifications"""
        if not self.filename:
            return
        fileobj = open(self.filename, 'w')
        try:
            self.parser.write(fileobj)
        finally:
            fileobj.close()

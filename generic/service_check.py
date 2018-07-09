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
# Copyright: 2016 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>
#
# Copyright: 2014 Red Hat Inc.
# Besed on the Sample Idea from:
# https://github.com/autotest/virt-test/blob/master/samples/service.py

import os
import ConfigParser
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.service import SpecificServiceManager
from avocado.utils import distro
from avocado.utils.wait import wait_for
from avocado.utils.software_manager import SoftwareManager


class service_check(Test):

    def test(self):
        detected_distro = distro.detect()
        parser = ConfigParser.ConfigParser()
        parser.read(self.get_data('services.cfg'))
        services_list = parser.get(detected_distro.name, 'services').split(',')

        smm = SoftwareManager()
        deps = []

        if detected_distro.name == 'SuSE':
            deps.extend(['ppc64-diag', 'libvirt-daemon'])
            if detected_distro.version >= 15:
                services_list.append('firewalld')
            else:
                services_list.append('SuSEfirewall2')
        elif detected_distro.name == 'Ubuntu':
            deps.extend(['opal-prd'])
            if detected_distro.version >= 17:
                services_list.remove('networking')

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(' %s is needed for the test to be run' % package)

        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            services_list.extend(['opal_errd', 'opal-prd'])
            if os.path.exists('/proc/device-tree/bmc'):
                services_list.remove('opal_errd')
        else:
            services_list.extend(['rtas_errd'])
        services_failed = []
        runner = process.run

        for service in services_list:
            service_obj = SpecificServiceManager(service, runner)
            self.log.info("Checking %s service" % service)
            if service_obj.is_enabled() is False:
                self.log.info("%s service Not Found !!!" % service)
                services_failed.append(service)
                continue
            original_status = service_obj.status()
            if original_status is True:
                service_obj.stop()
                if not wait_for(lambda: not service_obj.status(), 10):
                    self.log.info("Fail to stop %s service" % service)
                    services_failed.append(service)
                    continue
                service_obj.start()
                wait_for(service_obj.status, 10)
            else:
                service_obj.start()
                if not wait_for(service_obj.status, 10):
                    self.log.info("Fail to start %s service" % service)
                    services_failed.append(service)
                    continue
                service_obj.stop()
                wait_for(lambda: not service_obj.status(), 10)
            if not service_obj.status() is original_status:
                self.log.info("Fail to restore original status of the %s"
                              "service" % service)
                services_failed.append(service)

        if services_failed:
            self.fail("List of services failed: %s" % services_failed)
        else:
            self.log.info("All Services Passed the ON/OFF test")


if __name__ == "__main__":
    main()

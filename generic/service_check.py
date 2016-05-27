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

import ConfigParser
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.service import SpecificServiceManager
from avocado.utils import distro
from avocado.utils.wait import wait_for


class service_check(Test):

    def test(self):
        detected_distro = distro.detect()
        parser = ConfigParser.ConfigParser()
        config_file = self.datadir + '/services.cfg'
        parser.read(config_file)
        services_list = parser.get(detected_distro.name, 'services').split(',')
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
                services_failed.append(services)

        if services_failed:
            self.fail("List of services failed: %s" % services_failed)
        else:
            self.log.info("All Services Passed the ON/OFF test")

if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
#
# Copyright @ 2020 OPS, YY Inc.
#
# Author: Jinlong Yang
#

import logging

import libvirt

LOG = logging.getLogger(__name__)


class LibvirtDriver:

    def connect(self, ip):
        """Get a connection to the hypervisor.
        """
        uri  = 'qemu+ssh://root@%(ip)s/system' % {'ip': ip}
        self.conn = libvirt.open(uri)
        if self.conn is None:
            raise Exception('Connnect to hypervisor: %s failed.' % ip)

    def define(self, xml):
        """Define a domain, but does not start it.

        This definition is persistent, until explicitly undefined with
        virDomainUndefine(). A previous definition for this domain would be
        overridden if it already exists.

        virDomainFree should be used to free the resources after the domain
        object is no longer needed.
        """
        domain = self.conn.defineXML(xml)
        LOG.info('Define a instance: %s on hypervisor: %s success.'
                 % (domain.name(), self.conn.getHostname()))
        return domain

    def undefine(self, domain):
        """ Undefine a domain.

        If the domain is running, it's converted to transient domain,
        without stopping it. If the domain is inactive, the domain
        configuration is removed.
        """
        return domain.undefine()

    def launch(self, domain):
        """Launch a defined domain.

        If the call succeeds the domain moves from the defined to the running
        domains pools. The domain will be paused only if restoring from managed
        state created from a paused domain.
        """
        return domain.create()

    def destroy(self, domain):
        """Destroy the domain object.

        The running instance is shutdown if not down already and all resources
        used by it are given back to the hypervisor.
        """
        return domain.destory()

    def get_domain(self, uuid):
        """Return domain instance name.
        """
        domain = self.conn.lookupByUUIDString(uuid)
        return domain.name()

    def list_domain(self):
        """Return all running domains.
        """
        domain_list = self.conn.listAllDomains()
        for domain in domain_list:
            print (domain.name())

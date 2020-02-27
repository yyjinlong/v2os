# -*- coding: utf-8 -*-
#
# Copyright @ 2020 OPS, YY Inc.
#
# Author: Jinlong Yang
#

import logging

from osmo.base import Application
from osmo.db import get_session

from v2os.migrate.instance import InstanceManager
from v2os.migrate.l3 import L3Manager
from v2os.migrate.l2 import LibvirtManager

LOG = logging.getLogger(__name__)


class Instance:

    def __init__(self):
        self.uuid = None


class KVMInstance:

    def __init__(self):
        self.instance = Instance()
        self.instance_ref = None
        self.instance_uuid = None

    def build_instance(self, session):
        instance_manager = InstanceManager(session)
        instance_manager.check()
        LOG.info('Check instance migrate param passed.')

        self.instance_ref = instance_manager.write()
        self.instance_uuid = self.instance_ref.uuid
        self.instance.uuid = self.instance_ref.uuid
        LOG.info('Write instance: %s for database info success.'
                 % self.instance_uuid)

    def build_l3(self, session):
        l3_manager = L3Manager(session, self.instance_ref)
        l3_manager.write()
        LOG.info('Write instance: %s for l3(network) info success.'
                 % self.instance_uuid)

    def build_l2(self, session):
        l2_manager = LibvirtManager(session, self.instance_ref)
        l2_manager.build()
        LOG.info('Build instance: %s for l2(vlan、bridge、directory) '
                 'info success.' % self.instance_uuid)


class Nova:

    def __init__(self):
        self.builder = None

    def constuct(self, builder):
        self.builder = builder
        session = get_session()
        with session.begin(subtransactions=True):
            [step for step in (builder.build_instance(session),
                               builder.build_l3(session),
                               builder.build_l2(session))]

    @property
    def instance(self):
        return self.builder.instance.uuid


class Migrator(Application):
    name = 'migrator'
    version = '0.1'

    def __init__(self):
        super(Migrator, self).__init__()

    def run(self):
        nova = Nova()
        nova.constuct(KVMInstance())
        LOG.info('Build instance: %s on kvm platform success.' % nova.instance)


v2os_migrate = Migrator().entry_point()

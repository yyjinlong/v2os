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


class Migrator(Application):
    name = 'migrator'
    version = '0.1'

    def __init__(self):
        super(Migrator, self).__init__()

    def run(self):
        session = get_session()
        with session.begin(subtransactions=True):
            instance_manager = InstanceManager(session)
            instance_manager.check()
            LOG.info('** Check migrate instance param pass.')

            instance_ref = instance_manager.write()
            instance_uuid = instance_ref.uuid
            LOG.info('** Write instance: %s info success.' % instance_uuid)

            l3_manager = L3Manager(session, instance_ref)
            l3_manager.write()
            LOG.info('** Write instance: %s for l3(network) info success.'
                     % instance_uuid)

            l2_manager = LibvirtManager(session, instance_ref)
            l2_manager.build()
            LOG.info('** Build instance: %s for l2(vlan、bridge、directory) '
                     'info success.' % instance_uuid)


v2os_migrate = Migrator().entry_point()

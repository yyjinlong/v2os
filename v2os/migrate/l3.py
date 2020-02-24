# -*- coding: utf-8 -*-
#
# Copyright @ 2020 OPS, YY Inc.
#
# Author: Jinlong Yang
#

import json
import logging
from datetime import datetime

from dotmap import DotMap
from oslo_config import cfg

from v2os.migrate.manager import Manager
from v2os import objects

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

vm_opts = [
    cfg.IntOpt('vlan', default=0, help='nova network.'),
]

CONF.register_cli_opts(vm_opts, 'VM')


class L3Manager(Manager):

    def __init__(self, session, instance_ref):
        self.session = session
        self.instance_ref = instance_ref
        self.instance_uuid = instance_ref.uuid

    def write(self):
        network_id = self.read_network_id()
        self.ip = self.generate_ip_address(network_id)
        virtual_interface_id = self.create_virtual_interface(network_id)
        LOG.info('step9 write instance: %s map virtual interface id: %s '
                 'success.' % (self.instance_uuid, virtual_interface_id))

        self.update_fixed_ip(network_id, virtual_interface_id)
        self.write_instance_info_cache()
        LOG.info('step11 write instance: %s instance info cache success.'
                 % self.instance_uuid)

    def read_network_id(self):
        network_ref = self.session.query(objects.Network)\
                .filter(objects.Network.vlan == CONF.VM.vlan)\
                .first()
        return network_ref.id

    def create_virtual_interface(self, network_id):
        """Create the instance of virtual interface.
        """
        vif_ref = objects.VirtualInterface()
        vif_ref.address = self.generate_mac_address()
        vif_ref.network_id = network_id
        vif_ref.instance_uuid = self.instance_uuid
        vif_ref.uuid = self.generate_uuid()
        vif_ref.created_at = datetime.now()
        vif_ref.deleted = 0
        self.session.add(vif_ref)
        self.session.flush()
        return vif_ref.id

    def update_fixed_ip(self, network_id, virtual_interface_id):
        """Update the instance had been used ip info.
        """
        fixed_ip_ref = self.session.query(objects.FixedIp)\
                .filter(objects.FixedIp.network_id == network_id)\
                .filter(objects.FixedIp.address == self.ip)\
                .first()
        if fixed_ip_ref:
            fixed_ip_ref.instance_uuid = self.instance_uuid
            fixed_ip_ref.updated_at = datetime.now()
            fixed_ip_ref.leased = 1     # NOTE(该ip已经租用给dhcp网桥)
            fixed_ip_ref.allocated = 1  # NOTE(该ip已经分配)
            fixed_ip_ref.virtual_interface_id = virtual_interface_id
            fixed_ip_ref.updated_at = datetime.now()
            LOG.info('step10 update instance: %s map fixed ip: %s info '
                     'success.' % (self.instance_uuid, self.ip))

    def read_network_info(self):
        vif_ref = self.session.query(objects.VirtualInterface)\
                .filter(objects.VirtualInterface.instance_uuid == self.instance_uuid)\
                .first()

        network_ref = self.session.query(objects.Network)\
                .filter(objects.Network.vlan == CONF.VM.vlan)\
                .first()

        fixed_ip_ref = self.session.query(objects.FixedIp)\
                .filter(objects.FixedIp.instance_uuid == self.instance_uuid)\
                .first()

        # NOTE(cache: virtual interface info)
        cache = DotMap()
        cache.profile = None
        cache.ovs_interfaceid = None
        cache.preserve_on_delete = False
        cache.devname = None
        cache.vnic_type = 'normal'
        cache.qbh_params = None
        cache.meta = {}
        cache.details = {}
        cache.address = vif_ref.address
        cache.active = False
        cache.id = vif_ref.uuid
        cache.type = 'bridge'
        cache.qbg_params = None

        # NOTE(cache -> network: vlan info)
        network = DotMap()
        network.bridge = network_ref.bridge
        network.id = network_ref.uuid
        network.label = network_ref.label

        # NOTE(network -> meta)
        network.meta.multi_host = network_ref.multi_host
        network.meta.vlan = network_ref.vlan
        network.meta.bridge_interface = network_ref.bridge_interface
        network.meta.tenant_id = network_ref.project_id
        network.meta.should_create_vlan = True
        network.meta.should_create_bridge = True

        # NOTE(network -> subnets)
        subnet = DotMap()
        subnet.version = 4
        subnet.routes = []
        subnet.cidr = network_ref.cidr

        # NOTE(subnet -> meta)
        subnet.meta.dhcp_server = network_ref.dhcp_server

        # NOTE(subnet -> gateway)
        subnet.gateway.meta = {}
        subnet.gateway.version = 4
        subnet.gateway.type = 'gateway'
        subnet.gateway.address = network_ref.gateway

        # NOTE(subnet -> ips)
        ip = DotMap()
        ip.meta = {}
        ip.version = 4
        ip.type = 'fixed'
        ip.floating_ips = []
        ip.address = fixed_ip_ref.address
        subnet.ips = [ip]

        # NOTE(subnet -> dns)
        dns = DotMap()
        dns.meta = {}
        dns.version = 4
        dns.type = 'dns'
        dns.address = network_ref.dns1
        subnet.dns = [dns]

        network.subnets = [subnet]
        cache.network = network
        return [cache.toDict()]

    def write_instance_info_cache(self):
        """Represents a cache of information about an instance.
        """
        network_info = self.read_network_info()
        instance_cache_ref = objects.InstanceInfoCache()
        instance_cache_ref.network_info = json.dumps(network_info)
        instance_cache_ref.instance_uuid = self.instance_uuid
        instance_cache_ref.created_at = datetime.now()
        instance_cache_ref.deleted = 0
        self.session.add(instance_cache_ref)

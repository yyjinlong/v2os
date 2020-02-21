# -*- coding: utf-8 -*-
#
# Copyright @ 2020 OPS, YY Inc.
#
# Author: Jinlong Yang
#

import uuid
import time
import random
import logging
from datetime import datetime

from osmo.db import model_query
from sqlalchemy.sql.expression import asc

from v2os import objects

LOG = logging.getLogger(__name__)

_ISO8601_TIME_FORMAT = '%Y-%m-%dT%H:%M:%S'
_ISO8601_TIME_FORMAT_SUBSECOND = '%Y-%m-%dT%H:%M:%S.%f'


class Manager:

    def generate_uuid(self):
        """Generate an instance unique id(36bit).
        """
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, str(time.time())))

    def generate_mac_address(self):
        """Generate an Ethernet MAC address.
        """
        # NOTE(vish): We would prefer to use 0xfe here to ensure that linux
        #             bridge mac addresses don't change, but it appears to
        #             conflict with libvirt, so we use the next highest octet
        #             that has the unicast and locally administered bits set
        #             properly: 0xfa.
        #             Discussion: https://bugs.launchpad.net/nova/+bug/921838
        mac = [0xfa, 0x16, 0x3e,
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff)]
        return ':'.join(map(lambda x: "%02x" % x, mac))

    def generate_ip_address(self):
        """Gererate ip address.
        """
        # NOTE(从已创建的vlan中取出一个ip. 要求:
        #      没有预留的且没有分配过实例的; 同时要按updated_at升序.
        fixed_ip = model_query(objects.FixedIp)\
                .filter(objects.FixedIp.reserved == False)\
                .filter(objects.FixedIp.instance_uuid == None)\
                .filter(objects.FixedIp.host == None)\
                .order_by(asc(objects.FixedIp.updated_at))\
                .first()
        return fixed_ip.address

    def generate_uid(self, topic, size=8):
        """Generate an instance unique reservation id(8 bit).
        """
        characters = '01234567890abcdefghijklmnopqrstuvwxyz'
        choices = [random.choice(characters) for _ in range(size)]
        return '%s-%s' % (topic, ''.join(choices))

    def generate_request_id(self):
        """Generate an instance request uuid.
        """
        return 'req-' + str(uuid.uuid4())

    def isotime(self, at=None, subsecond=False):
        """Stringify time in ISO 8601 format.
        """
        if not at:
            at = datetime.utcnow()
        st = at.strftime(_ISO8601_TIME_FORMAT
                         if not subsecond
                         else _ISO8601_TIME_FORMAT_SUBSECOND)
        tz = at.tzinfo.tzname(None) if at.tzinfo else 'UTC'
        st += ('Z' if tz == 'UTC' else tz)
        return st

    def strtime(self, at):
        return at.strftime('%Y-%m-%d %H:%M:%S')

    def primitive_vcpu_model(self, cpu):
        """Generate obj from primitive vcpu model.
        """
        object_changes = [
            'vendor', 'features', 'model', 'topology', 'arch', 'match', 'mode']
        obj = {
            'nova_object.version': '1.0',
            'nova_object.changes': object_changes,
            'nova_object.name': 'VirtCPUModel',
            'nova_object.data': {
                'vendor': None,
                'features': [],
                'mode': 'host-model',
                'model': None,
                'arch': None,
                'match': 'exact',
                'topology': {
                    'nova_object.version': '1.0',
                    'nova_object.changes': ['cores', 'threads', 'sockets'],
                    'nova_object.name': 'VirtCPUTopology',
                    'nova_object.data': {
                        'cores': 1,
                        'threads': 1,
                        'sockets': cpu
                    },
                    'nova_object.namespace': 'nova'
                }
            },
            'nova_object.namespace': 'nova'
        }
        return obj

    def primitive_flavor(self, flavor_data):
        """Generate obj from primitive flavor.
        """
        obj = {
            'new': None,
            'old': None,
            'cur': {
                'nova_object.version': '1.1',
                'nova_object.name': 'Flavor',
                'nova_object.data': flavor_data,
                'nova_object.namespace': 'nova'
            }
        }
        return obj

    def generate_instance_name(self, instance_id):
        """Generate instance template name. such as: instance-00000001
        """
        return 'instance-%08x' % instance_id

    def get_hypervisor_ip(self, hostname):
        compute_ref = model_query(objects.ComputeNode)\
                .filter(objects.ComputeNode.host == hostname)\
                .first()
        return compute_ref.host_ip


# -*- coding: utf-8 -*-
#
# Copyright @ 2020 OPS, YY Inc.
#
# Author: Jinlong Yang
#

import re
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
    cfg.StrOpt('os', default='centos-6.9',
               help='instance os type, such as: centos-6.7、centos-6.9'),
    cfg.IntOpt('cpu', default=4, help='instance cpu number.'),
    cfg.IntOpt('mem', default=4, help='instance mem size(G).'),
    cfg.IntOpt('disk', default=150, help='instance disk size(G).'),
    cfg.IntOpt('vlan', default=0, help='nova network.'),
    cfg.StrOpt('hostname', default='', help='instance hostname.'),
    cfg.StrOpt('hypervisor', default='', help='instance of hypervisor.'),
]

keystone_opts = [
    cfg.StrOpt('user_id', default='', help='current user id'),
    cfg.StrOpt('tenant_id', default='', help='current tenant id'),
]

glance_opts = [
    cfg.StrOpt('image_ref', default='', help='current image id')
]

nova_opts = [
    cfg.StrOpt('key_name', default='admin', help='tenant key name.'),
    cfg.StrOpt('security_group', default='default', help='security group.')
]

CONF.register_cli_opts(vm_opts, 'VM')
CONF.register_opts(keystone_opts, 'KEYSTONE')
CONF.register_opts(glance_opts, 'GLANCE')
CONF.register_opts(nova_opts, 'NOVA')


class InstanceManager(Manager):

    def __init__(self, session):
        self.session = session
        self.instance_uuid = self.generate_uuid()

    def check(self):
        if not CONF.VM.os or not CONF.VM.vlan or \
           not CONF.VM.cpu or not CONF.VM.mem or not CONF.VM.disk or \
           not CONF.VM.hostname or not CONF.VM.hypervisor:
            raise Exception('参数: os、vlan、cpu、mem、disk、hostname、'
                            'hypervisor不能为空!')
        if CONF.VM.cpu > 64:
            raise Exception('cpu核数不能超过64核!')
        if CONF.VM.mem > 256:
            raise Exception('内存不能大于256G!')
        if not re.search('\w*-\d*.\d*', CONF.VM.os):
            raise Exception('os值错误, 正确如: centos-6.9、centos-7.5...')

    def write(self):
        key_data = self.read_key_data()

        instance_type_id = self.read_instance_type()
        if instance_type_id is None:
            raise Exception('给定规格不匹配!')
        LOG.info('step1 read instance: %s instance type(flavor) id: %d'
                 % (self.instance_uuid, instance_type_id))

        zone = self.read_zone()
        LOG.info('step2 read instance: %s availability zone: %s'
                 % (self.instance_uuid, zone))

        # NOTE(create instance)
        instance_ref = objects.Instance()
        instance_ref.user_id = CONF.KEYSTONE.user_id
        instance_ref.project_id = CONF.KEYSTONE.tenant_id
        instance_ref.image_ref = self.read_image()
        instance_ref.kernel_id = ''
        instance_ref.ramdisk_id = ''
        instance_ref.hostname = CONF.VM.hostname
        instance_ref.launch_index = 0
        instance_ref.key_name = CONF.NOVA.key_name
        instance_ref.key_data = key_data
        instance_ref.power_state = 1
        instance_ref.vm_state = 'active'
        instance_ref.vcpus = CONF.VM.cpu
        instance_ref.memory_mb = CONF.VM.mem * 1024
        instance_ref.root_gb = CONF.VM.disk
        instance_ref.ephemeral_gb = 0
        instance_ref.host = CONF.VM.hypervisor
        instance_ref.node = CONF.VM.hypervisor
        instance_ref.instance_type_id = instance_type_id
        instance_ref.reservation_id = self.generate_uid('r')
        instance_ref.launched_at = datetime.now()
        instance_ref.availability_zone = zone
        instance_ref.display_name = CONF.VM.hostname
        instance_ref.display_description = CONF.VM.hostname
        instance_ref.launched_on = CONF.VM.hypervisor
        instance_ref.locked = False
        instance_ref.uuid = self.instance_uuid
        instance_ref.root_device_name = '/dev/vda'
        instance_ref.config_drive = ''
        instance_ref.auto_disk_config = False
        instance_ref.shutdown_terminate = 0
        instance_ref.disable_terminate = 0
        self.session.add(instance_ref)
        self.session.flush()
        LOG.info('step3 write instance: %s info: %s success.'
                 % (self.instance_uuid, CONF.VM.hostname))

        self.write_security_group()
        LOG.info('step4 write instance: %s for security group success.'
                 % self.instance_uuid)

        self.write_block_device_mapping()
        LOG.info('step5 write instance: %s for block device mapping '
                 'success.' % self.instance_uuid)

        self.write_instance_system_metadata()
        LOG.info('step6 write instance: %s for instance system '
                 'metadata success.' % self.instance_uuid)

        self.write_instance_extra(instance_type_id)
        LOG.info('step7 write instance: %s for instance extra success.'
                 % self.instance_uuid)

        self.write_instance_actions()
        LOG.info('step8 write instance: %s build action and event success.'
                 % self.instance_uuid)
        return instance_ref

    def read_image(self):
        # NOTE(获取迁移的虚拟机镜像uuid
        #      约定: 在OpenStack集群上创建一个vcenter-4_4_150.x86_64镜像.
        #      方法: 以一个正常的centos镜像上传, 镜像名称设置为这个.)
        return CONF.GLANCE.image_ref

    def read_key_data(self):
        key_name = CONF.NOVA.key_name
        key_pair_ref = self.session.query(objects.KeyPair)\
                .filter(objects.KeyPair.name == key_name)\
                .first()
        return key_pair_ref.public_key

    def read_instance_type(self):
        flavor_suffix = '%d_%d_%d' % (CONF.VM.cpu, CONF.VM.mem, CONF.VM.disk)
        instance_type_ref_list = self.session.query(objects.InstanceTypes)\
                .filter(objects.InstanceTypes.name.like('%' + flavor_suffix + '%'))\
                .all()
        for model in instance_type_ref_list:
            if model.name.find(CONF.VM.os) != -1:
                return model.id
        return None

    def read_zone(self):
        aggregate_ref_list = self.session.query(objects.Aggregate).all()
        for model in aggregate_ref_list:
            host_list = [m.host for m in model._hosts if m]
            if CONF.VM.hypervisor in host_list:
                return model.name
        return None

    def read_flavor_info(self, instance_type_id):
        instance_type_ref = self.session.query(objects.InstanceTypes)\
                .filter(objects.InstanceTypes.id == instance_type_id)\
                .first()
        flavor = DotMap()
        flavor.id = instance_type_ref.id
        flavor.name = instance_type_ref.name
        flavor.flavorid = instance_type_ref.flavorid
        flavor.vcpus = instance_type_ref.vcpus
        flavor.memory_mb = instance_type_ref.memory_mb
        flavor.root_gb = instance_type_ref.root_gb
        flavor.ephemeral_gb = instance_type_ref.ephemeral_gb
        flavor.swap = instance_type_ref.swap
        flavor.rxtx_factor = instance_type_ref.rxtx_factor
        flavor.vcpu_weight = instance_type_ref.vcpu_weight
        flavor.disabled = instance_type_ref.disabled
        flavor.is_public = instance_type_ref.is_public
        flavor.created_at = self.isotime(instance_type_ref.created_at)
        flavor.updated_at = None
        flavor.deleted_at = None
        flavor.deleted = instance_type_ref.deleted
        flavor.extra_specs = {}
        return flavor.toDict()

    def read_security_group_id(self, security_group_name):
        security_group_ref = self.session.query(objects.SecurityGroup)\
                .filter(objects.SecurityGroup.name == security_group_name)\
                .first()
        return security_group_ref.id

    def write_instance_extra(self, instance_type_id):
        """Create the instance of primitive extar info.
        """
        pci_requests_text = json.dumps([])

        flavor_data = self.read_flavor_info(instance_type_id)
        flavor_text = json.dumps(self.primitive_flavor(flavor_data))

        vcpu_model_text = json.dumps(self.primitive_vcpu_model(CONF.VM.cpu))

        extra_ref = objects.InstanceExtra()
        extra_ref.instance_uuid = self.instance_uuid
        extra_ref.pci_requests = pci_requests_text
        extra_ref.flavor = flavor_text
        extra_ref.vcpu_model = vcpu_model_text
        extra_ref.created_at = datetime.now()
        extra_ref.deleted = 0
        self.session.add(extra_ref)

    def write_security_group(self):
        """Create the instance of security group.
        """
        security_group_id = self.read_security_group_id(
            CONF.NOVA.security_group)
        sec_assocate_ref = objects.SecurityGroupInstanceAssociation()
        sec_assocate_ref.instance_uuid = self.instance_uuid
        sec_assocate_ref.security_group_id = security_group_id
        sec_assocate_ref.created_at = datetime.now()
        sec_assocate_ref.deleted = 0
        self.session.add(sec_assocate_ref)

    def write_block_device_mapping(self):
        """Create the instance of block device mapping.
        """
        block_device_ref = objects.BlockDeviceMapping()
        block_device_ref.instance_uuid = self.instance_uuid
        block_device_ref.source_type = 'image'
        block_device_ref.destination_type = 'local'
        block_device_ref.device_type = 'disk'
        block_device_ref.boot_index = 0
        block_device_ref.device_name = '/dev/vda'
        block_device_ref.delete_on_termination = True
        block_device_ref.image_id = self.read_image()
        block_device_ref.no_device = False
        block_device_ref.created_at = datetime.now()
        block_device_ref.deleted = 0
        self.session.add(block_device_ref)

    def write_instance_system_metadata(self):
        """Create a system-owned metadata key/value pair for an instance.
        """
        metadata_info = {
            'image_min_disk': CONF.VM.disk,
            'image_min_ram': 0,
            'image_disk_format': 'qcow2',
            'image_base_image_ref': self.read_image(),
            'image_container_format': 'bare'
        }
        for k, v in metadata_info.items():
            metadata_ref = objects.InstanceSystemMetadata()
            metadata_ref.key = k
            metadata_ref.value = v
            metadata_ref.instance_uuid = self.instance_uuid
            metadata_ref.created_at = datetime.now()
            metadata_ref.deleted = 0
            self.session.add(metadata_ref)

    def write_instance_actions(self):
        """Create the instance of actions and events.
        """
        build_event = 'compute__do_build_and_run_instance'

        action_ref = objects.InstanceAction()
        action_ref.action = 'create'
        action_ref.instance_uuid = self.instance_uuid
        action_ref.request_id = self.generate_request_id()
        action_ref.user_id = CONF.KEYSTONE.user_id
        action_ref.project_id = CONF.KEYSTONE.tenant_id
        action_ref.created_at = datetime.now()
        action_ref.deleted = 0
        self.session.add(action_ref)
        self.session.flush()

        event_ref = objects.InstanceActionEvent()
        event_ref.event = build_event
        event_ref.action_id = action_ref.id
        event_ref.result = 'Success'
        event_ref.created_at = datetime.now()
        event_ref.deleted = 0
        self.session.add(event_ref)

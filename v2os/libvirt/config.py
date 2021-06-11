# -*- coding: utf-8 -*-
#
# Copyright @ 2020 OPS, YY Inc.
#
# Author: Jinlong Yang
#

from lxml import etree


NOVA_NS = "http://openstack.org/xmlns/libvirt/nova/1.0"


class LibvirtConfigObject:

    def __init__(self, **kwargs):
        self.root_name = kwargs.get('root_name')
        self.ns_prefix = kwargs.get('ns_prefix')
        self.ns_uri = kwargs.get('ns_uri')

    def _new_node(self, tag, **kwargs):
        if self.ns_uri is None:
            return etree.Element(tag, **kwargs)
        else:
            return etree.Element('{' + self.ns_uri + '}' + tag,
                                 nsmap={self.ns_prefix: self.ns_uri},
                                 **kwargs)

    def _text_node(self, tag, value, **kwargs):
        child = self._new_node(tag, **kwargs)
        child.text = value if isinstance(value, str) else str(value)
        return child

    def format_dom(self):
        return self._new_node(self.root_name)

    def to_xml(self):
        root = self.format_dom()
        xml_str = etree.tostring(root, pretty_print=True).decode('utf-8')
        return xml_str


class LibvirtConfigMetaInstance(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super().__init__(root_name='instance',
                         ns_prefix='nova', ns_uri=NOVA_NS)

        self.hostname = kwargs.get('hostname')
        self.create_time = kwargs.get('create_time')
        self.flavor_name = kwargs.get('flavor_name')
        self.flavor_mem = kwargs.get('flavor_mem')
        self.flavor_disk = kwargs.get('flavor_disk')
        self.cpu = kwargs.get('cpu')
        self.user_id = kwargs.get('user_id')
        self.tenant_id = kwargs.get('tenant_id')
        self.image_id = kwargs.get('image_id')

    def format_dom(self):
        dev = super().format_dom()

        # package
        pkg = self._new_node('package', **{'version': '2015.1.4-1.el7'})
        dev.append(pkg)

        # name
        name = self._text_node('name', self.hostname)
        dev.append(name)

        # creationTime
        ct = self._text_node('creationTime', self.create_time)
        dev.append(ct)

        # flavor
        flavor = self._new_node('flavor', **{'name': self.flavor_name})
        mem = self._text_node('memory', self.flavor_mem)
        flavor.append(mem)

        disk = self._text_node('disk', self.flavor_disk)
        flavor.append(disk)

        swap = self._text_node('swap', '0')
        flavor.append(swap)

        ephemeral = self._text_node('ephemeral', '0')
        flavor.append(ephemeral)

        vcpu = self._text_node('vcpus', self.cpu)
        flavor.append(vcpu)
        dev.append(flavor)

        # owner
        owner = self._new_node('owner')
        user = self._text_node('user', 'admin', **{'uuid': self.user_id})
        owner.append(user)

        project = self._text_node('project', 'admin',
                                  **{'uuid': self.tenant_id})
        owner.append(project)
        dev.append(owner)

        # root
        dev.append(self._new_node('root',
                                  **{'type': 'image', 'uuid': self.image_id}))
        return dev


class LibvirtConfigDisk(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super().__init__(root_name='disk', **kwargs)

        uuid = kwargs.get('uuid')
        mount = kwargs.get('mount')
        self.disk = '%(mount)s/nova/instances/%(uuid)s/disk' % {
            'mount': mount, 'uuid': uuid}

    def format_dom(self):
        dev = super().format_dom()
        dev.set('type', 'file')
        dev.set('device', 'disk')
        dev.append(self._new_node('driver', **{'name': 'qemu',
                                               'type': 'qcow2',
                                               'cache': 'none'}))
        dev.append(self._new_node('source', **{'file': self.disk}))
        dev.append(self._new_node('target', **{'bus': 'virtio', 'dev': 'vda'}))
        return dev


class LibvirtConfigInterface(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super().__init__(root_name='interface', **kwargs)

        self.mac = kwargs.get('mac')
        self.cpu = str(kwargs.get('cpu'))
        self.bridge = kwargs.get('bridge')

    def format_dom(self):
        dev = super().format_dom()
        dev.set('type', 'bridge')
        dev.append(self._new_node('mac', **{'address': self.mac}))
        dev.append(self._new_node('model', **{'type': 'virtio'}))
        dev.append(self._new_node('source', **{'bridge': self.bridge}))

        nic = self._new_node('driver', **{'name': 'vhost', 'queues': self.cpu})
        dev.append(nic)
        return dev


class LibvirtConfigGuest(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super().__init__(root_name='domain', **kwargs)

        self.kwargs = kwargs
        self.uuid = kwargs.get('uuid')
        self.name = kwargs.get('name')
        self.vcpu = kwargs.get('cpu')
        self.memory = kwargs.get('mem')
        self.flavor_mem = kwargs.get('flavor_mem')
        self.serial_uuid = kwargs.get('serial_uuid')
        self.console_path = '%(mount)s/nova/instances/%(uuid)s/console.log' % {
            'mount': kwargs.get('mount'), 'uuid': self.uuid}

    def format_dom(self):
        root = super().format_dom()
        root.set('type', 'kvm')

        self._format_basic_props(root)
        self._format_metadata(root)
        self._format_sysinfo(root)
        self._format_os(root)
        self._format_feature(root)
        self._format_cputune(root)
        self._format_clock(root)
        self._format_arch(root)
        self._format_device(root)

        return root

    def _format_basic_props(self, root):
        root.append(self._text_node('uuid', self.uuid))
        root.append(self._text_node('name', self.name))
        root.append(self._text_node('memory', self.memory))

        vcpu = self._text_node('vcpu', self.vcpu)
        vcpu.set('cpuset', '4-39')
        root.append(vcpu)

    def _format_metadata(self, root):
        meta = self._new_node('metadata')
        config_meta = LibvirtConfigMetaInstance(**self.kwargs)
        info = config_meta.format_dom()
        meta.append(info)
        root.append(meta)

    def _format_sysinfo(self, root):
        sysinfo = self._new_node('sysinfo', **{'type': 'smbios'})

        system = self._new_node('system')
        sysinfo.append(system)

        system.append(self._text_node('entry', 'Fedora Project',
                                      **{'name': 'manufacturer'}))
        system.append(self._text_node('entry', 'OpenStack Nova',
                                      **{'name': 'product'}))
        system.append(self._text_node('entry', '2015.1.4-1.el7',
                                      **{'name': 'version'}))
        system.append(self._text_node('entry', self.serial_uuid,
                                      **{'name': 'serial'}))
        system.append(self._text_node('entry', self.uuid,
                                      **{'name': 'uuid'}))
        sysinfo.append(system)

        root.append(sysinfo)

    def _format_os(self, root):
        os = self._new_node('os')
        os.append(self._text_node('type', 'hvm'))
        os.append(self._new_node('boot', **{'dev': 'hd'}))
        os.append(self._new_node('smbios', **{'mode': 'sysinfo'}))
        root.append(os)

    def _format_feature(self, root):
        feature = self._new_node('features')
        feature.append(self._new_node('acpi'))
        feature.append(self._new_node('apic'))
        root.append(feature)

    def _format_cputune(self, root):
        cputune = self._new_node('cputune')
        cputune.append(self._text_node('shares', self.flavor_mem))
        root.append(cputune)

    def _format_clock(self, root):
        clock = self._new_node('clock', **{'offset': 'utc'})
        clock.append(self._new_node(
                     'timer', **{'name': 'pit', 'tickpolicy': 'delay'}))
        clock.append(self._new_node(
                     'timer', **{'name': 'rtc', 'tickpolicy': 'catchup'}))
        clock.append(self._new_node(
                     'timer', **{'name': 'hpet', 'present': 'no'}))
        root.append(clock)

    def _format_arch(self, root):
        cpu = self._new_node('cpu', **{'mode': 'host-model', 'match': 'exact'})
        cpu.append(self._new_node('topology',
                                  **{'sockets': str(self.vcpu),
                                     'cores': '1', 'threads': '1'}))
        root.append(cpu)

    def _format_device(self, root):
        devices = self._new_node('devices')

        config_disk = LibvirtConfigDisk(**self.kwargs)
        disk = config_disk.format_dom()
        devices.append(disk)

        config_interface = LibvirtConfigInterface(**self.kwargs)
        nic = config_interface.format_dom()
        devices.append(nic)

        serial = self._new_node('serial', **{'type': 'file'})
        serial.append(self._new_node('source', **{'path': self.console_path}))
        devices.append(serial)
        devices.append(self._new_node('serial', **{'type': 'pty'}))

        devices.append(self._new_node('input',
                                      **{'type': 'tablet', 'bus': 'usb'}))

        devices.append(self._new_node('graphics', **{'type': 'vnc',
                                                     'autoport': 'yes',
                                                     'keymap': 'en-us',
                                                     'listen': '0.0.0.0'}))
        video = self._new_node('video')
        video.append(self._new_node('model', **{'type': 'cirrus'}))
        devices.append(video)

        balloon = self._new_node('memballoon', **{'model': 'virtio'})
        balloon.append(self._new_node('stats', **{'period': '10'}))
        devices.append(balloon)

        root.append(devices)

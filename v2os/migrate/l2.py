# -*- coding: utf-8 -*-
#
# Copyright @ 2020 OPS, YY Inc.
#
# Author: Jinlong Yang
#

import json
import logging
import netaddr

import paramiko
from dotmap import DotMap
from oslo_config import cfg

from v2os.migrate.manager import Manager
from v2os import objects
from v2os.libvirt.config import LibvirtConfigGuest
from v2os.libvirt.driver import LibvirtDriver

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

vm_opts = [
    cfg.StrOpt('mount', default='/data', help='nova instance mount dir.'),
    cfg.StrOpt('source', default='/opt/migrate',
               help='migrate image disk source directory.')
]

keystone_opts = [
    cfg.StrOpt('user_id', default='', help='current user id'),
    cfg.StrOpt('tenant_id', default='', help='current tenant id'),
]

glance_opts = [
    cfg.StrOpt('image_ref', default='', help='current image id')
]

CONF.register_cli_opts(vm_opts, 'VM')
CONF.register_opts(keystone_opts, 'KEYSTONE')
CONF.register_opts(glance_opts, 'GLANCE')


class RPC:

    def execute(self, host, cmd, port=22, user='root', pswd=''):
        """Remote commond execute.
        """
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(host, port, user, pswd,
                        timeout=360, banner_timeout=360)
        except Exception as _ex:
            LOG.error('host: %s ssh remote connect failed: %s'
                      % (host, str(_ex)))
            raise Exception('连接到目标机器: %s 失败!' % host)
        stdin, stdout, stderr = ssh.exec_command(cmd)
        err_list = stderr.readlines()
        if len(err_list) > 0:
            return False
        return True

    def device_exists(self, host, device):
        """Check remote host if ethernet device exists.
        """
        cmd = 'ls /sys/class/net/%s' % device
        return self.execute(host, cmd)

    def mkdir(self, host, path):
        """Make diriectory in the remote host.
        """
        cmd = 'if [ ! -d "%s" ]; then mkdir -p %s; fi' % (path, path)
        if not self.execute(host, cmd):
            raise Exception('创建目录: %s 失败!' % path)

    def touch(self, host, filename):
        """Create file in the remote host.
        """
        cmd = 'if [ ! -f "%s" ]; then touch %s; fi' % (filename, filename)
        if not self.execute(host, cmd):
            raise Exception('创建文件: %s 失败!' % filename)

    def chmod(self, host, path, mode):
        """Change the access permissions of a file.
        """
        cmd = 'chmod %s %s' % (mode, path)
        if not self.execute(host, cmd):
            raise Exception('修改权限: %s 失败!' % cmd)

    def chown(self, host, path, uid, gid):
        """Change the owner and group id of path to the numeric uid and gid.
        """
        cmd = 'chown %s:%s %s' % (uid, gid, path)
        if not self.execute(host, cmd):
            raise Exception('修改所属用户和所属组: %s 失败!' % cmd)

    def redirect(self, host, content, dist):
        """Redirect content to dist file, such as: echo 'x' > /tmp/a.log
        """
        cmd = 'echo %s > %s' % (content, dist)
        if not self.execute(host, cmd):
            raise Exception('重定向数据到文件: %s 失败!' % cmd)

    def add_to(self, host, content, dist):
        """Add to content to dist file, such as: echo '\nx\c >> /tmp/a.log'
        """
        br = 'echo -e "\n%s\c" >> %s' % (content, dist)
        nobr = 'echo -e "%s\c" >> %s' % (content, dist)

        cmd = 'if [ ! -s "%s" ]; then %s; else %s; fi' % (dist, nobr, br)
        if not self.execute(host, cmd):
            raise Exception('追加数据到文件: %s 失败!' % cmd)

    def textarea(self, host, content, dist):
        """Use cat cmd write multi text data to dist file.
        """
        cmd = """\
cat > %s << EOF
%s
EOF""" % (dist, content)
        if not self.execute(host, cmd):
            raise Exception('写入文本数据到文件: %s 失败!' % cmd)


class L2Drivier(RPC):

    def ensure_vlan(self, hypervisor, vlan):
        """Create a vlan unless it already exists.
        """
        iface = 'vlan%s' % vlan
        if self.device_exists(hypervisor, iface):
            return

        cmd = 'ip link add link bond0 name %s type vlan id %s' % (
            iface, vlan
        )
        if not self.execute(hypervisor, cmd):
            raise Exception('创建vlan设备(%s)失败!' % iface)

        cmd = 'ip link set %s up' % iface
        if not self.execute(hypervisor, cmd):
            raise Exception('启用vlan设备(%s)失败!' % iface)
        LOG.info('** Create and start vlan device: %s success.' % iface)

    def ensure_bridge(self, hypervisor, network):
        """Create a bridge unless it already exists.
        """
        vlan = network.get('vlan')
        cidr = network.get('cidr')
        bridge = network.get('bridge')
        dhcp_server = network.get('dhcp_server')
        if self.device_exists(hypervisor, bridge):
            return

        cmd = 'ip link add %s type bridge' % bridge
        if not self.execute(hypervisor, cmd):
            raise Exception('创建bridge设备(%s)失败!' % bridge)

        iface = 'vlan%s' % vlan
        cmd = 'ip link set %s master %s' % (iface, bridge)
        if not self.execute(hypervisor, cmd):
            raise Exception('绑定vlan(%s) to bridge(%s)失败!' % (
                iface, bridge))

        cmd = 'ip link set %s up' % bridge
        if not self.execute(hypervisor, cmd):
            raise Exception('启用bridge设备(%s)失败!' % bridge)

        mask_bit = cidr.split('/')[-1]
        cmd = 'ip a add %s/%s dev %s' % (dhcp_server, mask_bit, bridge)
        if not self.execute(hypervisor, cmd):
            raise Exception('赋予bridge设备(%s) dhcp server地址(%s)失败!'
                            % (bridge, dhcp_server))
        LOG.info('** Create bridge: %s; Bind vlan: %s; Assign dhcp server '
                 'addr: %s; success.' % (bridge, iface, dhcp_server))

    def _dhcp_file(self, bridge, kind):
        """Return path to a pid, leases, hosts or conf file for a bridge/device.
        """
        prefix = '%(mount)s/nova/networks/nova-%(bridge)s' % {
            'mount': CONF.VM.mount, 'bridge': bridge
        }
        return '%(prefix)s.%(kind)s' % {'prefix': prefix, 'kind': kind}

    def get_dhcp_opts(self, gateway):
        """Get network's hosts config in dhcp-opts format.
        """
        opts = []
        # NOTE: 3 is the dhcp option for gateway.
        opts.append('3')
        opts.append(gateway)
        return ','.join(opts)

    def create_dhcp_item(self, hypervisor, network):
        """Write dhcp config item of a instance, for `--dhcp-hostsfile`.
        """
        ip = network.get('ip')
        mac = network.get('mac')
        bridge = network.get('bridge')
        hostname = network.get('hostname')

        hostfile = self._dhcp_file(bridge, 'conf')
        item = '%(mac)s,%(hostname)s,%(ip)s' % {'mac': mac,
                                                'hostname': hostname, 'ip': ip}
        self.add_to(hypervisor, item, hostfile)
        LOG.info('** Create dhcp config item: %s success.' % item)

    def restart_dhcp(self, hypervisor, network):
        """(Re)starts a dnsmasq server for a given network.

        If a dnsmasq instance is already running then send a HUP
        signal causing it to reload, otherwise spawn a new instance.
        """
        label = network.get('label')
        mask = network.get('netmask')
        bridge = network.get('bridge')
        gateway = network.get('gateway')
        dhcp_server = network.get('dhcp_server')
        dhcp_start = network.get('dhcp_start')
        lease_max = network.get('lease_max')

        pidfile = self._dhcp_file(bridge, 'pid')
        optsfile = self._dhcp_file(bridge, 'opts')
        addnfile = self._dhcp_file(bridge, 'hosts')

        # NOTE: Check hypervisor if dnsmasq process exists.
        cmd = ('total=$(ps aux|grep dnsmasq|grep "%s"|grep -v grep|wc -l); '
               'if [ $total -eq 0 ]; then ls 999; fi' % dhcp_server)
        is_running = self.execute(hypervisor, cmd)
        if is_running:
            cmd = ("ps aux | grep dnsmasq | grep '%s' | awk '{print $2}' | "
                   "xargs kill -9" % dhcp_server)
            if not self.execute(hypervisor, cmd):
                raise Exception('kill dnsmasq进程: %s 失败!' % cmd)
        else:
            self.touch(hypervisor, pidfile)
            self.touch(hypervisor, addnfile)

            self.touch(hypervisor, optsfile)
            self.chmod(hypervisor, optsfile, '644')
            self.redirect(hypervisor, self.get_dhcp_opts(gateway), optsfile)

        # NOTE: Write dhcp item(mac,hostname,ip) to the conf.
        hostsfile = self._dhcp_file(bridge, 'conf')
        self.touch(hypervisor, hostsfile)
        self.chmod(hypervisor, hostsfile, '644')
        self.create_dhcp_item(hypervisor, network)

        domain = 'novalocal'
        dhcp_range = 'set:%s,%s,static,%s,86400s' % (label, dhcp_start, mask)

        cmd = ['dnsmasq',
               '--strict-order',
               '--bind-interfaces',
               '--conf-file=',
               '--pid-file=%s' % pidfile,
               '--dhcp-optsfile=%s' % optsfile,
               '--listen-address=%s' % dhcp_server,
               '--except-interface=lo',
               '--dhcp-range=%s' % dhcp_range,
               '--dhcp-lease-max=%s' % lease_max,
               '--dhcp-hostsfile=%s' % hostsfile,
               '--domain=%s' % domain,
               '--addn-hosts=%s' % addnfile,
               '--no-hosts',
               '--leasefile-ro']
        cmd = ' '.join(cmd)
        LOG.debug(cmd)
        if not self.execute(hypervisor, cmd):
            raise Exception('创建dnsmasq服务失败!')
        LOG.info('** Start dnsmasq for dhcp service success.')


class LibvirtManager(Manager, L2Drivier):

    def __init__(self, session, instance_ref):
        self.session = session
        self.instance_ref = instance_ref
        self.network_info = self.read_network_info()
        self.instance_name = self.generate_instance_name(self.instance_ref.id)

    def build(self):
        mount = CONF.VM.mount
        uuid = self.instance_ref.uuid
        hypervisor = self.instance_ref.host
        vlan = self.network_info.get('vlan')

        # l2 build
        self.ensure_vlan(hypervisor, vlan)
        self.ensure_bridge(hypervisor, self.network_info)

        # NOTE: 应用到线上需要注释掉, 因为需要reload dhcp配置. 而这个reload
        #       是kill再启动, 所以线上dnsmasq服务还是最好不要动. 同时,
        #       这个dnsmasq服务启动去掉了--dhcp-script选项, 跟线上还是有差别.
        self.restart_dhcp(hypervisor, self.network_info)

        # directory
        instance_dir = '%s/nova/instances/%s' % (mount, uuid)
        self.mkdir(hypervisor, instance_dir)
        LOG.info('step12 build instance: %s nova dir: %s success.'
                 % (uuid, instance_dir))

        # disk.info
        disk_file = '%s/disk' % instance_dir
        info_file = '%s/disk.info' % instance_dir
        disk_info = json.dumps({disk_file: 'qcow2'})
        self.textarea(hypervisor, disk_info, info_file)
        self.chown(hypervisor, info_file, 'nova', 'nova')
        LOG.info('step13 write instance: %s disk.info success.' % uuid)

        # console.log
        console_file = '%s/console.log' % instance_dir
        self.touch(hypervisor, console_file)
        self.chown(hypervisor, console_file, 'qemu', 'qemu')
        LOG.info('step14 build instance: %s console.log success.' % uuid)

        # libvirt.xml
        xml = self.generate_xml()
        libvirt_xml = '%s/libvirt.xml' % instance_dir
        self.textarea(hypervisor, xml, libvirt_xml)
        self.chown(hypervisor, libvirt_xml, 'nova', 'nova')
        LOG.info('step15 write instance: %s libvirt.xml success.' % uuid)

        # disk (mv /opt/migrate/disk $instance_dir)
        self.move_disk(hypervisor, instance_dir)
        LOG.info('step16 move instacne: %s source disk to current instance '
                 'dir: %s success' % (uuid, instance_dir))

        # create virtual machine
        self.create_vm(hypervisor, instance_dir, xml)

        # NOTE: 通过root执行virsh命令后, 必须保证disk的owner为qemu:qemu
        console_log = """虚拟机已创建完成:
        1、磁盘路径: %s
        2、实例名称: %s
        """ % (instance_dir, self.instance_name)
        self.purple(console_log)

    def read_flavor_info(self):
        instance_type_id = self.instance_ref.instance_type_id
        instance_type_ref = self.session.query(objects.InstanceTypes)\
                .filter(objects.InstanceTypes.id == instance_type_id)\
                .first()
        flavor = DotMap()
        flavor.name = instance_type_ref.name
        flavor.memory_mb = instance_type_ref.memory_mb
        flavor.vcpus = instance_type_ref.vcpus
        flavor.root_gb = instance_type_ref.root_gb
        return flavor.toDict()

    def read_network_info(self):
        domain_uuid = self.instance_ref.uuid
        vif_ref = self.session.query(objects.VirtualInterface)\
                .filter(objects.VirtualInterface.instance_uuid == domain_uuid)\
                .first()
        network_id = vif_ref.network_id
        network_ref = self.session.query(objects.Network)\
                .filter(objects.Network.id == network_id)\
                .first()
        fixed_ip_ref = self.session.query(objects.FixedIp)\
                .filter(objects.FixedIp.instance_uuid == domain_uuid)\
                .first()

        cidr = network_ref.cidr
        lease_max = netaddr.IPNetwork(cidr).size

        net = DotMap()
        net.mac = vif_ref.address
        net.vlan = network_ref.vlan
        net.bridge = network_ref.bridge
        net.label = network_ref.label
        net.cidr = network_ref.cidr
        net.netmask = network_ref.netmask
        net.gateway = network_ref.gateway
        net.dhcp_server = network_ref.dhcp_server
        net.dhcp_start = network_ref.dhcp_start
        net.lease_max = lease_max
        net.ip = fixed_ip_ref.address
        net.hostname = self.instance_ref.hostname
        return net.toDict()

    def generate_xml(self):
        """Generate instance xml.
        """
        flavor_dict = self.read_flavor_info()
        xml_data = {
            'uuid': self.instance_ref.uuid,
            'name': self.instance_name,
            'mem': int(self.instance_ref.memory_mb) * 1024,
            'cpu': self.instance_ref.vcpus,
            'hostname': self.instance_ref.hostname,
            'create_time': self.strtime(self.instance_ref.created_at),
            'flavor_name': flavor_dict.get('name'),
            'flavor_mem': flavor_dict.get('memory_mb'),
            'flavor_disk': flavor_dict.get('root_gb'),
            'user_id': CONF.KEYSTONE.user_id,
            'tenant_id': CONF.KEYSTONE.tenant_id,
            'image_id': CONF.GLANCE.image_ref,
            'serial_uuid': self.generate_uuid(),
            'mount': CONF.VM.mount,
            'mac': self.network_info.get('mac'),
            'bridge': self.network_info.get('bridge')
        }
        domain = LibvirtConfigGuest(**xml_data)
        return domain.to_xml()

    def purple(self, output):
        convert = '\033[35m%(output)s\033[0m' % {'output': output}
        print (convert)

    def move_disk(self, hypervisor, instance_dir):
        cmd = 'ls %(source)s/disk' % {'source': CONF.VM.source}
        if not self.execute(hypervisor, cmd):
            raise Exception('迁移源目录下没有disk磁盘文件!, 命令: %s' % cmd)

        cmd = 'mv %(source)s/disk %(instance_dir)s' % {
            'source': CONF.VM.source, 'instance_dir': instance_dir}
        if not self.execute(hypervisor, cmd):
            raise Exception('移动迁移源目录下的disk到实例目录(%s)失败!' % cmd)

        disk_file = '%(instance_dir)s/disk' % {'instance_dir': instance_dir}
        self.chown(hypervisor, disk_file, 'qemu', 'qemu')

    def create_vm(self, hypervisor, instance_dir, xml):
        hypervisor_ip = self.get_hypervisor_ip(hypervisor)

        driver = LibvirtDriver()
        driver.connect(hypervisor_ip)
        domain = driver.define(xml)
        is_create = driver.launch(domain)
        if is_create != 0:
            raise Exception('创建实例失败!')
        LOG.info('step17 create instacne: %s success.' % domain.UUIDString())

        self.purple('当前hypervisor: %s 已运行虚拟机实例列表为:' % hypervisor)
        driver.list_domain()

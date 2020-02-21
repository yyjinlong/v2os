v2os(vcenter or virtual machine migrate to openstack)
-----------------------------------------------------
Jinlong Yang

# Mock vlan信息

    网段: 10.12.28.0/22  掩码: 255.255.252.0  网关: 10.12.28.1


# Mock 网络准备

    1 创建并启用vlan1220

    ip link add link bond0 name vlan1220 type vlan id 1220
    ip link set vlan1220 up

    2 检查已创建好的vlan1220

    ip link show vlan1220
    or:
    cat /proc/net/vlan/vlan1220

    3 添加br1220，并将vlan1220桥接到br1220这个网桥上

    ip link add br1220 type bridge
    ip link set vlan1220 master br1220
    ip link set br1220 up

    4 检查已创建好的br1220和绑定情况

    ip link show br1220
    brctl show

    5 给网桥绑定dhcp server地址

    ip a add 10.12.28.2/22 dev br1220

    6 ip link操作二层网络帮助查看

    ip link help


# Mock dhcp分配

    1 启动dnsmasq服务

    dnsmasq --strict-order
            --bind-interfaces
            --conf-file=
            --pid-file=/data/nova/networks/nova-br1220.pid
            --dhcp-optsfile=/data/nova/networks/nova-br1220.opts
            --listen-address=10.12.28.2
            --except-interface=lo
            --dhcp-range=set:pub-net,10.12.28.4,static,255.255.252.0,86400s
            --dhcp-lease-max=1024
            --dhcp-hostsfile=/data/nova/networks/nova-br1220.conf
            --domain=novalocal
            --addn-hosts=/data/nova/networks/nova-br1220.hosts
            --no-hosts
            --leasefile-ro

    2 写入网关信息

    [root@dx-tkvm00 networks]# cat /data/nova/networks/nova-br1220.opts
    3,10.12.28.1

    3 添加测试mac,主机名,ip地址信息

    [root@dx-tkvm00 ~]# cat /data/nova/networks/nova-br1220.conf
    fa:16:3e:c3:c4:c6,yy-jinlong00.yy,10.12.30.255

    4 登录虚拟机修改网卡配置为dhcp模式，并设置onboot=yes

    vim /etc/sysconfig/network-scripts/ifcfg-eth0
    DEVICE=eth0
    BOOTPROTO=dhcp
    ONBOOT=yes

    5 登录虚拟机进行dhcp测试

    # dhclient
    or
    # service network restart


# Develop

    1 初始化git
    # git init

    2 安装依赖
    # yum install -y mysql-devel libvirt-devel

    3 代码构建(注: 要求python3)
    # python tools/install_venv.py
    # tools/with_venv.sh python seup.py develop


# Run

    # 查看参数
    # tools/with_venv.sh v2os-migrate --config-file=etc/dev.conf -h

    # 迁移信息
    # tools/with_venv.sh v2os-migrate --config-file=etc/dev.conf --VM-os=centos-6.9 --VM-vlan=1220 --VM-cpu=4 --VM-mem=4 --VM-disk=150 --VM-hostname=yy-jinlong00.yy --VM-hypervisor=dx-tkvm00.dx --VM-mount=/data


# Online

    # cd /opt; git clone ....
    # ln -s /opt/v2os/.venv/bin/v2os-migrate /usr/local/bin/v2os-migrate
    # touch /etc/v2os.conf
    # v2os-migrate --config-file=/etc/v2os.conf -h

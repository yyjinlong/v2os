# -*- coding: utf-8 -*-
#
# Copyright @ 2020 OPS, YY Inc.
#
# Author: Jinlong Yang
#

import logging

# NOTE(设置oslo_db的日志级别, 避免DEBUG日志输出)
logging.getLogger('oslo_db').setLevel(logging.WARNING)
logging.getLogger('paramiko').setLevel(logging.WARNING)


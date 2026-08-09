"""子测试包（核心契约 / OKX 适配器 / Runner 产品 / 认证 / 备份 / 迁移）。

为什么需要这个文件
------------------
Python 3.11 起 ``unittest`` 的自动发现不再递归进入命名空间包（无 ``__init__.py``
的目录）。此前 ``tests/split/`` 下的 6 个用例文件从未被
``python -m unittest discover -s tests`` 发现——门禁显示的 196 个用例里**不含**
OKX CCXT 适配器、Runner 产品、产品认证、备份与迁移测试。

补上 ``__init__.py`` 后这些用例才真正进入门禁。
"""

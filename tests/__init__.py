"""后端测试包初始化：在导入任何被测模块之前完成数据库隔离。

为什么必须放在这里
------------------
复核发现（P1）：``tests/test_trading_proxy.py`` 直接使用 ``apps.api.main:app``，
其写请求会命中 ``governance_middleware`` 的统一审计，把 ``audit_logs`` 写进仓库主库
``apps/api/store.db``。实测一次门禁即让主库 SHA-256 由 ``fc865f…`` 变为 ``02b86f…``、
``audit_logs`` 由 368 增至 390。这使门禁**有副作用、不可重复**，不能作为发布门禁。

``apps/api/store.py`` 在**模块导入时**一次性解析 ``QUANTHUB_STORE_PATH``（``_DB``），
之后无法再改。因此隔离必须发生在任何 ``apps.api.*`` 导入之前。
``unittest discover -s tests`` 会先导入 ``tests`` 包本身，再导入 ``tests.test_*``
子模块——包 ``__init__`` 是能保证的最早时机。

隔离范围
--------
- ``QUANTHUB_STORE_PATH`` → ``logs/test-store/pid-<pid>/store.db``（``logs/`` 已 gitignore）
- ``QUANTHUB_BACKUP_DIR`` → 同目录下 ``backups/``，避免备份用例写入仓库
- ``QUANTHUB_DATABASE_URL`` → 默认清除，防止继承开发者环境里的真实 Postgres
  （确需保留时设 ``QH_TEST_ALLOW_ENV_DATABASE=1``）
- 超长环境变量 → 从**测试进程**视图中移除，详见 ``_drop_unrestorable_env_vars``

逃生舱：显式设置 ``QUANTHUB_STORE_PATH`` 时以显式值为准，但仍禁止指向仓库主库。
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 仓库主库。任何测试都不得写入此文件。
PRODUCTION_STORE_PATH = (REPO_ROOT / "apps" / "api" / "store.db").resolve()


# Windows ``putenv`` 的单变量上限是 32767 字符。宿主环境若注入了超长变量，
# Python 能读到、却写不回去：任何 ``unittest.mock.patch.dict(os.environ, ...)``
# 在退出时执行 ``clear() + update(original)``，就会抛
# ``ValueError: the environment variable is longer than 32767 characters``，
# 让与之无关的用例集体失败。
#
# 实测（2026-08-09 本机）：宿主注入的 ``ACC_PRODUCT_CONFIG_V3`` 长 358604 字符，
# 4 行无关脚本即可复现，与被测代码无关。
#
# 处理：仅在**测试进程内**移除这类无法回写的变量，使门禁对宿主环境免疫。
# 不修改用户真实环境，不影响任何 QuantHub 自有变量（均为短值）。
_MAX_RESTORABLE_ENV_LENGTH = 32767


def _drop_unrestorable_env_vars() -> list[str]:
    dropped = [
        key for key, value in list(os.environ.items()) if len(value) > _MAX_RESTORABLE_ENV_LENGTH
    ]
    for key in dropped:
        os.environ.pop(key, None)
    return dropped


def _default_store_path() -> Path:
    override = os.environ.get("QH_TEST_STORE_DIR", "").strip()
    base = Path(override).expanduser() if override else REPO_ROOT / "logs" / "test-store"
    directory = base / f"pid-{os.getpid()}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "store.db"


def isolate_database() -> Path:
    """把应用态持久化重定向到一次性目录，并返回实际使用的库路径。"""
    configured = os.environ.get("QUANTHUB_STORE_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = _default_store_path().resolve()
        os.environ["QUANTHUB_STORE_PATH"] = str(path)

    if path == PRODUCTION_STORE_PATH:
        raise RuntimeError(
            "后端测试禁止指向仓库主库 apps/api/store.db。"
            "请清除 QUANTHUB_STORE_PATH，或改指一次性目录。"
        )

    os.environ.setdefault("QUANTHUB_BACKUP_DIR", str(path.parent / "backups"))
    if not os.environ.get("QH_TEST_ALLOW_ENV_DATABASE"):
        os.environ.pop("QUANTHUB_DATABASE_URL", None)
    return path


#: 本次测试进程实际使用的隔离库路径（供门禁与守卫用例断言）。
STORE_PATH = isolate_database()

#: 本次为保证门禁可重复而丢弃的超长环境变量名（供门禁证据记录）。
DROPPED_ENV_VARS = _drop_unrestorable_env_vars()

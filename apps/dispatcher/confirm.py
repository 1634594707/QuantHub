# -*- coding: utf-8 -*-
"""实盘 CLI 二次确认。

下单前在终端要求人工输入确认码，避免误触发。
配置见 configs/base.yaml: live_confirm
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

from core.config import get_config

logger = logging.getLogger(__name__)


class ConfirmTimeoutError(TimeoutError):
    """确认超时（用户未在 timeout_seconds 内输入）。"""


def cli_confirm(order_summary: dict) -> bool:
    """CLI 交互式确认。

    Args:
        order_summary: 拟下单摘要（symbol/side/qty/price/...）

    Returns:
        True 表示用户确认；False 表示取消或超时。

    注意:
        - 仅在 live_trading=true 时调用此函数
        - 超时自动取消（避免阻塞）
    """
    cfg = get_config().get("live_confirm", {})
    if not cfg.get("enabled", True):
        return True

    token = cfg.get("confirm_token", "CONFIRM")
    timeout = int(cfg.get("timeout_seconds", 60))

    print("\n" + "=" * 60, file=sys.stderr)
    print("⚠️  实盘下单确认", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"时间: {datetime.now().isoformat()}", file=sys.stderr)
    for k, v in order_summary.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    print(f"输入 '{token}' 确认下单（{timeout}秒超时自动取消）；其他输入取消: ",
          end="", file=sys.stderr, flush=True)

    # Windows 不支持 select 超时读 stdin，用线程+队列实现
    import queue
    import threading

    q: queue.Queue = object  # type: ignore
    q = queue.Queue()

    def _reader():
        try:
            line = sys.stdin.readline().strip()
            q.put(line)
        except Exception:  # noqa: BLE001
            q.put(None)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        print("\n[超时] 已自动取消下单", file=sys.stderr)
        return False

    try:
        answer = q.get_nowait()
    except queue.Empty:
        return False

    if answer == token:
        print("[确认] 开始执行下单", file=sys.stderr)
        return True
    print("[取消] 用户取消下单", file=sys.stderr)
    return False

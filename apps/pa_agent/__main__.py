# -*- coding: utf-8 -*-
"""``python -m apps.pa_agent`` 入口。

等价于 ``python apps/pa_agent/run.py``：把本目录加入 sys.path 后启动上游 PyQt6 应用。
"""
from __future__ import annotations

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from pa_agent.main import main

if __name__ == "__main__":
    raise SystemExit(main())

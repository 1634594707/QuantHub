"""QuantHub PA_Agent 桌面应用成员（apps/pa_agent）。

双轨并入的一部分：
- 本目录下的 ``pa_agent/`` 是上游 PA_Agent 的完整桌面应用（PyQt6 GUI + 分析引擎），
  自包含、可独立启动，不污染 QuantHub 的 Web 栈（Streamlit/FastAPI）。
- 重依赖（PyQt6 / pyqtgraph / MT5 等）走可选组 ``pa-agent-desktop`` / ``pa-agent-win32``，
  默认不安装。
- 后续 Phase 2 将把 ``pa_agent/ai/`` 分析引擎抽离为统一底座，供本桌面应用与
  ``strategies/ai_analysis/pa_agent`` 插件共享，消除双引擎。

启动方式::

    uv sync --extra pa-agent-desktop
    uv run python apps/pa_agent/run.py
    # 或
    uv run python -m apps.pa_agent
"""

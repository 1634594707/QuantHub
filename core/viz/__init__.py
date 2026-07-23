# -*- coding: utf-8 -*-
"""统一可视化组件库。

提供:
    - Plotly helper（统一图表风格与配色）
    - HTMLReport：自包含 HTML 报告生成器（无 Streamlit 依赖）
    - Streamlit 组件（K线图、权益曲线、信号表）

Plotly / Streamlit 按 extra 安装（uv sync --extra viz）。
"""
from __future__ import annotations

import logging
from typing import Iterable

import pandas as pd

from .html_report import HTMLReport, _md_to_html

logger = logging.getLogger(__name__)

# 统一配色
COLORS = {
    "primary": "#2E86AB",
    "up": "#E63946",
    "down": "#06A77D",
    "neutral": "#6C757D",
    "bg": "#F8F9FA",
    "grid": "#E9ECEF",
}


def plot_equity_curve(equity: pd.DataFrame, title: str = "权益曲线") -> object:
    """绘制权益曲线（Plotly Figure）。"""
    try:
        import plotly.graph_objects as go
    except ImportError as e:
        raise ImportError("plotly 未安装，请运行: pip install plotly") from e

    if equity.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity["datetime"], y=equity["equity"],
        mode="lines", name="Equity",
        line=dict(color=COLORS["primary"], width=2),
    ))
    fig.update_layout(
        title=title,
        xaxis_title="日期", yaxis_title="权益",
        template="plotly_white",
        hovermode="x unified",
    )
    return fig


def plot_kline(klines: pd.DataFrame, title: str = "K线图") -> object:
    """绘制 K 线（Plotly candlestick）。"""
    try:
        import plotly.graph_objects as go
    except ImportError as e:
        raise ImportError("plotly 未安装，请运行: pip install plotly") from e

    if klines.empty:
        return go.Figure()

    fig = go.Figure(data=[go.Candlestick(
        x=klines["datetime"],
        open=klines["open"], high=klines["high"],
        low=klines["low"], close=klines["close"],
        increasing_line_color=COLORS["up"],
        decreasing_line_color=COLORS["down"],
    )])
    fig.update_layout(
        title=title, xaxis_title="日期", yaxis_title="价格",
        template="plotly_white", xaxis_rangeslider_visible=False,
    )
    return fig


def render_signal_table(signals: Iterable) -> None:
    """Streamlit 渲染信号表。signals 为 Signal 可迭代对象。"""
    try:
        import streamlit as st
    except ImportError as e:
        raise ImportError("streamlit 未安装，请运行: pip install streamlit") from e

    rows = []
    for s in signals:
        rows.append({
            "时间": s.ts, "来源": s.source, "标的": s.symbol,
            "市场": s.market, "方向": s.direction, "评分": f"{s.score:.2f}",
            "置信度": f"{s.confidence:.2f}", "周期": s.timeframe,
            "标签": ",".join(s.tags),
        })
    if not rows:
        st.info("暂无信号")
        return
    df = pd.DataFrame(rows).sort_values("时间", ascending=False)
    st.dataframe(df, use_container_width=True)


def render_module_status(modules: dict) -> None:
    """Streamlit 渲染模块状态卡片。modules: {name: {enabled, live, status}}"""
    try:
        import streamlit as st
    except ImportError as e:
        raise ImportError("streamlit 未安装，请运行: pip install streamlit") from e

    cols = st.columns(len(modules)) if modules else []
    for col, (name, info) in zip(cols, modules.items()):
        with col:
            status_color = "🟢" if info.get("enabled") else "🔴"
            live_badge = " [LIVE]" if info.get("live") else ""
            st.metric(label=f"{status_color} {name}{live_badge}", value=info.get("status", "-"))

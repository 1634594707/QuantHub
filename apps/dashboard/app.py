"""Streamlit 统一看板入口。

聚合所有模块: 结果、回测、信号、监控。
无鉴权（本地使用）。启动: streamlit run apps/dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保仓库根在 sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

from core.config import get_config
from core.signals import get_bus
from core.viz import render_module_status, render_signal_table
from strategies import discover_and_register, list_strategies

st.set_page_config(page_title="QuantHub 看板", layout="wide", page_icon="📊")

# 启动时预加载所有策略模块，触发 @register_strategy 注册
# （streamlit 每次脚本 rerun 都会执行，可接受；discover_and_register 已做容错）
discover_and_register()


@st.cache_data(ttl=30)
def load_config() -> dict:
    return get_config()


def main() -> None:
    st.title("📊 QuantHub 统一量化看板")
    cfg = load_config()
    live = cfg.get("live_trading", False)
    st.caption(
        f"版本 {cfg.get('version', '?')} | schema {cfg.get('schema_version', 1)} | "
        f"模式: {'🔴 实盘' if live else '🟢 研究(dry-run)'}"
    )

    # ===== 侧边栏 =====
    with st.sidebar:
        st.header("导航")
        page = st.radio("选择页面", ["概览", "信号", "回测", "策略模块", "配置"])
        st.divider()
        st.header("市场")
        market = st.selectbox("市场", ["a_shares", "crypto", "mt5"])

    # ===== 概览 =====
    if page == "概览":
        st.header("模块状态")
        strategies = list_strategies()
        modules = {}
        for name, info in strategies.items():
            modules[name] = {
                "enabled": info.live_capable,
                "live": False,
                "status": "ready" if info.live_capable else "research",
            }
        if modules:
            render_module_status(modules)
        else:
            st.info("尚未注册策略模块")

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.metric("已注册策略", len(strategies))
        with col2:
            bus = get_bus()
            st.metric("近期信号", len(bus.history()))

    # ===== 信号 =====
    elif page == "信号":
        st.header("信号流")
        bus = get_bus()
        limit = st.slider("显示条数", 10, 500, 50)
        sigs = bus.history(limit=limit)
        if sigs:
            render_signal_table(sigs)
        else:
            st.info("暂无信号")

    # ===== 回测 =====
    elif page == "回测":
        st.header("回测")
        st.info("选择策略与参数后运行回测。具体策略回测入口在各策略模块内。")
        strategies = list_strategies()
        if strategies:
            name = st.selectbox("策略", list(strategies.keys()))
            if st.button("运行示例回测", type="primary"):
                st.info(f"委托 {name} 策略回测（需策略实现 backtest 方法）")

    # ===== 策略模块 =====
    elif page == "策略模块":
        st.header("策略模块")
        strategies = list_strategies()
        for name, info in strategies.items():
            with st.expander(f"{name} ({info.market})"):
                st.write(f"**版本**: {info.version}")
                st.write(f"**支持实盘**: {'是' if info.live_capable else '否'}")
                st.write(f"**描述**: {info.description or '-'}")

    # ===== 配置 =====
    elif page == "配置":
        st.header("当前配置")
        st.json(cfg)


if __name__ == "__main__":
    main()

"""PA 分析工作台 — Streamlit Web 页面。

以 PA_Agent 桌面工作台为前端主基调，复用 ``pa_agent.view_models`` 共享渲染
逻辑（与 PyQt6 桌面端共用同一套数据提取），提供：

  - 顶部控制栏：数据源 / 交易所 / 品种 / 周期 / 获取数据 / 提交分析 / 增量 / 持续跟踪
  - 5 步分析进度条（FlowBar）
  - 左侧 K 线图（plotly candlestick）
  - 右侧 7 标签页：实时 / 决策树 / 决策树可视化 / 决策 / 未来走势 / 原始 / 调试
  - 底部 5 指标卡（SummaryStrip）

当前为布局 + 渲染打通版本，分析数据由「运行示例分析」按钮注入 mock record
（真实 AI 调用需配置 API Key，后续接入 TwoStageOrchestrator.submit）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保 pa_agent 包可导入（它位于 apps/pa_agent 下，非仓库顶层）
_PA_AGENT_DIR = Path(__file__).resolve().parents[1] / "pa_agent"
if str(_PA_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PA_AGENT_DIR))

import streamlit as st
from pa_agent.view_models import (  # noqa: E402
    build_decision_tree_view,
    build_decision_view,
    build_future_trend_view,
)

# ── Mock 示例 record（符合 AnalysisRecord 关键字段）───────────────────────────

SAMPLE_STAGE1 = {
    "direction": "多",
    "cycle_position": "上涨中",
    "market_phase": "stable",
}

SAMPLE_STAGE2 = {
    "order_type": "做多",
    "order_direction": "多",
    "entry_price": 5400.5,
    "take_profit_price": 5460.0,
    "take_profit_price_2": 5510.0,
    "stop_loss_price": 5360.0,
    "trade_confidence": 78,
    "trade_confidence_reasoning": "多周期共振，量能配合，回踩不破前低。",
    "diagnosis_confidence": 82,
    "diagnosis_confidence_reasoning": "趋势结构完整，动能未衰减。",
    "reasoning": "当前处于上涨中继，回踩均线带获得支撑，风险回报比合理，建议逢低做多。",
    "estimated_win_rate": 65,
    "diagnosis_summary": {
        "direction": "多",
        "cycle_position": "上涨中",
        "market_phase": "stable",
    },
    "next_bar_prediction": {
        "direction": "bullish",
        "probabilities": {"bullish": 60, "bearish": 25, "neutral": 15},
        "reasoning": "阳线吞噬前一根，短线偏多。",
    },
    "next_cycle_prediction": {
        "direction": "bullish",
        "probabilities": {
            "accumulation": 5,
            "uptrend": 45,
            "distribution": 10,
            "downtrend": 5,
            "consolidation": 25,
            "reversal_up": 5,
            "reversal_down": 5,
        },
        "reasoning": "主升段概率最高，关注量能确认。",
    },
}

SAMPLE_GATE_TRACE = [
    {
        "phase": "gate",
        "node_id": "1.1",
        "question": "是否处于明确趋势？",
        "answer": "是",
        "reason": "高点抬高低点抬高",
    },
    {
        "phase": "gate",
        "node_id": "1.2",
        "question": "动能是否配合？",
        "answer": "是",
        "reason": "MACD 金叉",
    },
]
SAMPLE_DECISION_TRACE = [
    {
        "phase": "decision",
        "node_id": "2.1",
        "question": "方向倾向？",
        "answer": "多",
        "reason": "回踩支撑",
    },
    {
        "phase": "decision",
        "node_id": "2.2",
        "question": "是否入场？",
        "answer": "是",
        "reason": "风险回报比达标",
    },
]

STEPS = ["数据就绪", "阶段一分析", "策略路由", "阶段二分析", "决策就绪"]


def _mock_kline() -> list[dict]:
    """Generate a small synthetic OHLC series for the chart demo."""
    import random

    bars = []
    price = 5380.0
    for i in range(60):
        o = price
        c = price + random.uniform(-8, 9)
        h = max(o, c) + random.uniform(0, 5)
        l = min(o, c) - random.uniform(0, 5)
        bars.append({"index": i, "open": o, "high": h, "low": l, "close": c})
        price = c
    return bars


def render_pa_workbench() -> None:
    """Render the PA Agent analysis workbench page."""
    st.title("🖥️ PA 分析工作台")
    st.caption("PA Agent — Trading Terminal 的 Web 孪生视图（分析仅供参考，不构成投资建议）")

    # ── 顶部控制栏 ──
    with st.container(border=True):
        c1, c2, c3, c4, c5, c6 = st.columns([1.2, 1.2, 1.4, 1, 1.1, 1.1])
        with c1:
            data_source = st.selectbox("数据来源", ["MT5", "TradingView", "AkShare"], key="pa_src")
        with c2:
            exchange = st.selectbox(
                "交易所",
                ["（自动）", "OANDA", "PEPPERSTONE", "SSE", "SZSE", "HKEX", "NASDAQ"],
                key="pa_ex",
            )
        with c3:
            symbol = st.text_input("合约 / 品种", "XAUUSDm", key="pa_sym")
        with c4:
            timeframe = st.selectbox(
                "周期", ["1m", "5m", "15m", "1h", "4h", "1d"], index=2, key="pa_tf"
            )
        with c5:
            st.write("")
            if st.button("获取数据", key="pa_fetch", use_container_width=True):
                st.toast(f"已订阅 {symbol} {timeframe}（{data_source}）")
        with c6:
            st.write("")
            if st.button("提交分析", type="primary", key="pa_submit", use_container_width=True):
                st.session_state["pa_record"] = True
                st.toast("示例分析已注入（mock record）")

        c7, c8, c9 = st.columns([1.4, 1.4, 2.2])
        with c7:
            st.checkbox("等待最新K线收盘后再提交", key="pa_wait")
        with c8:
            st.checkbox("持续跟踪分析", key="pa_keep")
        with c9:
            st.checkbox("增量分析（基于上轮记录）", key="pa_incr")

    # ── 5 步进度条 ──
    has_record = st.session_state.get("pa_record", False)
    step_idx = 4 if has_record else 0
    cols = st.columns(len(STEPS))
    for i, label in enumerate(STEPS):
        with cols[i]:
            done = i <= step_idx
            bg = "#1f6feb" if done else "#30363d"
            fg = "#ffffff" if done else "#8b949e"
            st.markdown(
                f"<div style='text-align:center;background:{bg};color:{fg};"
                f"border-radius:6px;padding:6px 2px;font-size:12px;'>{label}</div>",
                unsafe_allow_html=True,
            )

    if not has_record:
        st.info("点击上方「提交分析」注入示例分析，查看完整的决策 / 走势 / 决策树视图。")
        return

    # ── 左图右栏布局 ──
    left, right = st.columns([3, 2], gap="medium")

    with left:
        st.subheader("📈 K 线图")
        bars = _mock_kline()
        import plotly.graph_objects as go

        fig = go.Figure(
            data=[
                go.Candlestick(
                    x=[b["index"] for b in bars],
                    open=[b["open"] for b in bars],
                    high=[b["high"] for b in bars],
                    low=[b["low"] for b in bars],
                    close=[b["close"] for b in bars],
                )
            ]
        )
        fig.update_layout(
            height=420,
            margin=dict(l=30, r=10, t=10, b=20),
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── 底部 5 指标卡 ──
        dview = build_decision_view(
            SAMPLE_STAGE2, stage1_diagnosis=SAMPLE_STAGE1, decision_stance="balanced"
        )
        fview = build_future_trend_view(SAMPLE_STAGE2)
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("趋势", dview["trend"])
        m2.metric("结论", dview["order_type"])
        m3.metric("方向", dview["direction"])
        m4.metric("诊断置信", f"{dview['diagnosis_confidence']['score']}/100")
        nb = fview["next_bar"]
        m5.metric("次根预测", nb["direction_zh"] if nb else "—")

    with right:
        tabs = st.tabs(["实时", "决策树", "决策树可视化", "决策", "未来走势", "原始", "调试"])

        with tabs[0]:
            st.subheader("实时 AI 输出")
            st.write("阶段一 / 阶段二 reasoning 流式输出（接入 Orchestrator 后启用）。")
            st.code("> 阶段一：识别上升趋势，动能未衰减…\n> 阶段二：建议逢低做多…", language="text")

        with tabs[1]:
            st.subheader("决策树（路径）")
            tview = build_decision_tree_view(
                gate_trace=SAMPLE_GATE_TRACE, decision_trace=SAMPLE_DECISION_TRACE
            )
            if tview["path"]:
                st.dataframe(
                    tview["path"],
                    use_container_width=True,
                    column_config={
                        "step": "步",
                        "phase": "阶段",
                        "node": "节点",
                        "question": "问题",
                        "answer": "回答",
                        "basis": "K线依据",
                        "reason": "理由",
                    },
                )
            else:
                st.info("暂无决策路径")

        with tabs[2]:
            st.subheader("决策树可视化")
            st.write("完整静态决策树（已走过节点高亮）：")
            for sec in build_decision_tree_view()["sections"]:
                with st.expander(f"§{sec['id']} {sec['title']}"):
                    for node in sec["nodes"]:
                        st.write(f"**{node['id']}** — {node['question']}")

        with tabs[3]:
            st.subheader("AI 交易决策")
            _render_decision(dview)

        with tabs[4]:
            st.subheader("未来走势预期")
            _render_future_trend(fview)

        with tabs[5]:
            st.subheader("原始")
            st.json({"stage1_diagnosis": SAMPLE_STAGE1, "stage2_decision": SAMPLE_STAGE2})

        with tabs[6]:
            st.subheader("调试")
            st.write("Prompt 文件 / 模型选择器（接入后启用）。")


def _render_decision(dview: dict) -> None:
    st.markdown(
        f"**趋势**：{dview['trend']}  ·  **周期**：{dview['cycle']}  ·  **阶段**：{dview['phase']}"
    )
    dc = dview["diagnosis_confidence"]
    if dc["score"] is not None:
        st.progress(dc["score"] / 100, text=f"市场判断置信度 {dc['score']}/100")
        if dc["reasoning"]:
            st.caption(dc["reasoning"])

    if dview["order_type"] == "不下单":
        st.warning("不下单")
    else:
        st.success(f"**{dview['order_type']}** · 方向 {dview['direction']}")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("入场", _fmt(dview["entry"]))
        col2.metric("TP1", _fmt(dview["tp1"]))
        col3.metric("TP2", _fmt(dview["tp2"]))
        col4.metric("止损", _fmt(dview["sl"]))
        rr = dview["risk_reward"]
        if rr:
            st.write(
                f"盈亏比 **{rr['ratio_text']}** · 风险 {rr['risk']:.4g} / 回报 {rr['reward']:.4g}"
                f"{rr['note']}"
            )
        if dview["estimated_win_rate"]:
            st.write(f"预估胜率：{dview['estimated_win_rate']}")
    tc = dview["trade_confidence"]
    if tc["score"] is not None:
        st.progress(tc["score"] / 100, text=f"交易决策置信度 {tc['score']}/100")
    if dview["reasoning"]:
        st.text_area("分析理由", dview["reasoning"], height=120, disabled=True)


def _render_future_trend(fview: dict) -> None:
    nb = fview["next_bar"]
    if nb:
        st.markdown(f"**次根预测方向**：{nb['direction_zh']}")
        st.write(
            f"阳线 {nb['probabilities']['bullish']}% · "
            f"阴线 {nb['probabilities']['bearish']}% · "
            f"中性 {nb['probabilities']['neutral']}%"
        )
        if nb["reasoning"]:
            st.caption(nb["reasoning"])
    st.divider()
    cyc = fview["next_cycle"]
    if cyc:
        if cyc["unpredictable"]:
            st.warning("不可预测")
        else:
            st.markdown(f"**下个周期方向**：{cyc['direction_zh']}")
            t3 = " · ".join(f"{c['label']} {c['pct']}%" for c in cyc["top3"])
            st.write(t3)
            if cyc["rest"]:
                st.caption("  |  ".join(f"{c['label']} {c['pct']}%" for c in cyc["rest"]))
            if cyc["reasoning"]:
                st.caption(cyc["reasoning"])
    else:
        st.info("暂无周期预测")


def _fmt(v: object) -> str:
    return f"{v:.4g}" if isinstance(v, (int, float)) else "—"

# -*- coding: utf-8 -*-
"""A股晨会简报策略。

把原 ``trading-master/03-daily_news/daily-news``（晨会简报）下沉为 QuantHub 策略模块：

    - 行情/新闻统一走 ``core.data_feed``（不直接抓数据源）
    - 简报文本由 ``core.llm.get_llm()`` 生成，prompt 从原 ``prompts/`` 提取为常量
    - 枢轴点走本模块 ``pivot.calc_pivots``（算法不变）
    - 影响评分走本模块 ``scoring.score_environment``（固定公式，对齐 scoring.md）
    - 可选通过 ``core.alert.get_notifier()`` 推送简报
    - 产出一个综合 ``Signal``（信息型，direction=hold，不给买卖建议）

prompt 规格（full / intraday / swing）对应原 A/B/C 三档报告：
    - full     → C档 全量市场框架（日内+周度+衍生品+资金+事件）
    - intraday → A档 日内交易报告
    - swing    → B档 波段交易报告
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

from core.alert import AlertMessage, get_notifier
from core.config import get_config
from core.data_feed import Interval, get_data_source
from core.llm import get_llm
from core.signals import Signal
from strategies.a_shares.morning_brief.pivot import calc_pivots, pivots_from_klines
from strategies.a_shares.morning_brief.scoring import (
    ScoringInput,
    ScoreBreakdown,
    score_environment,
)
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

_SOURCE = "morning_brief"
_MARKET = "a_shares"

# 默认观察指数（上证指数 / 创业板指 / 沪深300）；可经 kwargs/symbols 覆盖
_DEFAULT_SYMBOLS = ["sh000001", "sz399006", "sh000300"]


# ─────────────────────────────────────────────
# Prompt 常量（从原 prompts/full.md / intraday.md / swing.md 原文提取）
# ─────────────────────────────────────────────

FULL_PROMPT = """# C档 — 全量市场框架报告规格

适用于需要"日内 + 周度 + 衍生品 + 资金 + 事件"完整视角的用户。

---

## 输出目标

同时回答两句话：

1. **今天**：由谁主导，赚钱效应是改善、分化还是转弱。
2. **本周**：由谁主导，环境更偏进攻、轮动还是防守。

并先输出"全量投资速览"（固定 6 行）：
1. 今日主导 + 本周主导
2. 赚钱效应状态（改善/分化/转弱）
3. 今日执行节奏（进攻/均衡/防守/观望）
4. 本周执行节奏（进攻/均衡/防守/观望）
5. 最关键位与触发条件
6. 未来 3–7 天首要风险（一句）

---

## 搜索顺序

执行 `intraday.md` 的全部搜索 + `swing.md` 的全部搜索，并追加：

| # | 新增搜索内容 |
| - | ------------ |
| + | 沪深300成分股日度涨跌榜 Top5 / Bottom5 |
| + | IF / IH / IC 主力价格、基差、持仓变化 |
| + | 中国10Y、美国10Y、中美利差 |
| + | 国务院 / 央行 / 证监会 / 交易所未来7天政策日历 |
| + | 未来7天重要财报披露、股东大会、解禁高峰 |

---

## 必须回答的 5 个问题

1. 今天谁主导市场？
2. 本周谁主导市场？
3. 赚钱效应是在改善、分化还是转弱？
4. 衍生品与资金流向是否支持现有趋势？
5. 未来 3–7 天最重要的事件风险是什么？

---

## 报告结构

```
一页看懂
今日结论
本周结论
全球市场（美股 / 欧股 / 亚股 / DXY / 中美10Y）
A股关键位与赚钱效应（上证 / 创业板 / 沪深300 + 广度数据）
衍生品脉冲（期权 PCR/MaxPain/OI；期指基差/持仓）
资金流向（北向周表 + 分时净流 + 融资融券 + 主力行业流向）
商品与事件（原油/金银/汇率 + IPO/解禁/回购/财报日历）
影响评分
置信度分解
行动框架
触发条件表
重点新闻（宏观/全球/行业/公司/预警，≤ 8 条总计）
数据可得性与缺口
```

---

## 强制约束

- 同时覆盖日内与周度两个时间框架，两者数据不得混用或缺失其一。
- 必须明确三者中谁占优：权重 / 成长 / 题材。
- 必须明确赚钱效应状态：改善 / 分化 / 转弱。
- 必须给出今日与本周执行节奏（由综合环境分+置信度共同决定）。
- 不给买卖建议，只提供市场上下文。
- 全量不等于冗长：每个模块最多 4–6 条核心信息。
- 重点新闻总数最多 8 条，按"最影响盘面"排序，不做背景长文复述。

---

## 推荐模板

`templates/A股晨会简报_C_全量模板.md`
"""

INTRADAY_PROMPT = """# A档 — 日内交易报告规格

适用于当日开平仓交易者，核心是"今天谁主导、关键位在哪、赚钱效应怎么样"。

---

## 输出目标

首句必须回答：**今天更像大盘强、成长强、小票题材强，还是普跌分化。**

并在开头先给"投资速览"（固定 5 行）：
1. 市场状态（偏多/中性/偏弱）
2. 主导风格（权重/成长/题材）
3. 执行节奏（进攻/均衡/防守/观望）
4. 最关键点位与上破/下破触发
5. 今日执行重点（仅 1 句）

---

## 搜索顺序

| # | 搜索内容 | 备用 |
| - | -------- | ---- |
| 1 | A50 期货实时 | 上证50 或 A50 CFD 代理 |
| 2 | 上证 / 上证50 / 深成 / 创业板 / 沪深300 / 中证1000 实时 | — |
| 3 | A股涨跌家数、涨停跌停、两市成交额今日 | — |
| 4 | A股板块涨幅榜 / 跌幅榜实时；各强势板块找 1 个龙头 | — |
| 5 | 北向资金实时；板块资金流向今日 | — |
| 6 | 上证 / 创业板 / 沪深300 RSI(14)、MACD、20/50/200MA、Pivot | — |
| 7 | 50ETF 期权 PCR、Max Pain、OI 今日 | 300ETF 价格 + 成交变化代理 |
| 8 | USD/CNY、Brent、WTI、沪金、沪银实时 | 伦敦金银代理 |
| 9 | A股早间市场新闻（最近 12 小时）| 最多 8 条，要原文直链 |

---

## 必须回答的 4 个问题

1. 市场温度是升温、分化，还是退潮？
2. 当前主导风格是谁？
3. 主线板块是扩散、轮动，还是抱团？
4. 今天最重要的关键位和触发条件是什么？

---

## 报告结构

```
一页看懂
先看结论
市场温度
风格强弱
主线板块与龙头反馈
关键点位与技术状态（三锚：上证 / 创业板 / 沪深300）
资金与外部扰动
影响评分
置信度分解
行动框架
触发条件表
今天最值得看的新闻（≤ 8 条）
数据可得性与缺口
```

---

## 关键点位格式

```
[指数]: Pivot [P]  R1 [R1]  S1 [S1]  ← 一句话状态判断
```

时段观察（固定三行）：

```
09:30–10:00  → [看风格是否延续]
10:30–11:30  → [看主线是否扩散]
14:00–15:00  → [看资金是否回流核心方向]
```

---

## 强制约束

- 结论必须明确：今天更适合看权重、看成长，还是看题材情绪。
- 结论必须给出执行节奏：进攻/均衡/防守/观望（由综合环境分+置信度共同决定）。
- 数据有限时，优先保留赚钱效应 → 板块 → 风格，再保留技术指标。
- 不给买卖建议，只给环境解读。
- 每个模块最多 3–5 条核心信息；单条不超过两句。
- 新闻默认 3–5 条（仅在用户要求时扩展到 8 条）。

---

## 推荐模板

- 通用高可读版：`templates/A股晨会简报_A_高可读模板.md`
"""

SWING_PROMPT = """# B档 — 波段交易报告规格

适用于持仓 3–10 个交易日的交易者，核心是"这周谁主导、下周怎么看、资金在哪边"。

---

## 输出目标

首句必须回答：**下周更可能是权重主导、成长主导、题材轮动，还是防守分化。**

并先给"波段投资速览"（固定 5 行）：
1. 市场状态（偏多/中性/偏弱）
2. 本周主导风格（权重/成长/题材）
3. 执行节奏（进攻/均衡/防守/观望）
4. 下周关键位与上破/下破触发
5. 本周执行重点（仅 1 句）

---

## 搜索顺序

| # | 搜索内容 | 备用 |
| - | -------- | ---- |
| 1 | 沪深300 / 上证 / 创业板本周涨跌幅 | — |
| 2 | A50 当前或前收 | 上证50 代理 |
| 3 | S&P500 / Nasdaq / Dow / FTSE100 / DAX / 恒生 / Nikkei 最新值 | — |
| 4 | DXY、美国10Y、中国10Y | — |
| 5 | A股主要板块近 5 日涨跌幅排序；各强势板块找 1 个龙头 | — |
| 6 | A股本周涨跌家数、涨停跌停变化；高位股反馈 | — |
| 7 | 北向资金 Mon–Fri 每日净流入；周合计 | — |
| 8 | 融资融券余额本周变化 | — |
| 9 | USD/CNY、Brent、WTI、沪金、沪银 | 伦敦金银代理 |
| 10 | 本月 IPO 进度；本周解禁规模与标的；本周回购/增持/分红 | — |
| 11 | 最近 5 个交易日重要新闻（宏观/全球/行业/公司/预警）| — |

---

## 必须回答的 4 个问题

1. 本周赚钱效应是在改善、分化，还是转弱？
2. 本周主导风格与主导板块是谁？
3. 外资与杠杆资金是在强化还是减弱？
4. 下周关键位与主要风险点是什么？

---

## 报告结构

```
一页看懂
先看结论
周度温度（赚钱效应变化）
板块轮动（全球市场摘要 + A股板块排序）
资金流向（北向周表 + 融资融券变化）
汇率商品与事项（USD/CNY、原油、金银、IPO、解禁、公司行为）
影响评分
置信度分解
行动框架
本周最重要的新闻（按宏观/全球/行业/公司分类，≤ 5 条/类）
数据可得性与缺口
```

---

## 资金流向表格式

```
| 日期  | 北向净流入 | 融资余额变化 |
|-------|-----------|-------------|
| Mon   | ¥x亿      | ¥x亿        |
| ...   |           |             |
| Total | ¥x亿      | ¥x亿        |
```

---

## 强制约束

- 结论必须明确：下周更适合看权重、看成长，还是看题材轮动。
- 结论必须给出执行节奏：进攻/均衡/防守/观望（由综合环境分+置信度共同决定）。
- 至少覆盖一项周度资金数据和一项周度事项数据。
- 不给买卖建议，只做波段环境解读。
- 各模块按"结论优先"输出，最多 4–6 条要点。
- 新闻按分类总计最多 6 条，避免长篇复述。

---

## 推荐模板

`templates/A股晨会简报_B_波段模板.md`
"""

# style → prompt 映射
_PROMPTS = {
    "full": FULL_PROMPT,
    "intraday": INTRADAY_PROMPT,
    "swing": SWING_PROMPT,
}


# ─────────────────────────────────────────────
# 策略
# ─────────────────────────────────────────────

@register_strategy(StrategyInfo(
    name="morning_brief",
    market="a_shares",
    live_capable=False,
    description="A股晨会简报自动生成",
))
class MorningBriefStrategy(StrategyBase):
    """A股晨会简报策略。

    流程：
        1. 经 ``core.data_feed`` 拉取指数日 K 与市场新闻
        2. 用 ``pivot`` 计算各指数枢轴点，用 ``scoring`` 计算固定公式评分
        3. 组装上下文，经 ``core.llm.get_llm()`` 按 prompt 规格生成简报
        4. 产出综合 ``Signal``（信息型，不给买卖建议）
        5. 可选经 ``core.alert`` 推送简报
    """

    def produce(
        self,
        symbols: list[str] | None = None,
        style: str = "full",
        **kwargs: Any,
    ) -> list[Signal]:
        """生成当日晨会简报并产出综合信号。

        Args:
            symbols: 观察指数代码列表（默认上证/创业板/沪深300）
            style: 简报档位 ``"full"`` / ``"intraday"`` / ``"swing"``
            **kwargs:
                news_limit: 市场新闻条数（默认 30）
                kline_limit: K线回看根数（默认 300）
                push: 是否推送简报到告警通道（默认 False）
                scoring_input: 显式 ``ScoringInput``；未传则按主指数 K线自动派生
                llm_provider: LLM provider 覆盖
                temperature: LLM 温度（默认 0.5）
        Returns:
            含一个综合信号的列表（已推入总线）；生成失败返回空列表
        """
        if style not in _PROMPTS:
            logger.warning("未知 style=%s，回退为 full", style)
            style = "full"

        symbols = list(symbols or self.config.get("symbols") or _DEFAULT_SYMBOLS)
        news_limit = int(kwargs.get("news_limit", self.config.get("news_limit", 30)))
        kline_limit = int(kwargs.get("kline_limit", self.config.get("kline_limit", 300)))
        push = bool(kwargs.get("push", self.config.get("push", False)))

        # 1) 拉数据
        ds = get_data_source(_MARKET)
        index_data = self._fetch_indices(ds, symbols, kline_limit)
        try:
            news_list = ds.get_news(symbol=None, limit=news_limit)
        except Exception:  # noqa: BLE001
            logger.exception("获取市场新闻失败")
            news_list = []

        # 2) 评分（固定公式）
        score: ScoreBreakdown | None = None
        scoring_input: ScoringInput | None = kwargs.get("scoring_input")
        if scoring_input is None:
            scoring_input = self._derive_scoring_input(index_data, symbols)
        if scoring_input is not None:
            try:
                score = score_environment(scoring_input)
            except Exception:  # noqa: BLE001
                logger.exception("评分计算失败，简报将缺少评分区块")
                score = None

        # 3) 组装上下文 + LLM 生成
        context = self._build_context(style, index_data, news_list, score, kwargs)
        brief = self._generate_brief(style, context, kwargs)
        if not brief:
            logger.error("晨会简报生成失败：LLM 返回空内容")
            return []

        # 4) 推送（可选）
        if push:
            self._push_brief(brief, style)

        # 5) 产出综合信号（信息型：direction=hold，不给买卖建议）
        sig = self._build_signal(style, brief, score, symbols)
        if sig is not None:
            self.publish(sig)
            return [sig]
        return []

    # ------------------------------------------------------------------
    # 数据抓取
    # ------------------------------------------------------------------

    def _fetch_indices(
        self,
        ds: Any,
        symbols: list[str],
        kline_limit: int,
    ) -> list[dict]:
        """抓取各指数日 K 并计算枢轴点 / 基础技术指标。"""
        out: list[dict] = []
        for sym in symbols:
            entry: dict = {"symbol": sym, "ok": False}
            try:
                df = ds.get_kline(sym, Interval.DAILY, limit=kline_limit)
            except Exception:  # noqa: BLE001
                logger.warning("获取 K线失败: %s", sym, exc_info=True)
                df = pd.DataFrame()
            if df is None or df.empty:
                out.append(entry)
                continue
            df = df.sort_values("datetime").reset_index(drop=True) if "datetime" in df.columns else df
            entry["df"] = df
            entry["pivots"] = pivots_from_klines(df)
            entry["ta"] = self._basic_ta(df)
            entry["last"] = self._last_row_summary(df)
            entry["ok"] = True
            out.append(entry)
        return out

    @staticmethod
    def _basic_ta(df: pd.DataFrame) -> dict:
        """纯 pandas 计算基础技术指标（MA20/50/200、RSI14、MACD 柱体）。

        数据不足时对应字段返回 None / False，不抛异常。
        """
        out: dict = {"above_ma20": False, "above_ma50": False, "above_ma200": False,
                     "rsi": None, "macd_positive": False}
        if df is None or df.empty or "close" not in df.columns:
            return out
        close = df["close"].astype(float)
        last_close = float(close.iloc[-1])

        if len(close) >= 20:
            out["above_ma20"] = last_close >= float(close.rolling(20).mean().iloc[-1])
        if len(close) >= 50:
            out["above_ma50"] = last_close >= float(close.rolling(50).mean().iloc[-1])
        if len(close) >= 200:
            out["above_ma200"] = last_close >= float(close.rolling(200).mean().iloc[-1])

        # RSI(14) SMA 口径
        if len(close) >= 15:
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            g = float(gain.iloc[-1]) if not gain.empty else 0.0
            l = float(loss.iloc[-1]) if not loss.empty else 0.0
            if l == 0:
                out["rsi"] = 100.0 if g > 0 else 50.0
            else:
                rs = g / l
                out["rsi"] = round(100 - 100 / (1 + rs), 1)

        # MACD 柱体（EMA12-EMA26，signal EMA9）
        if len(close) >= 35:
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal = macd_line.ewm(span=9, adjust=False).mean()
            hist = macd_line - signal
            out["macd_positive"] = float(hist.iloc[-1]) > 0

        return out

    @staticmethod
    def _last_row_summary(df: pd.DataFrame) -> dict:
        """取最后一根 K线的 OHLC 与日涨跌幅。"""
        if df is None or df.empty:
            return {}
        last = df.iloc[-1]
        close = float(last["close"])
        prev = float(df["close"].iloc[-2]) if len(df) >= 2 else close
        chg = (close - prev) / prev * 100 if prev else 0.0
        return {
            "close": close,
            "high": float(last.get("high", close)),
            "low": float(last.get("low", close)),
            "change_pct": round(chg, 2),
        }

    # ------------------------------------------------------------------
    # 评分输入派生
    # ------------------------------------------------------------------

    def _derive_scoring_input(
        self,
        index_data: list[dict],
        symbols: list[str],
    ) -> ScoringInput | None:
        """从主指数 K线派生评分输入（固定公式所需技术面 + 代理风险口径）。

        以首个成功抓取的指数为主锚；宏观/商品/事件证据计数与数据质量
        字段保持保守默认（无结构化证据源），可由调用方经 kwargs 覆盖。
        """
        primary = next((d for d in index_data if d.get("ok")), None)
        if primary is None or "ta" not in primary:
            return None
        ta = primary["ta"]
        pivots = primary.get("pivots") or {}
        last = primary.get("last") or {}
        above_pivot = bool(last.get("close", 0) >= pivots.get("P", 0)) if pivots else False
        etf_change = float(last.get("change_pct", 0.0))

        # 数据完整性：以成功抓取的指数数 + 新闻口径估算
        ok_count = sum(1 for d in index_data if d.get("ok"))
        total = len(symbols)

        return ScoringInput(
            above_ma20=ta["above_ma20"],
            above_ma50=ta["above_ma50"],
            above_ma200=ta["above_ma200"],
            rsi=ta["rsi"] if ta["rsi"] is not None else 50.0,
            macd_positive=ta["macd_positive"],
            above_pivot=above_pivot,
            breadth_available=False,          # 无广度数据 → 代理口径
            etf_change=etf_change,
            news_risk_adj=0.0,
            macro_bull=0, macro_bear=0,
            commodity_bull=0, commodity_bear=0,
            event_bull=0, event_bear=0,
            available=ok_count,
            total=total if total else 1,
            consistent=0, verifiable=0,       # 单源，未做双源校验
            gaps=0, divergences=0,
        )

    # ------------------------------------------------------------------
    # 上下文 / LLM
    # ------------------------------------------------------------------

    def _build_context(
        self,
        style: str,
        index_data: list[dict],
        news_list: list,
        score: ScoreBreakdown | None,
        kwargs: Any,
    ) -> str:
        """组装喂给 LLM 的市场上下文。"""
        lines: list[str] = []
        lines.append(f"# 当日市场上下文（生成时间 {datetime.now().isoformat(timespec='minutes')}）")
        lines.append(f"报告档位: {style}\n")

        lines.append("## 指数行情与技术状态")
        for d in index_data:
            sym = d["symbol"]
            if not d.get("ok"):
                lines.append(f"- {sym}: 数据缺失")
                continue
            last = d.get("last") or {}
            ta = d.get("ta") or {}
            pv = d.get("pivots") or {}
            lines.append(
                f"- {sym}: 收盘 {last.get('close')}  日涨跌 {last.get('change_pct')}%  "
                f"MA20{'✓' if ta.get('above_ma20') else '✗'} "
                f"MA50{'✓' if ta.get('above_ma50') else '✗'} "
                f"MA200{'✓' if ta.get('above_ma200') else '✗'}  "
                f"RSI {ta.get('rsi')}  MACD柱{'正' if ta.get('macd_positive') else '负'}"
            )
            if pv:
                lines.append(
                    f"  Pivot: P {pv['P']:.2f}  R1 {pv['R1']:.2f}  S1 {pv['S1']:.2f}  "
                    f"R2 {pv['R2']:.2f}  S2 {pv['S2']:.2f}"
                )
        lines.append("")

        lines.append(f"## 市场新闻（共 {len(news_list)} 条）")
        for i, n in enumerate(news_list[:20], 1):
            title = (getattr(n, "title", "") or "").strip().replace("\n", " ")
            src = getattr(n, "source", "")
            ts = getattr(n, "ts", "")
            lines.append(f"{i}. [{src} {ts}] {title}")
        if len(news_list) > 20:
            lines.append(f"...（另有 {len(news_list) - 20} 条未列出）")
        lines.append("")

        if score is not None:
            lines.append("## 影响评分（固定公式计算结果，禁止主观调整）")
            lines.append(f"- 技术结构强度: {score.tech:.1f}")
            lines.append(f"- 风险偏好温度: {score.risk:.1f}（{score.risk_label}{'，[代理]' if score.is_proxy else ''}）")
            lines.append(f"- 宏观与流动性支持: {score.macro:.1f}")
            lines.append(f"- 商品与通胀扰动: {score.commodity:.1f}")
            lines.append(f"- 事件冲击可控度: {score.event:.1f}")
            lines.append(f"- 综合环境分: {score.composite:.1f}")
            lines.append(f"- 数据完整性: {score.data_completeness:.1f}")
            lines.append(f"- 多源一致性: {score.source_consistency:.1f}")
            lines.append(f"- 技术信号清晰度: {score.tech_clarity:.1f}")
            lines.append(f"- 置信度总分: {score.confidence:.1f} [{score.confidence_level}]")
            lines.append(f"- 执行节奏: {score.pace}")
            lines.append("")
            lines.append("注：上述评分由 scoring.md 固定公式生成，请在简报中直接引用，不得改动。")
        else:
            lines.append("## 影响评分\n评分输入缺失，请在简报中标注数据缺口并按 Low 置信度处理。")
        lines.append("")

        return "\n".join(lines)

    def _generate_brief(self, style: str, context: str, kwargs: Any) -> str:
        """调用 LLM 按规格生成简报文本。"""
        prompt = _PROMPTS[style]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 A股晨会简报生成助手。严格按下方报告规格生成简报，"
                    "遵守其强制约束；影响评分区块必须直接引用上下文中给出的"
                    "固定公式结果，不得主观拍分；不给买卖建议。"
                ),
            },
            {"role": "system", "content": f"报告规格:\n{prompt}"},
            {
                "role": "user",
                "content": (
                    f"以下是当日市场上下文，请按报告规格生成今日晨会简报：\n\n"
                    f"{context}"
                ),
            },
        ]
        provider = kwargs.get("llm_provider")
        temperature = float(kwargs.get("temperature", 0.5))
        try:
            llm = get_llm(provider)
            resp = llm.chat(messages, temperature=temperature)
            return (resp.content or "").strip()
        except Exception:  # noqa: BLE001
            logger.exception("LLM 生成简报失败")
            return ""

    # ------------------------------------------------------------------
    # 信号 / 推送
    # ------------------------------------------------------------------

    def _build_signal(
        self,
        style: str,
        brief: str,
        score: ScoreBreakdown | None,
        symbols: list[str],
    ) -> Signal | None:
        """构建综合信号（信息型：direction=hold，不给买卖建议）。"""
        sig_score = (score.composite / 100.0) if score else 0.5
        confidence = (score.confidence / 100.0) if score else 0.2
        sig_score = max(0.0, min(1.0, sig_score))
        confidence = max(0.0, min(1.0, confidence))
        try:
            return Signal(
                symbol=",".join(symbols[:3]),
                market=_MARKET,
                timeframe="daily",
                direction="hold",           # 信息型信号，非买卖建议
                score=sig_score,
                confidence=confidence,
                source=_SOURCE,
                tags=["morning_brief", style] + ([score.pace] if score else []),
                ts=datetime.now(),
                meta={
                    "style": style,
                    "brief": brief,
                    "symbols": symbols,
                    "score": score.to_dict() if score else None,
                },
            )
        except ValueError as e:
            logger.warning("信号构造失败: %s", e)
            return None

    def _push_brief(self, brief: str, style: str) -> dict[str, bool]:
        """经 core.alert 推送简报到已启用通道。"""
        title = f"A股晨会简报 [{style}] {datetime.now().strftime('%Y-%m-%d')}"
        msg = AlertMessage(
            title=title,
            content=brief,
            level="info",
            source=_SOURCE,
            tags=["morning_brief", style],
        )
        try:
            return get_notifier().send(msg)
        except Exception:  # noqa: BLE001
            logger.exception("简报推送失败")
            return {}


# ─────────────────────────────────────────────
# scheduler 入口
# ─────────────────────────────────────────────

def generate(symbols: list[str] | None = None, style: str = "full", push: bool = True,
             **kwargs: Any) -> list[Signal]:
    """生成并（默认）推送当日晨会简报（供 apps.scheduler 调用）。

    Args:
        symbols: 观察指数列表（缺省读 config 或默认三指数）
        style: 简报档位 full / intraday / swing
        push: 是否推送简报（默认 True）
        **kwargs: 透传给 MorningBriefStrategy.produce
    Returns:
        当日综合信号列表
    """
    cfg = get_config(_MARKET).get("modules", {}).get("morning_brief", {})
    strategy = MorningBriefStrategy(config=cfg)
    return strategy.produce(symbols=symbols, style=style, push=push, **kwargs)

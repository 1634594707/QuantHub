"""美股实时分析器（us_stocks_realtime_analyzer）。

参照 a_shares/realtime_analyzer 的结构，但抓数层直接复用 core.data_feed
已有的 Yahoo 数据源（项目内置，已经在服务 /data/kline 接口被调用），
避免重复写 HTTP 抓取 + 解析。LLM 行为保持一致：未配置 LLM 时降级为
纯行情/指标快照报告。

输出 Signal.market = "us_stocks"，与 /signals 查询和前端 RadarPage 期望一致。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
from typing import Any

from core.data_feed.factory import get_data_source
from core.signals import Signal
from strategies import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# 美股代码：1-5 位字母（NVDA、AVGO、AAPL、TSLA、BRK.B）
# 允许用户传 . 形式（BRK.B），统一为 "BRK-B"（Yahoo 用 -）
# 同时允许带连字符的复合 code（如 BTC-USDT 之类跨市场 hash code 会走别的数据源）。
_US_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,12}$")


def normalize_code(code: str) -> str:
    c = code.strip().upper().replace(" ", "")
    if not _US_CODE_RE.match(c):
        raise ValueError(f"Unsupported US code format: {code}")
    # Yahoo chart 接口对 BRK.B 期望写成 BRK-B
    return c.replace(".", "-")


def parse_codes(raw: str) -> list[str]:
    parts = [x for x in re.split(r"[,，\s]+", raw.strip()) if x]
    out: list[str] = []
    for p in parts:
        try:
            c = normalize_code(p)
        except ValueError:
            continue
        if c not in out:
            out.append(c)
    return out


def _safe_float(x) -> float | None:
    try:
        v = float(x)
        if math.isnan(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def fetch_quotes(codes: list[str]) -> list[dict]:
    """美股当前盘口：走 core data_feed（实时报价）→ 拿不到则空。"""
    if not codes:
        return []
    src = get_data_source("us_stocks")
    out: list[dict] = []
    for c in codes:
        try:
            q = src.get_realtime_quote(c) if hasattr(src, "get_realtime_quote") else None
        except Exception:  # noqa: BLE001 - data sources expose provider-specific failures
            q = None
        if q:
            out.append(
                {
                    "code": c,
                    "name": getattr(q, "name", c),
                    "last": _safe_float(getattr(q, "price", None)),
                    "pct": _safe_float(getattr(q, "change_pct", None)),
                    "prev_close": _safe_float(getattr(q, "prev_close", None)),
                }
            )
    return out


def _ma(vals: list[float], n: int) -> float | None:
    if len(vals) < n:
        return None
    return round(sum(vals[-n:]) / n, 4)


def _ret(vals: list[float], n: int) -> float | None:
    if len(vals) <= n:
        return None
    base = vals[-(n + 1)]
    if not base:
        return None
    return round((vals[-1] / base - 1) * 100, 4)


def _resolve_market_for_code(code: str) -> str:
    """根据 code 形态派发到对应数据源 market。

    Yahoo 只覆盖美股；带连字符的复合 code（如 BTC-USDT、ETH-USDT）
    派发到 crypto 源（okx），按 data source market 路由。
    """
    if "-" in code and not code.startswith("BRK-"):
        return "crypto"
    return "us_stocks"


def fetch_kline(code: str, days: int = 60) -> dict:
    """日 K + 均线/回报指标。按 code 形态自动选数据源（Yahoo / okx）。"""
    market = _resolve_market_for_code(code)
    src = get_data_source(market)
    try:
        df = src.get_kline(code, "1d", limit=days)
    except Exception as exc:  # noqa: BLE001 - data sources expose provider-specific failures
        logger.warning("us_stocks_realtime: K 线拉取失败 %s (market=%s): %s", code, market, exc)
        return {"metrics": {}, "klines": []}
    if df is None or df.empty:
        return {"metrics": {}, "klines": []}

    klines: list[dict] = []
    closes: list[float] = []
    for _, row in df.iterrows():
        close = _safe_float(row.get("close"))
        if close is None:
            continue
        rec = {
            "date": str(row.get("date") or row.name),
            "open": _safe_float(row.get("open")),
            "close": close,
            "high": _safe_float(row.get("high")),
            "low": _safe_float(row.get("low")),
            "volume": _safe_float(row.get("volume")),
        }
        klines.append(rec)
        closes.append(close)

    metrics = {
        "latest_date": klines[-1]["date"] if klines else None,
        "close": closes[-1] if closes else None,
        "ret_5d_pct": _ret(closes, 5),
        "ret_10d_pct": _ret(closes, 10),
        "ret_20d_pct": _ret(closes, 20),
        "ma5": _ma(closes, 5),
        "ma10": _ma(closes, 10),
        "ma20": _ma(closes, 20),
        "high_10d": max(closes[-10:]) if len(closes) >= 10 else (max(closes) if closes else None),
        "low_10d": min(closes[-10:]) if len(closes) >= 10 else (min(closes) if closes else None),
    }
    return {"metrics": metrics, "klines": klines}


_SYSTEM_PROMPT = """\
你是一位专业的美股分析师，遵循"证据优先、过程透明"的分析原则。

## 核心原则
1. **证据绑定**：每个关键结论必须附有数据依据。
2. **双逻辑分离**：每只股票判断拆分为 产业逻辑 + 交易逻辑。
3. **三情景输出**：给出 强/中/弱 三个价格情景及对应操作。
4. **不确定性标注**：置信度低于"中"时明确写出不确定因素。

## 分析报告必须包含
### 0) 数据摘要
### 1) 市场背景
### 2) 逐股深度分析
1. 业务定位 2. 当前叙事与阶段 3. 板块与龙头
4. 技术面（MA5/MA10/MA20、压力/支撑） 5. 事件面 6. 双逻辑判断 7. 三情景动作 8. 证据卡片 9. 置信度
### 3) 不确定性与自我修正
### 4) 一句话总结（≤30字）

仅基于调用方提供的结构化数据写作"数据摘要"；基本面部分须明确标注"需联网核实"。
输出语言：中文。
"""


@register_strategy(
    StrategyInfo(
        name="realtime_analyzer_us",
        market="us_stocks",
        version="0.1.0",
        live_capable=False,
        description="实时美股盘口+Yahoo日K，GPT/DeepSeek深度研报(实盘默认关)",
    )
)
class RealtimeAnalyzerUsStrategy(StrategyBase):
    """实时美股分析器（实盘默认关闭）。"""

    def _resolve_codes(self, codes: Any) -> list[str]:
        if codes:
            raw = codes if isinstance(codes, str) else ",".join(codes)
            return parse_codes(raw)
        cfg = self.config.get("default_codes") or ["NVDA", "AVGO"]
        return parse_codes(",".join(cfg))

    def produce(
        self,
        codes: Any = None,
        with_kline: bool = True,
        kline_days: int = 60,
        **kwargs,
    ) -> list[Signal]:
        target = self.config.get("default_codes")
        codes = self._resolve_codes(codes or target)
        if not codes:
            logger.warning("realtime_analyzer_us: 无可用股票代码，跳过")
            return []

        logger.info("realtime_analyzer_us: 分析 %d 只美股", len(codes))
        market_data: dict[str, Any] = {
            "timestamp": dt.datetime.now(dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "codes": codes,
            "market": "us_stocks",
            "quotes": fetch_quotes(codes),
        }
        if with_kline:
            kline = {}
            for c in codes:
                kline[c] = fetch_kline(c, days=kline_days)
            market_data["kline"] = kline

        has_llm = False
        report = self._build_report(market_data)
        if report is not None:
            has_llm = True
        else:
            report = self._snapshot_only_report(market_data)

        meta = {
            "report": report,
            "has_llm": has_llm,
            "market_data": market_data,
        }
        # 与 A 股 realtime_analyzer 一致：单条聚合信号，symbol = codes[0]
        sym = codes[0] if codes else "US_STOCKS"
        sig = Signal(
            symbol=sym,
            market="us_stocks",
            timeframe="realtime",
            direction="hold",
            score=0.5,
            confidence=0.6 if has_llm else 0.3,
            source="realtime_analyzer_us",
            tags=["analysis", "report", "us", "llm" if has_llm else "snapshot"],
            meta=meta,
        )
        self.publish(sig)
        return [sig]

    def _build_report(self, market_data: dict) -> str | None:
        try:
            from core.llm import get_llm

            llm = get_llm()
        except Exception as exc:  # noqa: BLE001 - optional LLM providers vary by installation
            logger.warning("realtime_analyzer_us: LLM 不可用（%s），降级为快照报告", exc)
            return None
        user_msg = "\n".join(
            [
                "## 分析请求",
                f"- 时间戳：{market_data.get('timestamp')}",
                "- 市场：美股 (us_stocks)",
                f"- 分析标的：{', '.join(market_data.get('codes', []))}",
                "",
                "## 结构化市场数据（JSON）",
                "```json",
                json.dumps(market_data, ensure_ascii=False, indent=2),
                "```",
                "",
                "请严格按照『分析报告结构』输出完整报告。",
            ]
        )
        try:
            resp = llm.chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.3,
                max_tokens=2000,
            )
            return resp.content
        except Exception:  # noqa: BLE001 - provider SDKs expose different exception hierarchies
            logger.exception("realtime_analyzer_us: LLM 调用失败")
            return None

    @staticmethod
    def _snapshot_only_report(market_data: dict) -> str:
        lines = ["[快照模式] 未配置 LLM，仅输出美股行情摘要：", ""]
        for q in market_data.get("quotes", []):
            lines.append(
                f"- {q.get('name', '')}({q.get('code', '')}) "
                f"最新 {q.get('last')} 涨跌幅 {q.get('pct')}%"
            )
        kline = market_data.get("kline", {})
        for c, k in kline.items():
            m = k.get("metrics", {}) if isinstance(k, dict) else {}
            if m:
                lines.append(
                    f"- {c} MA5={m.get('ma5')} MA20={m.get('ma20')} "
                    f"RET5D={m.get('ret_5d_pct')}% RET20D={m.get('ret_20d_pct')}%"
                )
        return "\n".join(lines)

    def backtest(self, klines: Any = None, **kwargs):
        from core.backtest.engine import BacktestResult

        return BacktestResult.empty(engine="none")

    def live_tick(self, tick: Any = None, **kwargs) -> None:
        if not self.is_live():
            logger.info("realtime_analyzer_us: dry-run tick（未开实盘），跳过下单")
            return
        logger.warning("realtime_analyzer_us: 实盘模式下也只产出研报，不主动下单")

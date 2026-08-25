"""美股实时分析器（us_stocks_realtime_analyzer）。

参照 a_shares/realtime_analyzer 的结构，但抓数层只复用 core.data_feed
中为 ``us_stocks`` 配置的唯一 primary。LLM 行为保持一致：未配置 LLM
时仅保存行情/指标快照，绝不以旧源或其他市场代替当前美股行情。

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
from strategies.signal_contract import SIGNAL_MARKER, parse_report_signal

logger = logging.getLogger(__name__)
_DEFAULT_MAX_QUOTE_AGE_MINUTES = 12 * 60
# MA20 plus a 20-bar return need at least 21 valid closes.
_DEFAULT_MIN_KLINE_BARS = 21

# 美股输入仅接受 ticker 或 class-share 的点号形式（BRK.B）。
# 连字符是 Yahoo 内部的规范化结果，绝不能作为用户输入或触发 crypto 路由。
_US_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,9}(?:\.[A-Za-z0-9]{1,4})?$")


def normalize_code(code: str) -> str:
    c = code.strip().upper().replace(" ", "")
    if not _US_CODE_RE.match(c):
        raise ValueError(f"Unsupported US code format: {code}")
    # 当前 primary 若需要 BRK-B，由此处的已验证美股输入规范化得到。
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


def fetch_quotes(codes: list[str], *, source: Any | None = None) -> list[dict]:
    """美股当前盘口只走 us_stocks configured primary。"""
    if not codes:
        return []
    src = source or get_data_source("us_stocks")
    out: list[dict] = []
    for c in codes:
        try:
            q = src.get_realtime_quote(c)
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
                    "source": getattr(q, "source", None),
                    "market": getattr(q, "market", None),
                    "observed_at": getattr(q, "observed_at", None).isoformat()
                    if getattr(q, "observed_at", None) is not None
                    else None,
                    "verified": True,
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


def fetch_kline(code: str, days: int = 60, *, source: Any | None = None) -> dict:
    """日 K + 均线/回报指标，只从 us_stocks primary 读取。"""
    src = source or get_data_source("us_stocks")
    source_name = str(getattr(src, "name", "unknown"))
    try:
        df = src.get_kline(code, "1d", limit=days)
    except Exception as exc:  # noqa: BLE001 - data sources expose provider-specific failures
        logger.warning("us_stocks_realtime: K 线拉取失败 %s (market=us_stocks): %s", code, exc)
        return _empty_kline(source_name)
    if df is None or df.empty:
        return _empty_kline(source_name)

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
    contract = df.attrs.get("_data_contract", {})
    return {
        "metrics": metrics,
        "klines": klines,
        "available": bool(klines),
        "source": str(df.attrs.get("_source") or source_name),
        "semantics": contract.get("kline_semantics", "bar_snapshot"),
    }


def _empty_kline(source_name: str) -> dict:
    return {
        "metrics": {},
        "klines": [],
        "available": False,
        "source": source_name,
        "semantics": "bar_snapshot",
    }


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

报告最后一行必须输出机器可读信号，不得省略或放进代码块：
QUANTHUB_SIGNAL_JSON:{"direction":"buy|sell|hold","score":0到1,"confidence":0到1}
其中 score 与 confidence 必须来自本次分析证据；无法计算时不要输出该行。
"""


@register_strategy(
    StrategyInfo(
        name="realtime_analyzer_us",
        market="us_stocks",
        version="0.1.0",
        live_capable=False,
        description="实时美股盘口+configured-primary 日K，GPT/DeepSeek深度研报(实盘默认关)",
    )
)
class RealtimeAnalyzerUsStrategy(StrategyBase):
    """实时美股分析器（实盘默认关闭）。"""

    def _resolve_codes(self, codes: Any) -> list[str]:
        if codes is None:
            codes = self.config.get("default_codes")
        if isinstance(codes, str):
            return parse_codes(codes)
        if isinstance(codes, (list, tuple)):
            return parse_codes(",".join(str(item) for item in codes))
        return []

    def _reject_configuration(self, *, reason: str) -> list[Signal]:
        details = {
            "market": "us_stocks",
            "reason": reason,
            "codes": [],
        }
        self.last_report = {
            "kind": "configuration",
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            **details,
        }
        self.last_signal_rejection = {
            "code": "symbols_required",
            "message": "美股实时分析未配置明确标的，未启动分析。",
            "details": details,
        }
        logger.warning("realtime_analyzer_us 配置不完整，跳过分析: %s", reason)
        return []

    def produce(
        self,
        codes: Any = None,
        with_kline: bool = True,
        kline_days: int = 60,
        **kwargs,
    ) -> list[Signal]:
        self.last_report = None
        self.last_signal_rejection = None
        requested_codes = codes if codes is not None else self.config.get("default_codes")
        codes = self._resolve_codes(requested_codes)
        if not codes:
            return self._reject_configuration(
                reason="未提供明确股票代码（调用参数 codes 或 modules.realtime_analyzer.default_codes）"
            )

        # 只有调用方明确传入 ``with_kline=False`` 才允许 quote-only 运行。
        # 省略参数、传入 None 或其他值都保持默认的 K 线证据闸门。
        kline_requested = with_kline is not False
        realtime_only = not kline_requested
        logger.info("realtime_analyzer_us: 分析 %d 只美股", len(codes))
        try:
            source = get_data_source("us_stocks")
        except Exception as exc:  # noqa: BLE001 - primary construction must fail closed
            return self._reject_market_data(
                {
                    "timestamp": dt.datetime.now(dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                    "codes": codes,
                    "market": "us_stocks",
                    "quotes": [],
                    "data_source": "unavailable",
                    "kline_requested": kline_requested,
                    "realtime_only": realtime_only,
                    "display_only": realtime_only,
                    "degraded": realtime_only,
                    "execution_eligible": not realtime_only,
                },
                code="market_data_unavailable",
                message="美股 primary 数据源不可用；未生成分析信号。",
                details={"error": str(exc), "market": "us_stocks"},
            )
        market_data: dict[str, Any] = {
            "timestamp": dt.datetime.now(dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "codes": codes,
            "market": "us_stocks",
            "quotes": fetch_quotes(codes, source=source),
            "data_source": source.name,
        }
        kline: dict[str, Any] = {}
        if kline_requested:
            for c in codes:
                try:
                    kline[c] = fetch_kline(c, days=kline_days, source=source)
                except Exception as exc:  # noqa: BLE001 - preserve a visible primary failure
                    logger.warning("美股 primary K 线失败 %s，不切换数据源: %s", c, exc)
                    kline[c] = {
                        "metrics": {},
                        "klines": [],
                        "available": False,
                        "source": source.name,
                        "semantics": "bar_snapshot",
                        "error": str(exc),
                    }
            market_data["kline"] = kline
        market_data["kline_requested"] = kline_requested
        market_data["realtime_only"] = realtime_only
        market_data["display_only"] = realtime_only
        market_data["degraded"] = realtime_only
        market_data["execution_eligible"] = not realtime_only

        rejection = self._validate_quotes(codes, market_data["quotes"], source.name)
        if rejection is not None:
            return self._reject_market_data(market_data, **rejection)
        if kline_requested:
            rejection = self._validate_klines(codes, market_data.get("kline"), source.name)
            if rejection is not None:
                return self._reject_market_data(market_data, **rejection)

        has_llm = False
        report = self._build_report(market_data)
        if report is not None:
            has_llm = True
        else:
            report = self._snapshot_only_report(market_data)

        self.last_report = {
            "kind": "llm_analysis" if has_llm else "market_snapshot",
            "report": report,
            "has_llm": has_llm,
            "market_data": market_data,
            "realtime_only": realtime_only,
            "display_only": realtime_only,
            "degraded": realtime_only,
            "execution_eligible": not realtime_only,
        }
        if not has_llm:
            market_data.update(display_only=True, degraded=True, execution_eligible=False)
            self.last_report.update(display_only=True, degraded=True, execution_eligible=False)
            self.last_signal_rejection = {
                "code": "model_unavailable",
                "message": "LLM 不可用；已保存行情快照，但未发布带数值把握度的信号。",
                "details": {"source": "realtime_analyzer_us"},
            }
            return []

        signal_values = parse_report_signal(report)
        if signal_values is None:
            market_data.update(display_only=True, degraded=True, execution_eligible=False)
            self.last_report.update(display_only=True, degraded=True, execution_eligible=False)
            self.last_signal_rejection = {
                "code": "structured_signal_missing",
                "message": f"分析报告缺少有效的 {SIGNAL_MARKER} 结构，未发布信号。",
                "details": {"source": "realtime_analyzer_us"},
            }
            return []

        meta = dict(self.last_report)
        # 与 A 股 realtime_analyzer 一致：单条聚合信号，symbol = codes[0]
        sym = codes[0] if codes else "US_STOCKS"
        sig = Signal(
            symbol=sym,
            market="us_stocks",
            timeframe="realtime",
            direction=signal_values["direction"],
            score=signal_values["score"],
            confidence=signal_values["confidence"],
            source="realtime_analyzer_us",
            tags=["analysis", "report", "us", "llm", "structured_signal"],
            meta=meta,
        )
        self.publish(sig)
        return [sig]

    def _validate_klines(
        self,
        codes: list[str],
        klines: Any,
        expected_source: str,
    ) -> dict[str, Any] | None:
        """Validate primary K-line evidence before invoking the LLM."""
        if not isinstance(klines, dict):
            return {
                "code": "market_data_incomplete",
                "message": "美股 primary K 线不可用；未生成结构化分析信号。",
                "details": {
                    "reason": "kline_not_mapping",
                    "expected_source": expected_source,
                },
            }

        configured_min = self.config.get("min_kline_bars", _DEFAULT_MIN_KLINE_BARS)
        try:
            min_bars = max(_DEFAULT_MIN_KLINE_BARS, int(configured_min))
        except (TypeError, ValueError):
            min_bars = _DEFAULT_MIN_KLINE_BARS

        for code in codes:
            payload = klines.get(code)
            if not isinstance(payload, dict):
                return {
                    "code": "market_data_incomplete",
                    "message": "美股 primary K 线覆盖不足；未生成结构化分析信号。",
                    "details": {
                        "reason": "kline_missing",
                        "symbol": code,
                        "expected_source": expected_source,
                    },
                }
            rows = payload.get("klines")
            if payload.get("available") is not True or not isinstance(rows, list) or not rows:
                return {
                    "code": "market_data_incomplete",
                    "message": "美股 primary K 线为空或不可用；未生成结构化分析信号。",
                    "details": {
                        "reason": "kline_unavailable",
                        "symbol": code,
                        "expected_source": expected_source,
                    },
                }
            if payload.get("source") != expected_source:
                return {
                    "code": "market_data_incomplete",
                    "message": "美股 primary K 线来源无法核验；未生成结构化分析信号。",
                    "details": {
                        "reason": "kline_unverified",
                        "symbol": code,
                        "expected_source": expected_source,
                        "actual_source": payload.get("source"),
                    },
                }
            if len(rows) < min_bars:
                return {
                    "code": "market_data_incomplete",
                    "message": "美股 primary K 线证据不足；未生成结构化分析信号。",
                    "details": {
                        "reason": "kline_insufficient",
                        "symbol": code,
                        "expected_source": expected_source,
                        "required_bars": min_bars,
                        "actual_bars": len(rows),
                    },
                }
            closes: list[float] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    close = float(row.get("close"))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(close) and close > 0:
                    closes.append(close)
            if len(closes) < min_bars:
                return {
                    "code": "market_data_incomplete",
                    "message": "美股 primary K 线有效收盘价不足；未生成结构化分析信号。",
                    "details": {
                        "reason": "kline_close_insufficient",
                        "symbol": code,
                        "expected_source": expected_source,
                        "required_bars": min_bars,
                        "actual_bars": len(closes),
                    },
                }
            metrics = payload.get("metrics")
            if not isinstance(metrics, dict):
                return {
                    "code": "market_data_incomplete",
                    "message": "美股 primary K 线指标证据不足；未生成结构化分析信号。",
                    "details": {
                        "reason": "kline_metrics_missing",
                        "symbol": code,
                        "expected_source": expected_source,
                    },
                }
            for metric in ("close", "ma5", "ma10", "ma20"):
                try:
                    value = float(metrics.get(metric))
                except (TypeError, ValueError):
                    value = float("nan")
                if not math.isfinite(value) or value <= 0:
                    return {
                        "code": "market_data_incomplete",
                        "message": "美股 primary K 线指标证据不足；未生成结构化分析信号。",
                        "details": {
                            "reason": "kline_metric_missing",
                            "symbol": code,
                            "metric": metric,
                            "expected_source": expected_source,
                        },
                    }
        return None

    def _validate_quotes(
        self,
        codes: list[str],
        quotes: Any,
        expected_source: str,
    ) -> dict[str, Any] | None:
        if not isinstance(quotes, list):
            return {
                "code": "market_data_unavailable",
                "message": "美股 primary 未返回可验证的实时行情；未生成分析信号。",
                "details": {"reason": "quotes_not_list", "expected_source": expected_source},
            }
        by_code = {
            str(item.get("code", "")).upper(): item for item in quotes if isinstance(item, dict)
        }
        max_age_minutes = self.config.get("max_quote_age_minutes", _DEFAULT_MAX_QUOTE_AGE_MINUTES)
        try:
            max_age = dt.timedelta(minutes=max(1, int(max_age_minutes)))
        except (TypeError, ValueError):
            max_age = dt.timedelta(minutes=_DEFAULT_MAX_QUOTE_AGE_MINUTES)
        now = dt.datetime.now(dt.UTC)
        for code in codes:
            quote = by_code.get(code)
            if quote is None:
                return {
                    "code": "market_data_unavailable",
                    "message": "美股 primary 行情覆盖不足；未生成分析信号。",
                    "details": {
                        "reason": "quote_missing",
                        "symbol": code,
                        "expected_source": expected_source,
                    },
                }
            try:
                last = float(quote.get("last"))
            except (TypeError, ValueError):
                last = float("nan")
            if (
                not math.isfinite(last)
                or last <= 0
                or quote.get("source") != expected_source
                or quote.get("market") != "us_stocks"
                or quote.get("verified") is not True
            ):
                return {
                    "code": "market_data_unavailable",
                    "message": "美股 primary 行情缺少可信价格或来源标识；未生成分析信号。",
                    "details": {
                        "reason": "quote_unverified",
                        "symbol": code,
                        "expected_source": expected_source,
                    },
                }
            observed_at = self._parse_observed_at(quote.get("observed_at"))
            if observed_at is None:
                return {
                    "code": "market_data_unavailable",
                    "message": "美股 primary 行情缺少观察时间；未生成分析信号。",
                    "details": {"reason": "quote_time_missing", "symbol": code},
                }
            age = now - observed_at
            if age > max_age or age < -dt.timedelta(minutes=5):
                return {
                    "code": "market_quote_stale",
                    "message": "美股 primary 行情已过期；未生成分析信号。",
                    "details": {
                        "reason": "quote_stale",
                        "symbol": code,
                        "observed_at": observed_at.isoformat(),
                        "max_age_minutes": int(max_age.total_seconds() / 60),
                    },
                }
        return None

    @staticmethod
    def _parse_observed_at(value: Any) -> dt.datetime | None:
        if isinstance(value, dt.datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = dt.datetime.fromisoformat(value)
            except ValueError:
                return None
        else:
            return None
        return parsed.astimezone(dt.UTC) if parsed.tzinfo is not None else None

    def _reject_market_data(
        self,
        market_data: dict[str, Any],
        *,
        code: str,
        message: str,
        details: dict[str, Any],
    ) -> list[Signal]:
        market_data["display_only"] = True
        market_data["degraded"] = True
        market_data["execution_eligible"] = False
        self.last_report = {
            "kind": "market_snapshot",
            "status": "unavailable",
            "report": self._snapshot_only_report(market_data),
            "has_llm": False,
            "market_data": market_data,
            "realtime_only": bool(market_data.get("realtime_only")),
            "display_only": True,
            "degraded": True,
            "execution_eligible": False,
        }
        self.last_signal_rejection = {
            "code": code,
            "message": message,
            "details": {"source": "realtime_analyzer_us", "market": "us_stocks", **details},
        }
        return []

    def _build_report(self, market_data: dict) -> str | None:
        try:
            from core.llm import get_llm

            llm = get_llm()
        except Exception as exc:  # noqa: BLE001 - optional LLM providers vary by installation
            logger.warning("realtime_analyzer_us: LLM 不可用（%s），仅记录快照且不发布信号", exc)
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

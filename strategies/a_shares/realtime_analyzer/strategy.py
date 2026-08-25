"""实时 A 股分析器策略 — QuantHub 迁移版。

把 ``trading-master/02-A-stock-realtime-analyzer`` 的实时分析能力下沉为
策略插件：

- 抓数层只走 ``core.data_feed`` 中配置的单一 primary；实时报价必须带来源
  与观察时间，不能用历史 K 线、缓存或另一供应商代替。
- LLM 层复用 ``core.llm.get_llm()``（与全仓统一，自动解析 GPT/DeepSeek 后端）。
- 产出：深度研报（文本）+ 一条 info 级 Signal（``direction="hold"``，
  真实买卖信号由研报文本承载，Signal 仅作"分析已产出"的登记与路由占位）。

实盘：默认关。即便开，本策略只产出研报，不主动下单。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from typing import Any

from core.data_feed.factory import get_data_source
from core.signals import Signal
from strategies import StrategyBase, StrategyInfo, register_strategy
from strategies.signal_contract import SIGNAL_MARKER, parse_report_signal

from .fetchers import (
    fetch_index_baseline,
    fetch_kline,
    fetch_quotes,
    parse_codes,
)

logger = logging.getLogger(__name__)
_DEFAULT_MAX_QUOTE_AGE_MINUTES = 12 * 60
# MA20 plus a 20-bar return need at least 21 valid closes.
_DEFAULT_MIN_KLINE_BARS = 21

_SYSTEM_PROMPT = """\
你是一位专业的A股分析师，遵循严格的"证据优先、过程透明"分析原则。

## 核心原则
1. **证据绑定**：每个关键结论必须附有来源/数据依据，禁止无依据主观猜测。
2. **双逻辑分离**：所有股票判断必须拆分为 产业逻辑 + 交易逻辑 两层。
3. **三情景输出**：每只股票给出 强/中/弱 三个价格情景及对应操作动作。
4. **不确定性标注**：置信度低于"中"时，必须明确写出不确定因素与修正计划。

## 分析报告必须包含以下结构（按顺序）
### 0) 数据摘要（Data Summary）
- 展示从调用方提供的结构化数据中读取到的关键指标。
### 1) 市场情绪底色
- 指数涨跌（上证/深成/创业板）+ 宽度（上涨/下跌家数）
### 2) 逐股深度分析（每只股票必须包含）
1. 公司业务定位 2. 当前市场叙事与阶段 3. 行业龙头与板块阶段
4. 技术面（MA5/MA10/MA20、关键压力位/支撑位）
5. 舆情与事件面 6. 双逻辑判断 7. 明日三情景动作 8. 证据卡片 9. 置信度
### 3) 组合分层建议（若多只）
### 4) 不确定性与自我修正
### 5) 一句话总结（≤30字，格式：「{股票}：{状态} — {建议动作}」）

仅基于调用方提供的结构化数据写作"数据摘要"；基本面部分须明确标注"需联网核实"。
输出语言：中文为主，技术指标名词可中英混写。

报告最后一行必须输出机器可读信号，不得省略或放进代码块：
QUANTHUB_SIGNAL_JSON:{"direction":"buy|sell|hold","score":0到1,"confidence":0到1}
其中 score 与 confidence 必须来自本次分析证据；无法计算时不要输出该行。
"""


@register_strategy(
    StrategyInfo(
        name="realtime_analyzer",
        market="a_shares",
        version="1.0.0",
        live_capable=False,
        description="实时A股盘口+日K+指数宽度，GPT/DeepSeek深度研报(实盘默认关)",
    )
)
class RealtimeAnalyzerStrategy(StrategyBase):
    """实时 A 股分析器（实盘默认关闭）。"""

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
            "market": "a_shares",
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
            "message": "A股实时分析未配置明确标的，未启动分析。",
            "details": details,
        }
        logger.warning("realtime_analyzer 配置不完整，跳过分析: %s", reason)
        return []

    def produce(
        self,
        codes: Any = None,
        with_kline: bool = True,
        kline_days: int = 60,
        with_indices: bool = True,
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
        logger.info("realtime_analyzer: 抓取 %d 只实时行情", len(codes))
        try:
            source = get_data_source("a_shares")
        except Exception as exc:  # noqa: BLE001 - primary construction must fail closed
            return self._reject_market_data(
                {
                    "timestamp": dt.datetime.now(dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                    "codes": codes,
                    "quotes": [],
                    "data_source": "unavailable",
                    "kline_requested": kline_requested,
                    "realtime_only": realtime_only,
                    "display_only": realtime_only,
                    "degraded": realtime_only,
                    "execution_eligible": not realtime_only,
                },
                code="market_data_unavailable",
                message="A股 primary 数据源不可用；未生成分析信号。",
                details={"error": str(exc), "market": "a_shares"},
            )
        market_data: dict[str, Any] = {
            "timestamp": dt.datetime.now(dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "codes": codes,
            "quotes": fetch_quotes(codes, source=source),
            "data_source": source.name,
        }
        if with_indices:
            market_data["indices"] = fetch_index_baseline(source=source)
        kline: dict[str, Any] = {}
        if kline_requested:
            for c in codes:
                try:
                    kline[c] = fetch_kline(c, days=kline_days, source=source)
                except Exception as exc:  # noqa: BLE001 - preserve a visible primary failure
                    logger.warning("A股 primary K 线失败 %s，不切换数据源: %s", c, exc)
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
                "details": {"source": "realtime_analyzer"},
            }
            return []

        signal_values = parse_report_signal(report)
        if signal_values is None:
            market_data.update(display_only=True, degraded=True, execution_eligible=False)
            self.last_report.update(display_only=True, degraded=True, execution_eligible=False)
            self.last_signal_rejection = {
                "code": "structured_signal_missing",
                "message": f"分析报告缺少有效的 {SIGNAL_MARKER} 结构，未发布信号。",
                "details": {"source": "realtime_analyzer"},
            }
            return []

        meta = dict(self.last_report)
        sym = codes[0] if codes else "A_SHARES"
        sig = Signal(
            symbol=sym,
            market="a_shares",
            timeframe="realtime",
            direction=signal_values["direction"],
            score=signal_values["score"],
            confidence=signal_values["confidence"],
            source="realtime_analyzer",
            tags=["analysis", "report", "llm", "structured_signal"],
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
        """Validate the primary K-line evidence before invoking the LLM.

        A realtime quote can be useful for a display-only snapshot, but it is
        not a substitute for the daily bars requested by the default analysis
        mode.  Keep this check at the strategy boundary because the fetcher
        intentionally converts provider errors and empty frames into an
        explicit unavailable payload.
        """
        if not isinstance(klines, dict):
            return {
                "code": "market_data_incomplete",
                "message": "A股 primary K 线不可用；未生成结构化分析信号。",
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
                    "message": "A股 primary K 线覆盖不足；未生成结构化分析信号。",
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
                    "message": "A股 primary K 线为空或不可用；未生成结构化分析信号。",
                    "details": {
                        "reason": "kline_unavailable",
                        "symbol": code,
                        "expected_source": expected_source,
                    },
                }
            if payload.get("source") != expected_source:
                return {
                    "code": "market_data_incomplete",
                    "message": "A股 primary K 线来源无法核验；未生成结构化分析信号。",
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
                    "message": "A股 primary K 线证据不足；未生成结构化分析信号。",
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
                    "message": "A股 primary K 线有效收盘价不足；未生成结构化分析信号。",
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
                    "message": "A股 primary K 线指标证据不足；未生成结构化分析信号。",
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
                        "message": "A股 primary K 线指标证据不足；未生成结构化分析信号。",
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
                "message": "A股 primary 未返回可验证的实时行情；未生成分析信号。",
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
                    "message": "A股 primary 行情覆盖不足；未生成分析信号。",
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
                or quote.get("market") != "a_shares"
                or quote.get("verified") is not True
            ):
                return {
                    "code": "market_data_unavailable",
                    "message": "A股 primary 行情缺少可信价格或来源标识；未生成分析信号。",
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
                    "message": "A股 primary 行情缺少观察时间；未生成分析信号。",
                    "details": {"reason": "quote_time_missing", "symbol": code},
                }
            age = now - observed_at
            if age > max_age or age < -dt.timedelta(minutes=5):
                return {
                    "code": "market_quote_stale",
                    "message": "A股 primary 行情已过期；未生成分析信号。",
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
            "details": {"source": "realtime_analyzer", "market": "a_shares", **details},
        }
        return []

    def _build_report(self, market_data: dict) -> str | None:
        try:
            from core.llm import get_llm

            llm = get_llm()
        except Exception as exc:  # noqa: BLE001 - optional LLM providers vary by installation
            logger.warning("realtime_analyzer: LLM 不可用（%s），仅记录快照且不发布信号", exc)
            return None
        user_msg = "\n".join(
            [
                "## 分析请求",
                f"- 时间戳：{market_data.get('timestamp')}",
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
            logger.exception("realtime_analyzer: LLM 调用失败")
            return None

    @staticmethod
    def _snapshot_only_report(market_data: dict) -> str:
        lines = ["[快照模式] 未配置 LLM，仅输出行情摘要：", ""]
        for q in market_data.get("quotes", []):
            lines.append(
                f"- {q.get('name', '')}({q.get('code', '')}) "
                f"最新 {q.get('last')} 涨跌幅 {q.get('pct')}% "
                f"换手 {q.get('turnover')}%"
            )
        idx = market_data.get("indices")
        if idx:
            lines.append("")
            lines.append("指数：")
            for it in idx:
                lines.append(
                    f"- {it.get('name', '')} {it.get('last')} "
                    f"{it.get('pct')}% 涨跌家数 {it.get('up_count')}/{it.get('down_count')}"
                )
        return "\n".join(lines)

    def backtest(self, klines: Any = None, **kwargs) -> BacktestResult:
        """分析/研报工具，不参与回测 —— 返回「未实现」空结果（绝不 raise）。"""
        from core.backtest.engine import BacktestResult

        return BacktestResult.empty(engine="none")

    def live_tick(self, tick: Any = None, **kwargs) -> None:
        # 研究模式：仅产出研报，不主动下单
        if not self.is_live():
            logger.info("realtime_analyzer: dry-run tick（未开实盘），跳过下单")
            return
        logger.warning("realtime_analyzer: 实盘模式下也只产出研报，不主动下单")

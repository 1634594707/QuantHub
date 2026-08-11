"""实时 A 股分析器策略 — QuantHub 迁移版。

把 ``trading-master/02-A-stock-realtime-analyzer`` 的实时分析能力下沉为
策略插件：

- 抓数层（``fetchers``）纯标准库（东方财富 push2 盘口 + 腾讯 fqkline 日 K +
  指数宽度），无第三方依赖，离线优雅降级。
- LLM 层复用 ``core.llm.get_llm()``（与全仓统一，自动解析 GPT/DeepSeek 后端）。
- 产出：深度研报（文本）+ 一条 info 级 Signal（``direction="hold"``，
  真实买卖信号由研报文本承载，Signal 仅作"分析已产出"的登记与路由占位）。

实盘：默认关。即便开，本策略只产出研报，不主动下单。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

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
        if codes:
            raw = codes if isinstance(codes, str) else ",".join(codes)
            return parse_codes(raw)
        cfg = self.config.get("default_codes") or ["600519", "000001"]
        return parse_codes(",".join(cfg))

    def produce(
        self,
        codes: Any = None,
        with_kline: bool = True,
        kline_days: int = 60,
        with_indices: bool = True,
        **kwargs,
    ) -> list[Signal]:
        target = self.config.get("default_codes")
        codes = self._resolve_codes(codes or target)
        if not codes:
            logger.warning("realtime_analyzer: 无可用股票代码，跳过")
            return []

        logger.info("realtime_analyzer: 抓取 %d 只实时行情", len(codes))
        market_data: dict[str, Any] = {
            "timestamp": dt.datetime.now(dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "codes": codes,
            "quotes": fetch_quotes(codes),
        }
        if with_indices:
            market_data["indices"] = fetch_index_baseline()
        if with_kline:
            kline = {}
            for c in codes:
                try:
                    kline[c] = fetch_kline(c, days=kline_days)
                except Exception as exc:  # noqa: BLE001 - fetchers expose provider-specific failures
                    kline[c] = {"error": str(exc)}
            market_data["kline"] = kline

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
        }
        if not has_llm:
            self.last_signal_rejection = {
                "code": "model_unavailable",
                "message": "LLM 不可用；已保存行情快照，但未发布带数值把握度的信号。",
                "details": {"source": "realtime_analyzer"},
            }
            return []

        signal_values = parse_report_signal(report)
        if signal_values is None:
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

    def _build_report(self, market_data: dict) -> str | None:
        try:
            from core.llm import get_llm

            llm = get_llm()
        except Exception as exc:  # noqa: BLE001 - optional LLM providers vary by installation
            logger.warning("realtime_analyzer: LLM 不可用（%s），降级为快照报告", exc)
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

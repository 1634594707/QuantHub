"""两阶段 LLM 价格行为分析编排（Al Brooks PA）。

从原 ``PA_Agent/pa_agent/orchestrator/two_stage.py`` 提取核心两阶段流程:

    Stage 1（市场诊断）:
        1. 组装 Stage1 prompt（K 线表 + EMA/ATR + PA 术语与诊断 schema）
        2. 调用 LLM → 解析 JSON → 得到 cycle_position / direction / gate_result
    Stage 2（决策）:
        3. 组装 Stage2 prompt（携带 Stage1 诊断 JSON + 决策 schema）
        4. 调用 LLM → 解析 JSON → 得到 decision / terminal / next_bar_prediction

【与原版差异（迁移简化，已标注）】
    - LLM 客户端: 改用 ``core.llm.get_llm()`` 统一客户端，弃用原 deepseek_client
    - 流式回调 / 取消令牌 / QClaw fallback / 经验库 / 持久化记录: 全部省略
      （原 orchestrator 依赖 CancelToken / PendingWriter / ExperienceReader /
       QClawConnector / stream_chat 等大量辅助模块，本模块仅保留分析主流程）
    - JSON 校验: 原版用 JsonValidator + validation_retry + 语义检查 + 不可变字段
      作弊检测；此处简化为 ``json.loads`` + 关键字段存在性检查，复杂校验省略
    - Prompt 组装: 原版由 PromptAssembler 生成（含 pattern_routing /
      kline_features / decision_stance / 几何特征等）；此处保留 PA 诊断/决策
      schema 的核心字段与中文术语约束，K 线表与指标直接内联

主流程 ``run_two_stage`` 返回 ``TwoStageResult``，供 ``strategy.py`` 解析为 Signal。
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field

import pandas as pd

from core.llm import LLMClient, get_llm

logger = logging.getLogger(__name__)

PA_PIPELINE_VERSION = "pa-two-stage-v1"
PA_PROMPT_VERSION = "pa-inline-schema-2026-07-25"

_CYCLE_VALUES = (
    "spike",
    "micro_channel",
    "tight_channel",
    "normal_channel",
    "broad_channel",
    "trending_tr",
    "trading_range",
    "extreme_tr",
)


# ── 结果数据类 ─────────────────────────────────────────────────────────────────


@dataclass
class TwoStageResult:
    """两阶段分析的最终结果。"""

    stage1_json: dict | None  # 阶段一诊断 JSON（失败时为 None）
    stage2_json: dict | None  # 阶段二决策 JSON（失败/闸门短路时为 None）
    stage1_content: str = ""  # 阶段一原始正文（调试用）
    stage2_content: str = ""  # 阶段二原始正文（调试用）
    error: str | None = None  # 失败原因（成功时为 None）
    usage: dict[str, int] = field(default_factory=dict)


# ── Prompt 片段（保留原版 PA 术语与 schema 核心约束） ─────────────────────────

_LANGUAGE_ZH_RULE = """
## 语言要求（阶段一、阶段二均必须遵守）
- 思考过程与最终输出 JSON 中所有面向用户的字符串一律使用简体中文。
- 仅 JSON 字段名、固定枚举（proceed/wait、bullish/bearish/neutral、做多/做空）允许英文。
- 价格行为术语优先使用简体中文：信号棒/入场棒/确认棒/突破/假突破/外包棒/内包棒/
  流星线/锤子线/十字星/趋势棒/铁丝网/被套/磁力位。
""".strip()

_THINKING_OUTPUT_RULE = """
## 思考与正式输出分离（硬约束）
- 思考区仅用于推演草稿；程序只读取 assistant 消息的 content 正文做 JSON 解析。
- 必须在 content 正文里输出完整、可 json.loads 的裸 JSON 对象（以 { 开头、以 } 结尾）。
- 禁止在 content 里输出 markdown 说明或纯叙述文字；content 只能是裸 JSON。
""".strip()


def _stage1_system_prompt() -> str:
    """阶段一系统提示：PA 市场诊断角色与 schema。"""
    return f"""你是 Al Brooks 价格行为（PA）分析专家，负责阶段一市场诊断。

{_LANGUAGE_ZH_RULE}

{_THINKING_OUTPUT_RULE}

## 阶段一任务：市场诊断
基于给出的最近 N 根已收盘 K 线（含 EMA20 / ATR14），完成市场结构诊断。

必须在 content 正文输出如下 JSON（裸 JSON，无 markdown）：
{{
  "cycle_position": "spike | micro_channel | tight_channel | normal_channel | broad_channel | trending_tr | trading_range | extreme_tr",
  "alternative_cycle_position": "上述枚举之一或null",
  "direction": "bullish | bearish | neutral",
  "trend_stage": "初生 | 发展 | 成熟 | 衰竭",
  "market_phase": "stable | transitioning",
  "transition_risk": "低 | 中 | 高",
  "diagnosis_confidence": 0到100的整数,
  "diagnosis_confidence_reasoning": "简体中文置信依据",
  "detected_patterns": ["以简体中文描述检测到的 PA 形态，如 高1/低1、二次突破、外包棒等"],
  "key_levels": {{
    "support": [数字],
    "resistance": [数字]
  }},
  "momentum": "强 | 中 | 弱",
  "bar_by_bar_summary": ["逐根简述最近 5-8 根 K 线的价格行为"],
  "gate_trace": [
    {{
      "node_id": "1.2",
      "question": "能否识别当前周期类型？",
      "answer": "是 | 否 | 中性",
      "reason": "简体中文依据",
      "bar_range": "如 K20-K1"
    }}
  ],
  "gate_result": "proceed | wait | unknown"
}}

## 闸门规则（gate_result）
- gate_result=proceed：可进入阶段二做下单评估。
- gate_result=wait/unknown：仅在无法识别周期（§1.2 否）或极端混乱时使用。
- §2.5 惯性不足（否/中性）不构成闸门阻断，gate_result 仍为 proceed。
"""


def _stage2_system_prompt() -> str:
    """阶段二系统提示：PA 决策与下单评估。"""
    return f"""你是 Al Brooks 价格行为（PA）分析专家，负责阶段二决策评估。

{_LANGUAGE_ZH_RULE}

{_THINKING_OUTPUT_RULE}

## 阶段二任务：决策评估
你将收到阶段一诊断 JSON。基于该诊断 + K 线，评估是否下单及具体计划。

必须在 content 正文输出如下 JSON（裸 JSON，无 markdown）：
{{
  "decision": {{
    "order_type": "限价单 | 突破单 | 市价单 | 不下单",
    "order_direction": "做多 | 做空",
    "entry_price": 数字或null,
    "stop_loss_price": 数字或null,
    "take_profit_price": 数字或null,
    "reasoning": "简体中文决策依据",
    "diagnosis_confidence": 0到100的整数,
    "trade_confidence": 0到100的整数,
    "estimated_win_rate": 0到100的整数或null,
    "key_factors": ["简体中文关键因素"],
    "watch_points": ["简体中文观察点"],
    "risk_assessment": "简体中文风险评估"
  }},
  "diagnosis_summary": {{
    "cycle_position": "阶段一的周期枚举",
    "alternative_cycle_position": "备选周期枚举或null",
    "direction": "bullish | bearish | neutral",
    "market_phase": "stable | transitioning",
    "transition_risk": "低 | 中 | 高",
    "key_signals": ["简体中文关键信号"]
  }},
  "decision_trace": [
    {{
      "phase": "decision",
      "node_id": "如 4.1",
      "question": "本节点评估问题",
      "answer": "通过 | 边缘 | 不通过",
      "reason": "简体中文依据",
      "bar_range": "如 K8-K1"
    }}
  ],
  "terminal": {{
    "node_id": "10.x",
    "outcome": "wait | reject | trade | proceed",
    "label": "简体中文结局标签"
  }},
  "next_bar_prediction": {{
    "direction": "bullish | bearish | neutral | null",
    "probabilities": {{"bullish": 0到100整数, "bearish": 0到100整数, "neutral": 0到100整数}},
    "unpredictable": true或false,
    "reasoning": "简体中文预测依据"
  }},
  "next_cycle_prediction": {{
    "direction": "bullish | bearish | neutral | null",
    "probabilities": {{
      "spike": 0到100整数,
      "micro_channel": 0到100整数,
      "tight_channel": 0到100整数,
      "normal_channel": 0到100整数,
      "broad_channel": 0到100整数,
      "trending_tr": 0到100整数,
      "trading_range": 0到100整数,
      "extreme_tr": 0到100整数
    }},
    "unpredictable": true或false,
    "reasoning": "简体中文预测依据"
  }}
}}

## 决策规则
- order_type=不下单 时，entry/stop/target/order_direction/estimated_win_rate 必须为 null。
- order_type 为限价单/突破单/市价单 时，entry/stop/target 必须为数字，order_direction 为做多/做空。
- terminal.outcome 应与 decision.order_type 一致（不下单→wait/reject，下单→trade）。
- diagnosis_summary.direction 一般与阶段一 direction 一致；若反转须在 decision.reasoning 说明。
"""


# ── K 线表组装 ─────────────────────────────────────────────────────────────────


def _format_kline_table(df: pd.DataFrame, tail: int = 60) -> str:
    """把 K 线 DataFrame 格式化为供 LLM 阅读的文本表格（最近 tail 根）。

    序号采用「K1=最新已收盘 bar」倒序，与原 PA Agent 约定一致。
    """
    if df is None or df.empty:
        return "（无 K 线数据）"
    recent = df.tail(tail).reset_index(drop=True)
    lines = [
        "# K 线数据（K1=最新已收盘 bar，序号越小越新）",
        "序号 | 时间 | 开 | 高 | 低 | 收 | 量 | EMA20 | ATR14",
    ]
    n = len(recent)
    for i, row in recent.iterrows():
        seq = n - i  # K1 = 最新
        ts = row.get("datetime", row.get("ts", ""))
        ts_str = ts if isinstance(ts, str) else str(ts)
        ema = row.get("ema")
        atr = row.get("atr")
        ema_str = f"{ema:.4f}" if isinstance(ema, (int, float)) and not math.isnan(ema) else "-"
        atr_str = f"{atr:.4f}" if isinstance(atr, (int, float)) and not math.isnan(atr) else "-"
        lines.append(
            f"K{seq} | {ts_str} | {row['open']:.4f} | {row['high']:.4f} | "
            f"{row['low']:.4f} | {row['close']:.4f} | {row.get('volume', 0)} | "
            f"{ema_str} | {atr_str}"
        )
    return "\n".join(lines)


def _build_stage1_messages(
    symbol: str,
    timeframe: str,
    kline_text: str,
) -> list[dict[str, str]]:
    """组装阶段一消息列表（system + user）。"""
    user = f"""# 分析标的
- symbol: {symbol}
- timeframe: {timeframe}

# K 线与指标
{kline_text}

请按阶段一 schema 输出市场诊断 JSON。"""
    return [
        {"role": "system", "content": _stage1_system_prompt()},
        {"role": "user", "content": user},
    ]


def _build_stage2_messages(
    symbol: str,
    timeframe: str,
    kline_text: str,
    stage1_json: dict,
    stage1_content: str,
) -> list[dict[str, str]]:
    """组装阶段二消息列表（system + user，含阶段一诊断）。

    采用「多轮续写」形式：把阶段一的 assistant 回复嵌入对话历史，
    与原 build_stage2_continuation 一致，便于模型沿用阶段一上下文。
    """
    stage1_brief = json.dumps(stage1_json, ensure_ascii=False)
    user = f"""# 分析标的
- symbol: {symbol}
- timeframe: {timeframe}

# K 线与指标
{kline_text}

# 阶段一诊断结果（JSON）
{stage1_brief}

请基于阶段一诊断，按阶段二 schema 输出决策 JSON。若阶段一 gate_result 非 proceed，
应输出 order_type=不下单、terminal.outcome=wait。"""
    return [
        {"role": "system", "content": _stage2_system_prompt()},
        # 阶段一对话历史（续写模式）
        {"role": "user", "content": "（阶段一已完成市场诊断）"},
        {"role": "assistant", "content": stage1_content},
        {"role": "user", "content": user},
    ]


# ── JSON 解析（简化校验） ─────────────────────────────────────────────────────


def _extract_json(content: str) -> dict | None:
    """从 LLM 正文里提取首个 JSON 对象。

    【简化说明】原版用 JsonValidator 做 schema 级校验 + 重试反馈 + 语义检查 +
    不可变字段作弊检测；此处仅做 ``json.loads`` 与基本结构提取，复杂校验省略。
    模型偶尔会把 JSON 包在 ```json 围栏里或附带前后说明，此处做容错剥离。
    """
    if not content:
        return None
    text = content.strip()
    # 剥离 markdown 代码围栏
    if text.startswith("```"):
        # 去掉首行围栏
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    # 直接尝试整体解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 退而求其次：截取首个 {...} 平衡片段
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                snippet = text[start : i + 1]
                try:
                    obj = json.loads(snippet)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    return None
    return None


def _has_required_keys(obj: dict, keys: list[str]) -> bool:
    """检查 dict 是否含全部必填键（简化校验）。"""
    return all(k in obj for k in keys)


def _normalize_stage1(stage1: dict) -> dict:
    """补齐阶段一可选字段，保证视图模型拿到稳定结构。"""
    stage1.setdefault("alternative_cycle_position", None)
    stage1.setdefault("trend_stage", "")
    stage1.setdefault("market_phase", "stable")
    stage1.setdefault("transition_risk", "低")
    stage1.setdefault("diagnosis_confidence", 0)
    stage1.setdefault("diagnosis_confidence_reasoning", "")
    stage1.setdefault("detected_patterns", [])
    stage1.setdefault("key_levels", {"support": [], "resistance": []})
    stage1.setdefault("momentum", "中")
    stage1.setdefault("bar_by_bar_summary", [])
    stage1.setdefault("gate_trace", [])
    return stage1


def _empty_cycle_probabilities() -> dict[str, int]:
    return {key: 0 for key in _CYCLE_VALUES}


def _normalize_stage2(stage2: dict, stage1: dict) -> dict:
    """补齐阶段二模块，避免模型漏字段导致前端出现空白区块。"""
    decision = stage2.setdefault("decision", {})
    decision.setdefault("order_type", "不下单")
    decision.setdefault("order_direction", None)
    decision.setdefault("entry_price", None)
    decision.setdefault("stop_loss_price", None)
    decision.setdefault("take_profit_price", None)
    decision.setdefault("take_profit_price_2", None)
    decision.setdefault("reasoning", "模型未提供决策依据")
    decision.setdefault("diagnosis_confidence", stage1.get("diagnosis_confidence", 0))
    decision.setdefault(
        "diagnosis_confidence_reasoning", stage1.get("diagnosis_confidence_reasoning", "")
    )
    decision.setdefault("trade_confidence", 0)
    decision.setdefault("trade_confidence_reasoning", "")
    decision.setdefault("estimated_win_rate", None)
    decision.setdefault("key_factors", [])
    decision.setdefault("watch_points", [])
    decision.setdefault("risk_assessment", "")

    stage2.setdefault(
        "diagnosis_summary",
        {
            "cycle_position": stage1.get("cycle_position"),
            "alternative_cycle_position": stage1.get("alternative_cycle_position"),
            "direction": stage1.get("direction"),
            "market_phase": stage1.get("market_phase"),
            "transition_risk": stage1.get("transition_risk"),
            "key_signals": stage1.get("detected_patterns", []),
        },
    )
    stage2.setdefault("decision_trace", [])
    stage2.setdefault("terminal", {"node_id": "unknown", "outcome": "wait", "label": "等待"})
    stage2.setdefault(
        "next_bar_prediction",
        {
            "direction": None,
            "probabilities": {"bullish": 0, "bearish": 0, "neutral": 0},
            "unpredictable": True,
            "reasoning": "模型未提供下一根预测",
        },
    )
    stage2.setdefault(
        "next_cycle_prediction",
        {
            "direction": None,
            "probabilities": _empty_cycle_probabilities(),
            "unpredictable": True,
            "reasoning": "模型未提供下一周期预测",
        },
    )
    return stage2


# ── 主流程 ─────────────────────────────────────────────────────────────────────


def _call_llm(
    client: LLMClient,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int | None = 4096,
) -> tuple[str, dict[str, int]]:
    """调用统一 LLM 客户端，返回 (content, usage)。

    【简化说明】原版 stream_chat 支持思考流/正文流分流、取消令牌、QClaw fallback；
    此处用 ``core.llm.LLMClient.chat`` 一次性调用，由其内置 tenacity 重试覆盖网络错误。
    """
    chat_kwargs = {}
    if getattr(client, "_provider", "") == "deepseek":
        # PA 输出是严格 JSON。关闭 DeepSeek v4 的独立推理区，避免两阶段调用
        # 长时间消耗 reasoning token 后 content 为空。
        chat_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = client.chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **chat_kwargs,
    )
    usage = resp.usage or {}
    return resp.content or "", dict(usage)


def run_two_stage(
    symbol: str,
    timeframe: str,
    klines: pd.DataFrame,
    *,
    atr_period: int = 14,
    ema_period: int = 20,
    tail_bars: int = 60,
    llm: LLMClient | None = None,
) -> TwoStageResult:
    """执行两阶段 PA 分析，返回 TwoStageResult。

    Args:
        symbol: 标的代码
        timeframe: 周期（如 "1h" / "daily"）
        klines: K 线 DataFrame（需含 high/low/close/volume/datetime 列，升序）
        atr_period / ema_period: 指标周期
        tail_bars: 送入 LLM 的最近 K 线根数
        llm: 可选 LLM 客户端；None 时用 ``get_llm()`` 默认实例
    """
    # 延迟 import 避免循环依赖：indicators 在同包内
    from strategies.ai_analysis.pa_agent.indicators import compute_indicators

    result = TwoStageResult(stage1_json=None, stage2_json=None)
    if klines is None or klines.empty:
        result.error = "K 线数据为空"
        return result

    # 1. 计算指标
    df = compute_indicators(klines, atr_period=atr_period, ema_period=ema_period)
    if df.empty:
        result.error = "指标计算失败"
        return result
    kline_text = _format_kline_table(df, tail=tail_bars)

    # 2. 取得 LLM 客户端
    try:
        client = llm or get_llm()
    except Exception as exc:
        result.error = f"LLM 客户端初始化失败: {exc}"
        return result

    # 3. Stage 1: 市场诊断
    messages_s1 = _build_stage1_messages(symbol, timeframe, kline_text)
    try:
        content_s1, usage_s1 = _call_llm(client, messages_s1)
    except Exception as exc:
        result.error = f"阶段一 LLM 调用失败: {exc}"
        return result
    result.stage1_content = content_s1
    result.usage = {f"stage1_{k}": v for k, v in usage_s1.items()}

    stage1_json = _extract_json(content_s1)
    if stage1_json is None or not _has_required_keys(
        stage1_json, ["cycle_position", "direction", "gate_result"]
    ):
        # 【简化说明】原版会触发 validation_retry 带 feedback 重试；此处直接判失败
        logger.warning(
            "PA 阶段一 JSON 解析失败 symbol=%s; content(前300字): %.300s",
            symbol,
            content_s1,
        )
        result.error = "阶段一 JSON 解析或必填字段校验失败"
        return result
    result.stage1_json = _normalize_stage1(stage1_json)

    # 4. 闸门短路：gate_result 非 proceed 时跳过阶段二模型调用
    gate = str(stage1_json.get("gate_result", "proceed")).lower()
    if gate in ("wait", "unknown"):
        # 与原版 build_stage2_gate_wait_response 行为一致：短路生成不下单决策
        result.stage2_json = _normalize_stage2(
            {
                "decision": {
                    "order_type": "不下单",
                    "order_direction": None,
                    "entry_price": None,
                    "stop_loss_price": None,
                    "take_profit_price": None,
                    "reasoning": f"阶段一 gate_result={gate}，闸门未通过，不下单",
                    "diagnosis_confidence": stage1_json.get("diagnosis_confidence", 0),
                    "trade_confidence": 0,
                    "estimated_win_rate": None,
                    "key_factors": [],
                    "watch_points": ["等待周期清晰或结构突破后再评估"],
                    "risk_assessment": "周期无法识别或极端混乱，不入场",
                },
                "diagnosis_summary": {
                    "cycle_position": stage1_json.get("cycle_position"),
                    "alternative_cycle_position": stage1_json.get("alternative_cycle_position"),
                    "direction": stage1_json.get("direction"),
                    "market_phase": stage1_json.get("market_phase"),
                    "transition_risk": stage1_json.get("transition_risk"),
                    "key_signals": stage1_json.get("detected_patterns", []),
                },
                "decision_trace": [],
                "terminal": {"node_id": "gate", "outcome": "wait", "label": "闸门短路"},
                "next_bar_prediction": {
                    "direction": None,
                    "probabilities": None,
                    "unpredictable": True,
                    "reasoning": "闸门未通过，不预测下一根",
                },
            },
            stage1_json,
        )
        return result

    # 5. Stage 2: 决策评估
    messages_s2 = _build_stage2_messages(symbol, timeframe, kline_text, stage1_json, content_s1)
    try:
        content_s2, usage_s2 = _call_llm(client, messages_s2)
    except Exception as exc:
        result.error = f"阶段二 LLM 调用失败: {exc}"
        return result
    result.stage2_content = content_s2
    result.usage.update({f"stage2_{k}": v for k, v in usage_s2.items()})

    stage2_json = _extract_json(content_s2)
    if stage2_json is None or not _has_required_keys(
        stage2_json, ["decision", "terminal", "next_bar_prediction"]
    ):
        logger.warning(
            "PA 阶段二 JSON 解析失败 symbol=%s; content(前300字): %.300s",
            symbol,
            content_s2,
        )
        result.error = "阶段二 JSON 解析或必填字段校验失败"
        return result
    result.stage2_json = _normalize_stage2(stage2_json, stage1_json)
    return result

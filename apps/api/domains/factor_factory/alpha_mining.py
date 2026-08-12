from __future__ import annotations

import ast as python_ast
import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from core.factor_dsl import (
    FIELD_UNITS,
    FactorDefinition,
    FactorDslError,
    FactorDslLimits,
    validate_factor_definition,
)
from core.llm import LLMClient, get_llm

ALPHA_MINING_VERSION = "brain-alpha-v1.4"
AI_PROMPT_VERSION = "brain-alpha-refinement-json-v3"
AI_RAW_OUTPUT_LIMIT = 50_000

EXPRESSION_FIELDS = {"open", "high", "low", "close", "volume"}
EXPRESSION_BINARY = {"add", "sub", "mul", "div", "gt", "lt"}
EXPRESSION_UNARY = {"neg", "abs"}
EXPRESSION_PERIOD = {"lag", "diff", "pct_change"}
EXPRESSION_WINDOW = {
    "rolling_mean",
    "rolling_std",
    "rolling_min",
    "rolling_max",
    "rolling_sum",
    "rolling_zscore",
    "rank",
}

_EXPRESSION_FIELD_LABELS = {
    "open": "开盘价",
    "high": "最高价",
    "low": "最低价",
    "close": "收盘价",
    "volume": "成交量",
}

_EXPRESSION_OPERATOR_DOCS = {
    "add": ("add(left, right)", "相加；两侧单位必须一致", "add(close, neg(open))"),
    "sub": ("sub(left, right)", "相减；两侧单位必须一致", "sub(close, open)"),
    "mul": (
        "mul(left, right)",
        "相乘，用于组合两个信号",
        "mul(pct_change(close, 3), rank(volume, 20))",
    ),
    "div": ("div(left, right)", "相除；同单位结果为无量纲", "div(sub(close, open), open)"),
    "gt": ("gt(left, right)", "大于比较，生成布尔条件", "gt(close, rolling_mean(close, 20))"),
    "lt": ("lt(left, right)", "小于比较，生成布尔条件", "lt(close, rolling_mean(close, 20))"),
    "neg": ("neg(value)", "信号取反，常用于反转因子", "neg(pct_change(close, 3))"),
    "abs": ("abs(value)", "取绝对值", "abs(pct_change(close, 1))"),
    "lag": ("lag(value, periods)", "向后滞后 periods 根 K 线", "lag(close, 1)"),
    "diff": ("diff(value, periods)", "与 periods 根 K 线前做差", "diff(close, 5)"),
    "pct_change": (
        "pct_change(value, periods)",
        "计算 periods 根 K 线收益率",
        "pct_change(close, 3)",
    ),
    "rolling_mean": ("rolling_mean(value, window)", "滚动均值", "rolling_mean(close, 20)"),
    "rolling_std": (
        "rolling_std(value, window)",
        "滚动标准差",
        "rolling_std(pct_change(close, 1), 20)",
    ),
    "rolling_min": ("rolling_min(value, window)", "滚动最小值", "rolling_min(low, 20)"),
    "rolling_max": ("rolling_max(value, window)", "滚动最大值", "rolling_max(high, 20)"),
    "rolling_sum": ("rolling_sum(value, window)", "滚动求和", "rolling_sum(volume, 20)"),
    "rolling_zscore": (
        "rolling_zscore(value, window)",
        "滚动标准分，常用于归一化",
        "rolling_zscore(pct_change(close, 3), 20)",
    ),
    "rolling_winsorize": (
        "rolling_winsorize(value, window[, lower, upper])",
        "滚动缩尾；默认分位数 0.01 / 0.99",
        "rolling_winsorize(pct_change(close, 1), 20, 0.01, 0.99)",
    ),
    "rank": ("rank(value, window)", "当前值在滚动窗口内的百分位排名", "rank(volume, 20)"),
    "where": (
        "where(condition, then, else)",
        "按布尔条件选择两个同单位结果",
        "where(gt(close, open), volume, neg(volume))",
    ),
}


def alpha_expression_catalog() -> dict[str, Any]:
    """Return documentation generated from the actual manual-expression whitelist."""
    limits = FactorDslLimits()
    allowed = (
        EXPRESSION_BINARY
        | EXPRESSION_UNARY
        | EXPRESSION_PERIOD
        | EXPRESSION_WINDOW
        | {"rolling_winsorize", "where"}
    )
    fields = [
        {
            "name": name,
            "label": _EXPRESSION_FIELD_LABELS[name],
            "unit": FIELD_UNITS[name],
        }
        for name in ("open", "high", "low", "close", "volume")
        if name in EXPRESSION_FIELDS
    ]
    operators = [
        {
            "name": name,
            "signature": documentation[0],
            "description": documentation[1],
            "example": documentation[2],
        }
        for name, documentation in _EXPRESSION_OPERATOR_DOCS.items()
        if name in allowed
    ]
    return {
        "version": ALPHA_MINING_VERSION,
        "fields": fields,
        "operators": operators,
        "parameters": [
            {"name": "value", "description": "字段、数值常量或另一个算子的结果"},
            {"name": "left / right", "description": "二元算子的左右输入"},
            {"name": "periods", "description": f"回看或滞后的 K 线数量；整数 1–{limits.max_lag}"},
            {"name": "window", "description": f"滚动统计窗口；整数 1–{limits.max_window}"},
            {"name": "lower / upper", "description": "缩尾分位数；0 ≤ lower < upper ≤ 1"},
            {
                "name": "condition / then / else",
                "description": "布尔条件、条件成立值、条件不成立值",
            },
        ],
        "limits": {
            "periods_min": 1,
            "periods_max": limits.max_lag,
            "window_min": 1,
            "window_max": limits.max_window,
            "max_depth": limits.max_depth,
            "max_operators": limits.max_operators,
            "winsor_lower_min": 0,
            "winsor_upper_max": 1,
        },
    }


@dataclass(frozen=True)
class AlphaProposal:
    candidate_id: str
    label: str
    family: str
    source: str
    ast: dict[str, Any]
    hypothesis: str
    invalidation: str
    falsification_tests: tuple[str, ...] = (
        "rolling_validation_stability",
        "double_cost_stress",
    )
    model: dict[str, Any] = field(default_factory=dict)
    prompt: dict[str, Any] = field(default_factory=dict)
    ai_trace: dict[str, Any] = field(default_factory=dict)


def _field(name: str) -> dict[str, Any]:
    return {"op": "field", "name": name}


def _const(value: float) -> dict[str, Any]:
    return {"op": "const", "value": value}


def _returns(periods: int) -> dict[str, Any]:
    return {"op": "pct_change", "value": _field("close"), "periods": periods}


def _zscore(value: dict[str, Any], window: int) -> dict[str, Any]:
    return {"op": "rolling_zscore", "value": value, "window": window}


def _brain_primitive(kind: int, lookback: int) -> tuple[str, dict[str, Any], str, str]:
    close = _field("close")
    high = _field("high")
    low = _field("low")
    volume = _field("volume")
    long_window = min(240, max(lookback * 3, 24))
    if kind == 0:
        return (
            "return_trend",
            _zscore(_returns(lookback), long_window),
            "Risk-normalized price displacement may persist over the selected horizon.",
            "The direction reverses or the return disappears after doubled costs.",
        )
    if kind == 1:
        return (
            "return_reversal",
            {"op": "neg", "value": _zscore(_returns(max(1, lookback // 4)), lookback)},
            "Short-horizon return extremes may mean-revert after liquidity normalizes.",
            "Extreme moves continue in the same direction or turnover consumes the edge.",
        )
    if kind == 2:
        return (
            "price_volume_pressure",
            {
                "op": "mul",
                "left": _zscore(_returns(max(1, lookback // 3)), lookback),
                "right": _zscore(
                    {"op": "pct_change", "value": volume, "periods": 1},
                    lookback,
                ),
            },
            "Price moves supported by abnormal volume may contain more information than price alone.",
            "Volume confirmation increases noise, turnover, or drawdown without improving returns.",
        )
    if kind == 3:
        return (
            "range_position",
            {
                "op": "sub",
                "left": {
                    "op": "div",
                    "left": {"op": "sub", "left": close, "right": low},
                    "right": {"op": "sub", "left": high, "right": low},
                },
                "right": _const(0.5),
            },
            "Repeated closes near one side of the candle range may reveal directional pressure.",
            "Close location fails to persist or only reflects intrabar noise.",
        )
    if kind == 4:
        return (
            "range_breakout",
            {
                "op": "div",
                "left": {
                    "op": "sub",
                    "left": close,
                    "right": {"op": "rolling_max", "value": high, "window": lookback},
                },
                "right": {"op": "rolling_std", "value": close, "window": lookback},
            },
            "A volatility-scaled break beyond the lagged range may mark a supply-demand imbalance.",
            "Breakouts revert before costs are recovered or drawdown exceeds the preregistered limit.",
        )
    if kind == 5:
        one_bar = _returns(1)
        path = {
            "op": "rolling_sum",
            "value": {"op": "abs", "value": one_bar},
            "window": lookback,
        }
        return (
            "path_efficiency",
            {
                "op": "div",
                "left": {"op": "abs", "value": _returns(lookback)},
                "right": path,
            },
            "A larger net move per unit of traveled price path may identify cleaner trends.",
            "Path efficiency falls or the signal is not robust to nearby lookbacks.",
        )
    volatility = {"op": "rolling_std", "value": _returns(1), "window": lookback}
    return (
        "volatility_state",
        {"op": "neg", "value": _zscore(volatility, long_window)},
        "Volatility compression may precede a more stable directional expansion.",
        "Low-volatility states remain directionless or transaction costs dominate the expansion.",
    )


def _transform_alpha(value: dict[str, Any], *, transform: int, lookback: int) -> dict[str, Any]:
    if transform == 0:
        return _zscore(value, min(240, max(lookback * 2, 24)))
    if transform == 1:
        return {
            "op": "rolling_mean",
            "value": value,
            "window": max(2, min(12, lookback // 4)),
        }
    if transform == 2:
        return {"op": "rank", "value": value, "window": min(240, max(lookback * 2, 24))}
    volume_rank = {
        "op": "rank",
        "value": _field("volume"),
        "window": min(120, max(lookback, 12)),
    }
    return {"op": "mul", "left": value, "right": volume_rank}


def generate_grammar_proposals(
    *, seed: int, count: int, interval: str, market: str = "crypto"
) -> list[AlphaProposal]:
    rng = random.Random(seed)
    lookbacks = [3, 6, 12, 18, 24, 36, 48, 72]
    if interval == "4h":
        lookbacks = [3, 6, 9, 12, 18, 24, 36, 48]
    proposals: list[AlphaProposal] = []
    formula_hashes: set[str] = set()
    attempts = 0
    while len(proposals) < count and attempts < max(200, count * 30):
        attempts += 1
        lookback = rng.choice(lookbacks)
        kind = rng.randrange(7)
        transform = rng.randrange(4)
        family, primitive, hypothesis, invalidation = _brain_primitive(kind, lookback)
        ast = _transform_alpha(primitive, transform=transform, lookback=lookback)
        if rng.random() < 0.35:
            ast = {"op": "neg", "value": ast}
            family = f"inverse_{family}"
        candidate_id = f"brain_{family}_{lookback}_{transform}_{attempts}"
        try:
            definition = FactorDefinition(
                key=candidate_id[:80],
                label=candidate_id,
                market=market,
                ast=ast,
                family=f"brain_{family}",
            )
            validate_factor_definition(definition)
        except FactorDslError:
            continue
        if definition.formula_hash in formula_hashes:
            continue
        formula_hashes.add(definition.formula_hash)
        source = "symbolic_regression" if len(proposals) % 2 == 0 else "random_dsl"
        proposals.append(
            AlphaProposal(
                candidate_id=candidate_id,
                label=f"{family.replace('_', ' ')} {lookback}",
                family=f"brain_{family}",
                source=source,
                ast=ast,
                hypothesis=hypothesis,
                invalidation=invalidation,
            )
        )
    if len(proposals) < count:
        raise RuntimeError(f"alpha grammar produced {len(proposals)} of {count} candidates")
    return proposals


def _extract_json(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _extract_complete_candidate_rows(text: str) -> list[dict[str, Any]]:
    """Recover only fully closed objects from a truncated top-level candidates array."""

    match = re.search(r'"candidates"\s*:\s*\[', text)
    if match is None:
        return []
    rows: list[dict[str, Any]] = []
    array_depth = 1
    object_depth = 0
    object_start: int | None = None
    in_string = False
    escaped = False
    for index in range(match.end(), len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "[":
            array_depth += 1
        elif char == "]":
            array_depth -= 1
            if array_depth == 0:
                break
        elif char == "{":
            if array_depth == 1 and object_depth == 0:
                object_start = index
            object_depth += 1
        elif char == "}" and object_depth > 0:
            object_depth -= 1
            if array_depth == 1 and object_depth == 0 and object_start is not None:
                try:
                    row = json.loads(text[object_start : index + 1])
                except json.JSONDecodeError:
                    object_start = None
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                object_start = None
    return rows


def _safe_candidate_id(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or fallback).strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"alpha_{normalized or fallback}"
    return normalized[:72]


def _normalize_ai_formula_ast(node: Any) -> dict[str, Any]:
    """Convert common JSON ``args`` nodes into the canonical safe DSL shape."""

    if not isinstance(node, dict):
        raise FactorDslError("AI formula_ast 节点必须是对象")
    op = node.get("op")
    if not isinstance(op, str) or not op.strip():
        raise FactorDslError("AI formula_ast 节点缺少 op")
    op = op.strip()
    args = node.get("args")
    if args is not None and not isinstance(args, list):
        raise FactorDslError(f"{op}.args 必须是数组")

    def argument(key: str, index: int) -> Any:
        value = node.get(key)
        if value is None and isinstance(args, list) and index < len(args):
            value = args[index]
        return value

    if op == "field":
        name = argument("name", 0)
        if not isinstance(name, str):
            raise FactorDslError("field.name 必须是字段名")
        return {"op": op, "name": name}
    if op == "const":
        return {"op": op, "value": argument("value", 0)}
    if op in EXPRESSION_BINARY:
        return {
            "op": op,
            "left": _normalize_ai_formula_ast(argument("left", 0)),
            "right": _normalize_ai_formula_ast(argument("right", 1)),
        }
    if op in EXPRESSION_UNARY:
        return {"op": op, "value": _normalize_ai_formula_ast(argument("value", 0))}
    if op in EXPRESSION_PERIOD:
        periods = argument("periods", 1)
        if periods is None:
            periods = node.get("period")
        return {
            "op": op,
            "value": _normalize_ai_formula_ast(argument("value", 0)),
            "periods": periods,
        }
    if op in EXPRESSION_WINDOW:
        return {
            "op": op,
            "value": _normalize_ai_formula_ast(argument("value", 0)),
            "window": argument("window", 1),
        }
    if op == "rolling_winsorize":
        normalized = {
            "op": op,
            "value": _normalize_ai_formula_ast(argument("value", 0)),
            "window": argument("window", 1),
        }
        lower = argument("lower", 2)
        upper = argument("upper", 3)
        if lower is not None:
            normalized["lower"] = lower
        if upper is not None:
            normalized["upper"] = upper
        return normalized
    if op == "where":
        return {
            "op": op,
            "condition": _normalize_ai_formula_ast(argument("condition", 0)),
            "then": _normalize_ai_formula_ast(argument("then", 1)),
            "else": _normalize_ai_formula_ast(argument("else", 2)),
        }
    raise FactorDslError(f"不允许的 AI 因子算子: {op}")


def parse_alpha_expression(expression: str) -> dict[str, Any]:
    """Parse function-call alpha syntax without evaluating Python code."""

    try:
        root = python_ast.parse(expression.strip(), mode="eval").body
    except (SyntaxError, ValueError) as exc:
        raise FactorDslError(f"Alpha 表达式语法错误: {exc}") from exc

    def integer(node: python_ast.AST, name: str) -> int:
        if not isinstance(node, python_ast.Constant) or isinstance(node.value, bool):
            raise FactorDslError(f"{name} 必须是正整数")
        value = node.value
        if not isinstance(value, int) or value < 1:
            raise FactorDslError(f"{name} 必须是正整数")
        return value

    def number(node: python_ast.AST, name: str) -> float:
        if not isinstance(node, python_ast.Constant) or isinstance(node.value, bool):
            raise FactorDslError(f"{name} 必须是数值")
        value = node.value
        if not isinstance(value, int | float):
            raise FactorDslError(f"{name} 必须是数值")
        return float(value)

    def convert(node: python_ast.AST) -> dict[str, Any]:
        if isinstance(node, python_ast.Name) and node.id in EXPRESSION_FIELDS:
            return {"op": "field", "name": node.id}
        if isinstance(node, python_ast.Constant) and isinstance(node.value, int | float):
            if isinstance(node.value, bool):
                raise FactorDslError("Alpha 表达式不允许布尔常量")
            return {"op": "const", "value": float(node.value)}
        if not isinstance(node, python_ast.Call) or not isinstance(node.func, python_ast.Name):
            raise FactorDslError("Alpha 只允许字段、数值和白名单函数调用")
        if node.keywords:
            raise FactorDslError("Alpha 函数只允许位置参数")
        op = node.func.id
        args = node.args
        if op in EXPRESSION_BINARY and len(args) == 2:
            return {"op": op, "left": convert(args[0]), "right": convert(args[1])}
        if op in EXPRESSION_UNARY and len(args) == 1:
            return {"op": op, "value": convert(args[0])}
        if op in EXPRESSION_PERIOD and len(args) == 2:
            return {"op": op, "value": convert(args[0]), "periods": integer(args[1], "periods")}
        if op in EXPRESSION_WINDOW and len(args) == 2:
            return {"op": op, "value": convert(args[0]), "window": integer(args[1], "window")}
        if op == "rolling_winsorize" and len(args) in {2, 4}:
            result: dict[str, Any] = {
                "op": op,
                "value": convert(args[0]),
                "window": integer(args[1], "window"),
            }
            if len(args) == 4:
                result["lower"] = number(args[2], "lower")
                result["upper"] = number(args[3], "upper")
            return result
        if op == "where" and len(args) == 3:
            return {
                "op": op,
                "condition": convert(args[0]),
                "then": convert(args[1]),
                "else": convert(args[2]),
            }
        raise FactorDslError(f"不支持的 Alpha 函数或参数数量: {op}")

    result = convert(root)
    validate_factor_definition(
        FactorDefinition(
            key="manual_alpha_validation",
            label="manual alpha validation",
            market="crypto",
            ast=result,
            family="manual_alpha",
        )
    )
    return result


def _ai_messages(
    *,
    brief: str,
    interval: str,
    count: int,
    market: str,
    seed_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    catalog = {
        "fields": ["open", "high", "low", "close", "volume"],
        "operators": [
            "field",
            "const",
            "add",
            "sub",
            "mul",
            "div",
            "neg",
            "abs",
            "lag",
            "diff",
            "pct_change",
            "rolling_mean",
            "rolling_std",
            "rolling_min",
            "rolling_max",
            "rolling_sum",
            "rolling_zscore",
            "rolling_winsorize",
            "rank",
            "gt",
            "lt",
            "where",
        ],
    }
    seeds = seed_candidates or []
    system = (
        "You refine screened WorldQuant-BRAIN-style alpha hypotheses as JSON AST data only. "
        "Never emit Python, code strings, future data access, negative lags, or unsupported fields. "
        "Each expression must be causal, economically interpretable, and different from the others. "
        "When screened seeds are supplied, every proposal must name one seed_candidate_id and make "
        "a limited structural or parameter refinement of that seed rather than inventing an unrelated idea."
    )
    payload = {
        "task": "refine_screened_alpha_expressions" if seeds else "propose_alpha_expressions",
        "count": count,
        "market": market,
        "interval": interval,
        "research_brief": brief,
        "screened_seed_candidates": seeds,
        "catalog": catalog,
        "ast_contract": {
            "field": {"op": "field", "name": "close"},
            "const": {"op": "const", "value": 1.0},
            "binary": {"op": "mul", "left": "<node>", "right": "<node>"},
            "unary": {"op": "neg", "value": "<node>"},
            "period": {"op": "pct_change", "value": "<node>", "periods": 3},
            "window": {"op": "rolling_zscore", "value": "<node>", "window": 20},
            "winsorize": {
                "op": "rolling_winsorize",
                "value": "<node>",
                "window": 20,
                "lower": 0.01,
                "upper": 0.99,
            },
            "where": {
                "op": "where",
                "condition": "<boolean node>",
                "then": "<node>",
                "else": "<node>",
            },
        },
        "ast_rules": [
            "Use exactly the named object fields shown in ast_contract.",
            "Do not use args, children, input, operands, or expression strings.",
            "Every nested <node> must be another JSON object with an op field.",
        ],
        "output_schema": {
            "candidates": [
                {
                    "seed_candidate_id": "required when screened seeds are supplied",
                    "candidate_id": "short_ascii_id",
                    "label": "short label",
                    "family": "hypothesis_family",
                    "hypothesis": "economic hypothesis",
                    "invalidation": "falsifiable invalidation condition",
                    "falsification_tests": ["test name"],
                    "formula_ast": {"op": "..."},
                }
            ]
        },
        "refinement_rules": [
            "Preserve the seed's economic hypothesis unless the output explicitly narrows it.",
            "Prefer nearby lookbacks, normalization, winsorization, sign, or one compositional change.",
            "Do not use confirmation or holdout evidence; only the supplied discovery metrics exist.",
        ],
        "confirmation_labels_exposed": False,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def generate_ai_proposals(
    *,
    brief: str,
    interval: str,
    count: int,
    market: str = "crypto",
    maximum_tokens: int = 4_000,
    provider: str | None = None,
    client: LLMClient | None = None,
    seed_candidates: list[dict[str, Any]] | None = None,
) -> tuple[list[AlphaProposal], dict[str, Any]]:
    if count <= 0:
        return [], {
            "status": "disabled",
            "candidate_count": 0,
            "requested_provider": provider,
        }
    messages = _ai_messages(
        brief=brief,
        interval=interval,
        count=count,
        market=market,
        seed_candidates=seed_candidates,
    )
    input_text = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    input_fingerprint = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    llm: LLMClient | None = None
    prompt_tokens: int | None = None
    try:
        llm = client or get_llm(provider)
        prompt_tokens = llm.estimate_tokens(input_text)
        completion_budget = min(10_000, maximum_tokens - prompt_tokens)
        if completion_budget <= 0:
            return [], {
                "status": "token_budget_insufficient",
                "candidate_count": 0,
                "input_fingerprint": input_fingerprint,
                "estimated_prompt_tokens": prompt_tokens,
                "maximum_tokens": maximum_tokens,
                "requested_provider": provider,
            }
        response = llm.chat(
            messages,
            temperature=0.2,
            max_tokens=completion_budget,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001 - deterministic grammar remains available
        return [], {
            "status": "unavailable",
            "candidate_count": 0,
            "requested_candidates": count,
            "input_fingerprint": input_fingerprint,
            "estimated_prompt_tokens": prompt_tokens,
            "maximum_tokens": maximum_tokens,
            "error": f"{type(exc).__name__}: {exc}",
            "requested_provider": provider,
            "provider": getattr(llm, "_provider", None),
            "model": getattr(llm, "_model", None),
            "effective_timeout_seconds": getattr(llm, "_timeout", None),
            "effective_max_retries": getattr(llm, "_max_retries", None),
        }
    token_usage = response.usage or {}
    if int(token_usage.get("total_tokens", 0)) > maximum_tokens:
        return [], {
            "status": "token_budget_exceeded",
            "candidate_count": 0,
            "input_fingerprint": input_fingerprint,
            "token_usage": token_usage,
            "maximum_tokens": maximum_tokens,
            "requested_provider": provider,
        }
    payload = _extract_json(response.content)
    recovered_rows = [] if payload else _extract_complete_candidate_rows(response.content)
    recovered_partial = bool(recovered_rows)
    rows = payload.get("candidates", []) if payload else recovered_rows
    proposals: list[AlphaProposal] = []
    rejected: list[dict[str, str]] = []
    hashes: set[str] = set()
    seed_ids = {
        str(item.get("candidate_id"))
        for item in (seed_candidates or [])
        if item.get("candidate_id")
    }
    for index, row in enumerate(rows[:count]):
        if not isinstance(row, dict):
            rejected.append({"index": str(index), "reason": "candidate_not_object"})
            continue
        try:
            seed_candidate_id = str(row.get("seed_candidate_id") or "")
            if seed_ids and seed_candidate_id not in seed_ids:
                raise FactorDslError("AI refinement must reference a screened seed_candidate_id")
            candidate_id = _safe_candidate_id(row.get("candidate_id"), f"ai_alpha_{index + 1}")
            ast = _normalize_ai_formula_ast(row["formula_ast"])
            definition = FactorDefinition(
                key=candidate_id[:80],
                label=str(row.get("label") or candidate_id),
                market=market,
                ast=ast,
                family=str(row.get("family") or "brain_ai"),
            )
            validate_factor_definition(definition)
            if definition.formula_hash in hashes:
                raise FactorDslError("duplicate formula in AI batch")
            hashes.add(definition.formula_hash)
            falsification = row.get("falsification_tests") or [
                "rolling_validation_stability",
                "double_cost_stress",
            ]
            candidate_raw = json.dumps(row, ensure_ascii=False, sort_keys=True)
            proposals.append(
                AlphaProposal(
                    candidate_id=candidate_id,
                    label=str(row.get("label") or candidate_id),
                    family=str(row.get("family") or "brain_ai"),
                    source="ai",
                    ast=ast,
                    hypothesis=str(row.get("hypothesis") or brief),
                    invalidation=str(
                        row.get("invalidation")
                        or "The alpha fails rolling validation or doubled-cost stress."
                    ),
                    falsification_tests=tuple(str(item) for item in falsification[:10]),
                    model={
                        "provider": getattr(llm, "_provider", "unknown"),
                        "model": response.model,
                        "temperature": 0.2,
                    },
                    prompt={
                        "version": AI_PROMPT_VERSION,
                        "input_fingerprint": input_fingerprint,
                        "seed_candidate_id": seed_candidate_id or None,
                    },
                    ai_trace={
                        "token_usage": token_usage,
                        "output_raw": candidate_raw,
                        "generation_stage": "ai_refinement" if seed_ids else "ai_proposal",
                        "seed_candidate_id": seed_candidate_id or None,
                        "confirmation_labels_exposed": False,
                    },
                )
            )
        except (FactorDslError, KeyError, TypeError, ValueError) as exc:
            rejected.append({"index": str(index), "reason": str(exc)})
    response_incomplete = recovered_partial or response.finish_reason == "length"
    status = (
        "generated_partial"
        if proposals and response_incomplete
        else "generated"
        if proposals
        else "invalid_output"
    )
    return proposals, {
        "status": status,
        "candidate_count": len(proposals),
        "requested_candidates": count,
        "requested_provider": provider,
        "provider": getattr(llm, "_provider", "unknown"),
        "model": response.model,
        "finish_reason": response.finish_reason,
        "effective_timeout_seconds": getattr(llm, "_timeout", None),
        "effective_max_retries": getattr(llm, "_max_retries", None),
        "token_usage": token_usage,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": hashlib.sha256(response.content.encode("utf-8")).hexdigest(),
        "output_raw": response.content[:AI_RAW_OUTPUT_LIMIT],
        "output_truncated": len(response.content) > AI_RAW_OUTPUT_LIMIT or response_incomplete,
        "recovered_complete_candidates": len(rows) if recovered_partial else 0,
        "rejected": rejected,
        "seed_candidate_ids": sorted(seed_ids),
        "generation_stage": "ai_refinement" if seed_ids else "ai_proposal",
        "confirmation_labels_exposed": False,
    }


def generate_alpha_batch(
    *,
    run_seed: str,
    budget: int,
    interval: str,
    brief: str,
    market: str = "crypto",
    use_ai: bool,
    ai_candidate_count: int,
    maximum_ai_tokens: int = 4_000,
    provider: str | None = None,
    client: LLMClient | None = None,
) -> tuple[list[AlphaProposal], dict[str, Any]]:
    seed = int(hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:16], 16)
    ai_requested = min(budget, ai_candidate_count) if use_ai else 0
    ai_proposals, ai_audit = generate_ai_proposals(
        brief=brief,
        interval=interval,
        count=ai_requested,
        market=market,
        maximum_tokens=maximum_ai_tokens,
        provider=provider,
        client=client,
    )
    grammar_count = budget - len(ai_proposals)
    grammar = generate_grammar_proposals(
        seed=seed,
        count=grammar_count,
        interval=interval,
        market=market,
    )
    proposals = [*ai_proposals, *grammar]
    formula_hashes: set[str] = set()
    unique: list[AlphaProposal] = []
    for proposal in proposals:
        definition = FactorDefinition(
            key=proposal.candidate_id[:80],
            label=proposal.label,
            market=market,
            ast=proposal.ast,
            family=proposal.family,
        )
        if definition.formula_hash in formula_hashes:
            continue
        formula_hashes.add(definition.formula_hash)
        unique.append(proposal)
    refill_round = 0
    while len(unique) < budget and refill_round < 10:
        refill_round += 1
        refill = generate_grammar_proposals(
            seed=seed + refill_round,
            count=budget - len(unique),
            interval=interval,
            market=market,
        )
        for proposal in refill:
            definition = FactorDefinition(
                key=proposal.candidate_id[:80],
                label=proposal.label,
                market=market,
                ast=proposal.ast,
                family=proposal.family,
            )
            if definition.formula_hash in formula_hashes:
                continue
            formula_hashes.add(definition.formula_hash)
            unique.append(proposal)
            if len(unique) == budget:
                break
    if len(unique) < budget:
        raise RuntimeError(f"alpha batch produced {len(unique)} of {budget} unique candidates")
    selected = unique[:budget]
    return selected, {
        "version": ALPHA_MINING_VERSION,
        "mode": "brain_mixed",
        "brief": brief,
        "candidate_count": len(selected),
        "source_counts": dict(Counter(item.source for item in selected)),
        "ai": ai_audit,
        "confirmation_labels_exposed": False,
        "dynamic_code_execution": False,
    }

"""Safe, deterministic factor definition DSL.

The DSL is deliberately data-only: callers submit a JSON AST, the validator enforces
causality, units and complexity, and the evaluator only executes a small operator
whitelist.  It never evaluates Python source or imports user-provided functions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from core.factor_research import (
    FACTOR_FORMULA_VERSION,
    FACTOR_FORMULAS,
    FACTOR_HYPOTHESIS_FAMILIES,
    FACTOR_META,
    _factor_series,
)

Direction = Literal["positive", "inverse"]
Market = Literal["a_shares", "us_stocks", "crypto", "mt5", "all"]

FIELD_UNITS = {
    "datetime": "datetime",
    "industry": "categorical",
    "open": "price",
    "high": "price",
    "low": "price",
    "close": "price",
    "volume": "volume",
    "amount": "notional",
    "market_cap": "notional",
    "beta": "dimensionless",
    "liquidity": "notional",
    "fdv": "notional",
}

TOKEN_FORMULA_ENGINE_SOURCES = {
    "alphagpt": "strategies.crypto.alphagpt.stack_vm.StackVM",
    "alphamaster": "strategies.mt5.alphamaster._upstream.model_core.vm.StackVM",
}

BUILTIN_FACTOR_FIELDS = {
    key: ("high", "low", "close", "volume")
    if key in {"volume_confirmation", "obv_momentum", "chaikin_flow"}
    else ("high", "low", "close")
    if key in {"adx_direction", "atr_contraction"}
    else ("close",)
    for key in FACTOR_META
}

SAFE_OPERATORS = {
    "field",
    "const",
    "builtin_factor",
    "token_formula",
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
    "industry_neutralize",
}


class FactorDslError(ValueError):
    """Raised when a factor AST is unsafe or structurally invalid."""


@dataclass(frozen=True)
class FactorDslLimits:
    max_depth: int = 10
    max_operators: int = 30
    max_window: int = 500
    max_lag: int = 500
    max_parameter_combinations: int = 100
    minimum_data_coverage: float = 0.8


@dataclass(frozen=True)
class FactorDefinition:
    key: str
    label: str
    market: Market
    ast: dict[str, Any]
    direction: Direction = "positive"
    horizon: int = 5
    availability_lag: int = 0
    rationale: str = ""
    family: str | None = None
    version: str = "1.0.0"
    parameters: dict[str, Any] = field(default_factory=dict)
    _canonical_ast: str = field(init=False, repr=False)
    _canonical_parameters: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        key = self.key.strip()
        if not key or len(key) > 80:
            raise FactorDslError("因子 key 不能为空且不能超过 80 个字符")
        if self.horizon < 1:
            raise FactorDslError("horizon 必须大于等于 1")
        if self.availability_lag < 0:
            raise FactorDslError("availability_lag 不能为负数")
        canonical_ast = _canonical_json(self.ast)
        canonical_parameters = _canonical_json(self.parameters)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "family", self.family or key)
        object.__setattr__(self, "_canonical_ast", canonical_ast)
        object.__setattr__(self, "_canonical_parameters", canonical_parameters)

    @property
    def ast_payload(self) -> dict[str, Any]:
        return json.loads(self._canonical_ast)

    @property
    def input_fields(self) -> tuple[str, ...]:
        return validate_factor_definition(self).fields

    @property
    def formula_hash(self) -> str:
        payload = {
            "ast": json.loads(self._canonical_ast),
            "parameters": json.loads(self._canonical_parameters),
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @property
    def definition_hash(self) -> str:
        payload = {
            "key": self.key,
            "label": self.label,
            "market": self.market,
            "formula_hash": self.formula_hash,
            "direction": self.direction,
            "horizon": self.horizon,
            "availability_lag": self.availability_lag,
            "rationale": self.rationale,
            "family": self.family,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "market": self.market,
            "input_fields": list(self.input_fields),
            "ast": self.ast_payload,
            "direction": self.direction,
            "horizon": self.horizon,
            "availability_lag": self.availability_lag,
            "rationale": self.rationale,
            "family": self.family,
            "version": self.version,
            "parameters": json.loads(self._canonical_parameters),
            "formula_hash": self.formula_hash,
            "definition_hash": self.definition_hash,
        }


@dataclass(frozen=True)
class FactorValidation:
    unit: str
    shape: Literal["series"]
    fields: tuple[str, ...]
    depth: int
    operators: int


class FactorRegistry:
    """In-memory immutable registry used by research and future persistence adapters."""

    def __init__(self) -> None:
        self._by_identity: dict[tuple[str, str], FactorDefinition] = {}
        self._by_formula_hash: dict[str, FactorDefinition] = {}

    def register(self, definition: FactorDefinition) -> FactorDefinition:
        validate_factor_definition(definition)
        identity = (definition.key, definition.version)
        existing = self._by_identity.get(identity)
        if existing and existing.definition_hash != definition.definition_hash:
            raise FactorDslError("同一 key 与 version 已存在不同定义，必须提升版本")
        duplicate = self._by_formula_hash.get(definition.formula_hash)
        if duplicate and duplicate.key != definition.key and duplicate.family != definition.family:
            raise FactorDslError(f"公式与 {duplicate.key} 完全重复，请使用同一因子族或别名")
        self._by_identity[identity] = definition
        self._by_formula_hash.setdefault(definition.formula_hash, definition)
        return definition

    def get(self, key: str, version: str) -> FactorDefinition | None:
        return self._by_identity.get((key, version))

    def list(self) -> list[FactorDefinition]:
        return sorted(self._by_identity.values(), key=lambda item: (item.key, item.version))


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise FactorDslError(f"因子定义不是可序列化 JSON: {exc}") from exc


def _node_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    op = node.get("op")
    if op in {"add", "sub", "mul", "div", "gt", "lt"}:
        return [_require_node(node, "left"), _require_node(node, "right")]
    if op in {
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
    }:
        return [_require_node(node, "value")]
    if op == "where":
        return [
            _require_node(node, "condition"),
            _require_node(node, "then"),
            _require_node(node, "else"),
        ]
    if op == "industry_neutralize":
        return [
            _require_node(node, "value"),
            _require_node(node, "industry"),
            _require_node(node, "date"),
        ]
    return []


def _require_node(node: dict[str, Any], key: str) -> dict[str, Any]:
    value = node.get(key)
    if not isinstance(value, dict):
        raise FactorDslError(f"{node.get('op')} 缺少对象字段 {key}")
    return value


def _require_positive_int(node: dict[str, Any], key: str, maximum: int) -> int:
    value = node.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise FactorDslError(f"{node.get('op')}.{key} 必须为 1 到 {maximum} 的整数")
    return value


def _validate_node(
    node: dict[str, Any],
    limits: FactorDslLimits,
    *,
    depth: int = 1,
) -> FactorValidation:
    if depth > limits.max_depth:
        raise FactorDslError(f"AST 深度超过上限 {limits.max_depth}")
    op = node.get("op")
    if op not in SAFE_OPERATORS:
        raise FactorDslError(f"不允许的因子算子: {op}")
    if op == "field":
        name = node.get("name")
        if name not in FIELD_UNITS:
            raise FactorDslError(f"未注册的数据字段: {name}")
        return FactorValidation(FIELD_UNITS[name], "series", (str(name),), depth, 1)
    if op == "const":
        value = node.get("value")
        if isinstance(value, bool) or not isinstance(value, int | float) or not np.isfinite(value):
            raise FactorDslError("const.value 必须为有限数值")
        return FactorValidation("dimensionless", "series", (), depth, 1)
    if op == "builtin_factor":
        key = node.get("key")
        if key not in FACTOR_META:
            raise FactorDslError(f"未注册的内置因子: {key}")
        return FactorValidation(
            "dimensionless",
            "series",
            BUILTIN_FACTOR_FIELDS[str(key)],
            depth,
            1,
        )
    if op == "token_formula":
        return _validate_token_formula_node(node, depth)

    children = [_validate_node(child, limits, depth=depth + 1) for child in _node_children(node)]
    operators = 1 + sum(child.operators for child in children)
    if operators > limits.max_operators:
        raise FactorDslError(f"算子数超过上限 {limits.max_operators}")
    fields = tuple(sorted({field for child in children for field in child.fields}))
    max_depth = max([depth, *(child.depth for child in children)])

    if op in {"add", "sub"}:
        if children[0].unit != children[1].unit:
            raise FactorDslError(f"{op} 两侧单位不一致: {children[0].unit} 与 {children[1].unit}")
        unit = children[0].unit
    elif op == "mul":
        left, right = children[0].unit, children[1].unit
        if left == "dimensionless":
            unit = right
        elif right == "dimensionless":
            unit = left
        elif {left, right} == {"price", "volume"}:
            unit = "notional"
        else:
            unit = f"{left}*{right}"
    elif op == "div":
        left, right = children[0].unit, children[1].unit
        unit = "dimensionless" if left == right else f"{left}/{right}"
    elif op in {"gt", "lt"}:
        if children[0].unit != children[1].unit:
            raise FactorDslError(f"{op} 两侧单位不一致")
        unit = "boolean"
    elif op == "where":
        if children[0].unit != "boolean":
            raise FactorDslError("where.condition 必须为布尔表达式")
        if children[1].unit != children[2].unit:
            raise FactorDslError("where.then 与 where.else 单位必须一致")
        unit = children[1].unit
    elif op == "industry_neutralize":
        if children[0].unit in {"boolean", "categorical", "datetime"}:
            raise FactorDslError("industry_neutralize.value 必须为数值序列")
        if children[1].unit != "categorical":
            raise FactorDslError("industry_neutralize.industry 必须为行业分类字段")
        if children[2].unit != "datetime":
            raise FactorDslError("industry_neutralize.date 必须为日期字段")
        unit = children[0].unit
    elif op == "lag":
        periods = node.get("periods")
        if isinstance(periods, bool) or not isinstance(periods, int) or periods < 0:
            raise FactorDslError("lag.periods 不能为负数，负数会引用未来数据")
        if periods > limits.max_lag:
            raise FactorDslError(f"lag.periods 超过上限 {limits.max_lag}")
        unit = children[0].unit
    elif op in {"diff", "pct_change"}:
        _require_positive_int(node, "periods", limits.max_lag)
        unit = children[0].unit if op == "diff" else "dimensionless"
    elif op.startswith("rolling_"):
        _require_positive_int(node, "window", limits.max_window)
        if op == "rolling_winsorize":
            lower = node.get("lower", 0.01)
            upper = node.get("upper", 0.99)
            if (
                isinstance(lower, bool)
                or isinstance(upper, bool)
                or not isinstance(lower, int | float)
                or not isinstance(upper, int | float)
                or not 0 <= float(lower) < float(upper) <= 1
            ):
                raise FactorDslError("rolling_winsorize 分位数必须满足 0 <= lower < upper <= 1")
        if op in {"rolling_zscore", "rolling_winsorize"}:
            unit = "dimensionless" if op == "rolling_zscore" else children[0].unit
        else:
            unit = children[0].unit
    elif op == "rank":
        _require_positive_int(node, "window", limits.max_window)
        unit = "dimensionless"
    else:
        unit = children[0].unit
    return FactorValidation(unit, "series", fields, max_depth, operators)


def count_parameter_combinations(
    parameter_grid: dict[str, Any],
    limits: FactorDslLimits | None = None,
) -> int:
    limits = limits or FactorDslLimits()
    combinations = 1
    for name, values in parameter_grid.items():
        if not str(name).strip():
            raise FactorDslError("参数名称不能为空")
        if isinstance(values, list):
            if not values:
                raise FactorDslError(f"参数 {name} 的候选值不能为空")
            combinations *= len(values)
        else:
            combinations *= 1
        if combinations > limits.max_parameter_combinations:
            raise FactorDslError(f"参数组合数超过上限 {limits.max_parameter_combinations}")
    return combinations


def _validate_token_formula_node(node: dict[str, Any], depth: int) -> FactorValidation:
    """Validate an engine token formula from its immutable vocabulary snapshot."""

    engine = node.get("engine")
    if engine not in TOKEN_FORMULA_ENGINE_SOURCES:
        raise FactorDslError(f"不允许的 token 公式引擎: {engine}")
    if node.get("engine_source") != TOKEN_FORMULA_ENGINE_SOURCES[engine]:
        raise FactorDslError("token 公式引擎来源与受控适配器不匹配")

    vocab = node.get("vocab")
    if not isinstance(vocab, dict):
        raise FactorDslError("token_formula.vocab 必须为对象")
    version = vocab.get("version")
    schema = vocab.get("schema")
    if not isinstance(version, str) or not version.strip() or len(version) > 120:
        raise FactorDslError("token_formula.vocab.version 必须为非空字符串")
    if not isinstance(schema, str) or not schema.strip() or len(schema) > 120:
        raise FactorDslError("token_formula.vocab.schema 必须为非空字符串")

    feature_names = vocab.get("feature_names")
    operators = vocab.get("operators")
    if not isinstance(feature_names, list) or not feature_names or len(feature_names) > 500:
        raise FactorDslError("token_formula.vocab.feature_names 必须为非空列表")
    if not isinstance(operators, list) or not operators or len(operators) > 500:
        raise FactorDslError("token_formula.vocab.operators 必须为非空列表")
    if any(
        not isinstance(name, str) or not name.strip() or len(name) > 80 for name in feature_names
    ):
        raise FactorDslError("token 公式特征名称必须为非空字符串")
    operator_names: list[str] = []
    operator_arities: list[int] = []
    for operator in operators:
        if not isinstance(operator, dict):
            raise FactorDslError("token 公式算子定义必须为对象")
        name = operator.get("name")
        arity = operator.get("arity")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise FactorDslError("token 公式算子名称必须为非空字符串")
        if isinstance(arity, bool) or not isinstance(arity, int) or not 1 <= arity <= 3:
            raise FactorDslError(f"token 公式算子 {name} 的 arity 必须为 1 到 3")
        operator_names.append(name)
        operator_arities.append(arity)
    token_names = [*feature_names, *operator_names]
    if len(set(token_names)) != len(token_names):
        raise FactorDslError("token 公式词表名称必须全局唯一")

    tokens = node.get("tokens")
    if not isinstance(tokens, list) or not tokens or len(tokens) > 200:
        raise FactorDslError("token_formula.tokens 必须包含 1 到 200 个 token")
    stack_depth = 0
    feature_count = len(feature_names)
    for index, token in enumerate(tokens):
        if isinstance(token, bool) or not isinstance(token, int):
            raise FactorDslError(f"token_formula.tokens[{index}] 必须为整数")
        if token < 0 or token >= len(token_names):
            raise FactorDslError(f"token_formula.tokens[{index}]={token} 超出词表范围")
        if token < feature_count:
            stack_depth += 1
            continue
        arity = operator_arities[token - feature_count]
        if stack_depth < arity:
            raise FactorDslError(f"token 公式在 {token_names[token]} 处缺少操作数")
        stack_depth = stack_depth - arity + 1
    if stack_depth != 1:
        raise FactorDslError(f"token 公式执行后栈深度为 {stack_depth}，应为 1")

    input_fields = node.get("input_fields")
    if not isinstance(input_fields, list) or not input_fields:
        raise FactorDslError("token_formula.input_fields 必须为非空列表")
    if len(set(input_fields)) != len(input_fields):
        raise FactorDslError("token_formula.input_fields 不能重复")
    unknown_fields = [field for field in input_fields if field not in FIELD_UNITS]
    if unknown_fields:
        raise FactorDslError(f"token 公式包含未注册输入字段: {', '.join(map(str, unknown_fields))}")
    return FactorValidation(
        "dimensionless",
        "series",
        tuple(sorted(str(field) for field in input_fields)),
        depth,
        1,
    )


def token_formula_ast(
    *,
    engine: Literal["alphagpt", "alphamaster"],
    tokens: list[int],
    feature_names: list[str] | tuple[str, ...],
    operators: list[tuple[str, int]] | tuple[tuple[str, int], ...],
    vocab_version: str,
    vocab_schema: str,
    input_fields: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Build and validate the canonical audit AST for a controlled StackVM formula."""

    ast = {
        "op": "token_formula",
        "engine": engine,
        "engine_source": TOKEN_FORMULA_ENGINE_SOURCES[engine],
        "tokens": list(tokens),
        "vocab": {
            "version": vocab_version,
            "schema": vocab_schema,
            "feature_names": list(feature_names),
            "operators": [{"name": name, "arity": arity} for name, arity in operators],
        },
        "input_fields": list(input_fields),
    }
    _validate_token_formula_node(ast, 1)
    return ast


def describe_token_formula(ast: dict[str, Any]) -> dict[str, Any]:
    validation = _validate_token_formula_node(ast, 1)
    vocab = ast["vocab"]
    token_names = [
        *vocab["feature_names"],
        *(operator["name"] for operator in vocab["operators"]),
    ]
    readable_tokens = [token_names[token] for token in ast["tokens"]]
    return {
        "engine": ast["engine"],
        "engine_source": ast["engine_source"],
        "tokens": list(ast["tokens"]),
        "token_names": readable_tokens,
        "expression": " -> ".join(readable_tokens),
        "vocab_version": vocab["version"],
        "vocab_schema": vocab["schema"],
        "input_fields": list(validation.fields),
    }


def validate_factor_definition(
    definition: FactorDefinition,
    limits: FactorDslLimits | None = None,
) -> FactorValidation:
    limits = limits or FactorDslLimits()
    validation = _validate_node(definition.ast_payload, limits)
    if definition.availability_lag > limits.max_lag:
        raise FactorDslError(f"availability_lag 超过上限 {limits.max_lag}")
    return validation


def evaluate_factor_ast(ast: dict[str, Any], frame: pd.DataFrame) -> pd.Series:
    """Evaluate a validated AST against a frame without executing dynamic code."""

    _validate_node(json.loads(_canonical_json(ast)), FactorDslLimits())
    index = frame.index

    def evaluate(node: dict[str, Any]) -> pd.Series:
        op = node["op"]
        if op == "field":
            name = node["name"]
            if name not in frame:
                raise FactorDslError(f"输入数据缺少字段: {name}")
            if FIELD_UNITS[name] in {"categorical", "datetime"}:
                return frame[name].copy()
            return pd.to_numeric(frame[name], errors="coerce")
        if op == "const":
            return pd.Series(float(node["value"]), index=index, dtype=float)
        if op == "builtin_factor":
            key = str(node["key"])
            missing = [field for field in BUILTIN_FACTOR_FIELDS[key] if field not in frame]
            if missing:
                raise FactorDslError(f"输入数据缺少字段: {', '.join(missing)}")
            return _factor_series(frame)[key]
        if op == "token_formula":
            raise FactorDslError(
                "token 公式必须由其受控引擎适配器执行，通用 pandas DSL 不直接执行 StackVM"
            )
        if op in {"add", "sub", "mul", "div", "gt", "lt"}:
            left = evaluate(node["left"])
            right = evaluate(node["right"])
            if op == "add":
                return left.add(right)
            if op == "sub":
                return left.sub(right)
            if op == "mul":
                return left.mul(right)
            if op == "div":
                return left.div(right.replace(0, np.nan))
            if op == "gt":
                return left.gt(right)
            return left.lt(right)
        if op == "where":
            condition = evaluate(node["condition"]).fillna(False).astype(bool)
            return evaluate(node["then"]).where(condition, evaluate(node["else"]))
        if op == "industry_neutralize":
            value = pd.to_numeric(evaluate(node["value"]), errors="coerce")
            industry = evaluate(node["industry"])
            dates = evaluate(node["date"])
            grouped = pd.DataFrame(
                {"value": value, "industry": industry, "date": dates},
                index=index,
            )
            group_mean = grouped.groupby(["date", "industry"], dropna=False)["value"].transform(
                "mean"
            )
            return value.sub(group_mean)
        value = evaluate(node["value"])
        if op == "neg":
            return value.mul(-1)
        if op == "abs":
            return value.abs()
        if op == "lag":
            return value.shift(int(node["periods"]))
        if op == "diff":
            return value.diff(int(node["periods"]))
        if op == "pct_change":
            return value.pct_change(int(node["periods"]), fill_method=None)
        window = int(node["window"])
        rolling = value.rolling(window, min_periods=window)
        if op == "rank":
            return rolling.apply(
                lambda values: float(pd.Series(values).rank(pct=True).iloc[-1]),
                raw=False,
            )
        if op == "rolling_mean":
            return rolling.mean()
        if op == "rolling_std":
            return rolling.std(ddof=0)
        if op == "rolling_min":
            return rolling.min()
        if op == "rolling_max":
            return rolling.max()
        if op == "rolling_sum":
            return rolling.sum()
        if op == "rolling_zscore":
            return value.sub(rolling.mean()).div(rolling.std(ddof=0).replace(0, np.nan))
        if op == "rolling_winsorize":
            lower = float(node.get("lower", 0.01))
            upper = float(node.get("upper", 0.99))
            if not 0 <= lower < upper <= 1:
                raise FactorDslError("rolling_winsorize 分位数必须满足 0 <= lower < upper <= 1")
            lower_bound = rolling.quantile(lower)
            upper_bound = rolling.quantile(upper)
            return value.clip(lower=lower_bound, upper=upper_bound)
        raise FactorDslError(f"未实现的因子算子: {op}")

    result = evaluate(json.loads(_canonical_json(ast)))
    return pd.to_numeric(result, errors="coerce").replace([np.inf, -np.inf], np.nan)


def evaluate_factor_definition(definition: FactorDefinition, frame: pd.DataFrame) -> pd.Series:
    validate_factor_definition(definition)
    result = evaluate_factor_ast(definition.ast_payload, frame)
    return result.shift(definition.availability_lag) if definition.availability_lag else result


def validate_factor_data_coverage(
    definition: FactorDefinition,
    frame: pd.DataFrame,
    limits: FactorDslLimits | None = None,
) -> dict[str, float | int]:
    limits = limits or FactorDslLimits()
    if not 0 < limits.minimum_data_coverage <= 1:
        raise FactorDslError("minimum_data_coverage 必须在 0 到 1 之间")
    result = evaluate_factor_definition(definition, frame)
    valid = result.notna().to_numpy()
    if not valid.any():
        raise FactorDslError("因子在输入数据上没有任何有效值")
    first_valid = int(np.flatnonzero(valid)[0])
    eligible = len(result) - first_valid
    valid_count = int(valid[first_valid:].sum())
    coverage = valid_count / eligible if eligible else 0.0
    if coverage < limits.minimum_data_coverage:
        raise FactorDslError(
            f"因子数据覆盖率 {coverage:.2%} 低于门槛 {limits.minimum_data_coverage:.2%}"
        )
    return {
        "coverage": coverage,
        "valid_values": valid_count,
        "eligible_values": eligible,
        "warmup_rows": first_valid,
    }


def builtin_factor_definitions() -> list[FactorDefinition]:
    definitions: list[FactorDefinition] = []
    for key, (label, category, description) in FACTOR_META.items():
        definitions.append(
            FactorDefinition(
                key=key,
                label=label,
                market="all",
                ast={"op": "builtin_factor", "key": key},
                direction="positive",
                horizon=5,
                rationale=description,
                family=FACTOR_HYPOTHESIS_FAMILIES[key],
                version=FACTOR_FORMULA_VERSION,
                parameters={
                    "category": category,
                    "formula": FACTOR_FORMULAS[key],
                    "formula_version": FACTOR_FORMULA_VERSION,
                    "adapter": "core.factor_research._factor_series",
                },
            )
        )
    return definitions


def detect_series_redundancy(
    series_by_key: dict[str, pd.Series],
    *,
    minimum_observations: int = 30,
    high_correlation_threshold: float = 0.95,
    monotonic_threshold: float = 0.999,
    numerical_tolerance: float = 1e-10,
    tail_quantile: float = 0.1,
    regimes: pd.Series | None = None,
    include_all_pairs: bool = False,
) -> list[dict[str, Any]]:
    keys = sorted(series_by_key)
    pairs: list[dict[str, Any]] = []
    for left_index, left_key in enumerate(keys):
        for right_key in keys[left_index + 1 :]:
            aligned = (
                pd.concat([series_by_key[left_key], series_by_key[right_key]], axis=1)
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
            )
            if len(aligned) < minimum_observations:
                continue
            left = aligned.iloc[:, 0].astype(float).to_numpy()
            right = aligned.iloc[:, 1].astype(float).to_numpy()
            pearson = float(pd.Series(left).corr(pd.Series(right), method="pearson"))
            spearman = float(
                pd.Series(left).rank(method="average").corr(pd.Series(right).rank(method="average"))
            )
            tail_threshold_left = float(
                pd.Series(left).sub(float(np.mean(left))).abs().quantile(1 - tail_quantile)
            )
            tail_threshold_right = float(
                pd.Series(right).sub(float(np.mean(right))).abs().quantile(1 - tail_quantile)
            )
            tail_mask = (np.abs(left - np.mean(left)) >= tail_threshold_left) | (
                np.abs(right - np.mean(right)) >= tail_threshold_right
            )
            tail_observations = int(tail_mask.sum())
            tail_pearson = (
                float(pd.Series(left[tail_mask]).corr(pd.Series(right[tail_mask])))
                if tail_observations >= 3
                else None
            )
            regime_correlations: list[dict[str, Any]] = []
            if regimes is not None:
                aligned_regimes = regimes.reindex(aligned.index)
                for regime in sorted(str(value) for value in aligned_regimes.dropna().unique()):
                    regime_mask = aligned_regimes.astype(str).eq(regime).to_numpy()
                    regime_observations = int(regime_mask.sum())
                    if regime_observations < max(5, minimum_observations // 3):
                        continue
                    regime_correlations.append(
                        {
                            "regime": regime,
                            "observations": regime_observations,
                            "pearson": float(
                                pd.Series(left[regime_mask]).corr(
                                    pd.Series(right[regime_mask]), method="pearson"
                                )
                            ),
                            "spearman": float(
                                pd.Series(left[regime_mask])
                                .rank(method="average")
                                .corr(pd.Series(right[regime_mask]).rank(method="average"))
                            ),
                        }
                    )
            relation: str | None = None
            scale: float | None = None
            if np.allclose(left, right, rtol=numerical_tolerance, atol=numerical_tolerance):
                relation = "exact_duplicate"
                scale = 1.0
            else:
                denominator = float(np.dot(left, left))
                if denominator > numerical_tolerance:
                    scale = float(np.dot(left, right) / denominator)
                    residual = right - scale * left
                    relative_error = float(
                        np.linalg.norm(residual) / max(np.linalg.norm(right), numerical_tolerance)
                    )
                    if abs(scale) > numerical_tolerance and relative_error <= numerical_tolerance:
                        relation = "constant_multiple"
                if relation is None and abs(spearman) >= monotonic_threshold:
                    relation = "monotonic_equivalent"
                elif (
                    relation is None
                    and max(abs(pearson), abs(spearman)) >= high_correlation_threshold
                ):
                    relation = "high_correlation"
            if relation is None and not include_all_pairs:
                continue
            relation = relation or "distinct"
            pairs.append(
                {
                    "left_key": left_key,
                    "right_key": right_key,
                    "relation": relation,
                    "direction": "same" if spearman >= 0 else "inverse",
                    "observations": len(aligned),
                    "pearson": pearson,
                    "spearman": spearman,
                    "tail_pearson": tail_pearson,
                    "tail_observations": tail_observations,
                    "regime_correlations": regime_correlations,
                    "scale": scale if relation == "constant_multiple" else None,
                }
            )
    return pairs


def detect_factor_redundancy(
    definitions: list[FactorDefinition],
    frame: pd.DataFrame,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    series_by_key = {
        f"{definition.key}@{definition.version}": evaluate_factor_definition(definition, frame)
        for definition in definitions
    }
    return detect_series_redundancy(series_by_key, **kwargs)

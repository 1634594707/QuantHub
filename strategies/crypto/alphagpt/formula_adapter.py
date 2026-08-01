"""Lightweight AlphaGPT StackVM-to-FactorDefinition audit adapter.

This module intentionally has no torch dependency.  Search results can therefore be
validated, hashed and persisted even when the optional execution runtime is absent.
"""

from __future__ import annotations

import hashlib
from typing import Any

from core.factor_dsl import FactorDefinition, describe_token_formula, token_formula_ast

FEATURE_NAMES = (
    "RET",
    "LIQ_SCORE",
    "PRESSURE",
    "FOMO",
    "DEV",
    "LOG_VOL",
)
OPERATORS = (
    ("ADD", 2),
    ("SUB", 2),
    ("MUL", 2),
    ("DIV", 2),
    ("NEG", 1),
    ("ABS", 1),
    ("SIGN", 1),
    ("GATE", 3),
    ("JUMP", 1),
    ("DECAY", 1),
    ("DELAY1", 1),
    ("MAX3", 1),
)
VOCAB_SCHEMA = "alphagpt-stack-vm-1"
TOKEN_NAMES = (*FEATURE_NAMES, *(name for name, _ in OPERATORS))
VOCAB_VERSION = "v" + hashlib.sha256("\n".join(TOKEN_NAMES).encode("utf-8")).hexdigest()[:12]
INPUT_FIELDS = ("open", "high", "low", "close", "volume", "liquidity", "fdv")


def _normalize_formulas(formulas: Any) -> list[list[int]]:
    if not isinstance(formulas, list) or not formulas:
        raise ValueError("公式不能为空")
    candidates = [formulas] if all(isinstance(token, int) for token in formulas) else formulas
    normalized: list[list[int]] = []
    for index, formula in enumerate(candidates):
        if not isinstance(formula, list) or not formula:
            raise ValueError(f"第 {index + 1} 条公式为空或不是 token 列表")
        if any(isinstance(token, bool) or not isinstance(token, int) for token in formula):
            raise ValueError(f"第 {index + 1} 条公式包含非整数 token")
        normalized.append([int(token) for token in formula])
    return normalized


def formula_ast(tokens: list[int]) -> dict[str, Any]:
    return token_formula_ast(
        engine="alphagpt",
        tokens=tokens,
        feature_names=FEATURE_NAMES,
        operators=OPERATORS,
        vocab_version=VOCAB_VERSION,
        vocab_schema=VOCAB_SCHEMA,
        input_fields=INPUT_FIELDS,
    )


def describe_formulas(formulas: Any) -> list[dict[str, Any]]:
    return [describe_token_formula(formula_ast(tokens)) for tokens in _normalize_formulas(formulas)]


def factor_definitions(
    formulas: Any,
    *,
    key_prefix: str = "alphagpt_token",
    label_prefix: str = "AlphaGPT token 因子",
    version: str = "1.0.0",
    horizon: int = 5,
    availability_lag: int = 0,
    rationale: str = "AlphaGPT StackVM 搜索候选，经统一因子注册表审计。",
) -> list[FactorDefinition]:
    definitions: list[FactorDefinition] = []
    for index, tokens in enumerate(_normalize_formulas(formulas), start=1):
        ast = formula_ast(tokens)
        details = describe_token_formula(ast)
        definitions.append(
            FactorDefinition(
                key=f"{key_prefix}_{index:03d}",
                label=f"{label_prefix} {index}",
                market="crypto",
                ast=ast,
                horizon=horizon,
                availability_lag=availability_lag,
                rationale=rationale,
                family=f"{key_prefix}_stackvm",
                version=version,
                parameters={
                    "adapter": "strategies.crypto.alphagpt.formula_adapter",
                    **details,
                },
            )
        )
    return definitions

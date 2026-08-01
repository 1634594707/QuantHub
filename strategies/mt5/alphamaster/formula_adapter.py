"""Torch-free AlphaMaster StackVM-to-FactorDefinition audit adapter.

The current vocabulary is derived from the controlled vendored source with Python's
syntax tree.  No upstream code is executed, so definitions remain importable in the
default environment where torch is intentionally optional.
"""

from __future__ import annotations

import ast
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.factor_dsl import FactorDefinition, describe_token_formula, token_formula_ast

UPSTREAM_ROOT = Path(__file__).resolve().parent / "_upstream"
FEATURES_PATH = UPSTREAM_ROOT / "model_core" / "features.py"
OPS_PATH = UPSTREAM_ROOT / "model_core" / "ops.py"
ACTIVE_FEATURES_PATH = UPSTREAM_ROOT / "active_features.json"
VOCAB_SCHEMA = "4.0-registry"
INPUT_FIELDS = ("open", "high", "low", "close", "volume")
OPERATOR_LISTS = (
    "_INITIAL_OPERATORS",
    "_CROSS_SECTIONAL_OPERATORS",
    "_TASK33_OPERATORS",
    "_TASK34_OPERATORS",
)


def _assigned_list(path: Path, variable: str) -> ast.List:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == variable for target in node.targets):
            if isinstance(node.value, ast.List):
                return node.value
            break
    raise ValueError(f"无法从 {path.name} 恢复 {variable} 词表声明")


def _tuple_string_and_int(node: ast.AST, *, variable: str) -> tuple[str, int]:
    if not isinstance(node, ast.Tuple) or len(node.elts) < 3:
        raise ValueError(f"{variable} 包含不可审计的非三元组声明")
    name_node, arity_node = node.elts[0], node.elts[2]
    if not isinstance(name_node, ast.Constant) or not isinstance(name_node.value, str):
        raise TypeError(f"{variable} 包含非字面量名称")
    if not isinstance(arity_node, ast.Constant) or not isinstance(arity_node.value, int):
        raise TypeError(f"{variable} 包含非字面量 arity")
    return name_node.value, arity_node.value


def _feature_names() -> tuple[str, ...]:
    declarations = _assigned_list(FEATURES_PATH, "_FEATURE_DEFS")
    names = tuple(
        _tuple_string_and_int_proxy(node, variable="_FEATURE_DEFS") for node in declarations.elts
    )
    if not ACTIVE_FEATURES_PATH.exists():
        return names
    payload = json.loads(ACTIVE_FEATURES_PATH.read_text(encoding="utf-8"))
    active = payload.get("active_features") if isinstance(payload, dict) else payload
    allowed = {str(name) for name in active or []}
    return tuple(name for name in names if name in allowed) if allowed else names


def _tuple_string_and_int_proxy(node: ast.AST, *, variable: str) -> str:
    if not isinstance(node, ast.Tuple) or not node.elts:
        raise ValueError(f"{variable} 包含不可审计的特征声明")
    name_node = node.elts[0]
    if not isinstance(name_node, ast.Constant) or not isinstance(name_node.value, str):
        raise TypeError(f"{variable} 包含非字面量名称")
    return name_node.value


def _operators() -> tuple[tuple[str, int], ...]:
    result: list[tuple[str, int]] = []
    for variable in OPERATOR_LISTS:
        declarations = _assigned_list(OPS_PATH, variable)
        result.extend(_tuple_string_and_int(node, variable=variable) for node in declarations.elts)
    return tuple(result)


@lru_cache(maxsize=1)
def vocab_manifest() -> dict[str, Any]:
    features = _feature_names()
    operators = _operators()
    token_names = (*features, *(name for name, _ in operators))
    if len(set(token_names)) != len(token_names):
        raise ValueError("AlphaMaster 源码词表存在重复名称")
    version = "v" + hashlib.sha256("\n".join(token_names).encode("utf-8")).hexdigest()[:12]
    return {
        "feature_names": features,
        "operators": operators,
        "token_names": token_names,
        "version": version,
        "schema": VOCAB_SCHEMA,
    }


def normalize_formulas(formulas: Any) -> list[list[int]]:
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
    manifest = vocab_manifest()
    return token_formula_ast(
        engine="alphamaster",
        tokens=tokens,
        feature_names=manifest["feature_names"],
        operators=manifest["operators"],
        vocab_version=manifest["version"],
        vocab_schema=manifest["schema"],
        input_fields=INPUT_FIELDS,
    )


def validate_formulas(formulas: Any) -> list[list[int]]:
    normalized = normalize_formulas(formulas)
    for tokens in normalized:
        formula_ast(tokens)
    return normalized


def describe_formulas(formulas: Any) -> list[dict[str, Any]]:
    return [describe_token_formula(formula_ast(tokens)) for tokens in validate_formulas(formulas)]


def factor_definitions(
    formulas: Any,
    *,
    key_prefix: str = "alphamaster_token",
    label_prefix: str = "AlphaMaster token 因子",
    version: str = "1.0.0",
    horizon: int = 5,
    availability_lag: int = 0,
    rationale: str = "AlphaMaster StackVM 搜索候选，经统一因子注册表审计。",
) -> list[FactorDefinition]:
    definitions: list[FactorDefinition] = []
    for index, tokens in enumerate(validate_formulas(formulas), start=1):
        ast = formula_ast(tokens)
        details = describe_token_formula(ast)
        definitions.append(
            FactorDefinition(
                key=f"{key_prefix}_{index:03d}",
                label=f"{label_prefix} {index}",
                market="mt5",
                ast=ast,
                horizon=horizon,
                availability_lag=availability_lag,
                rationale=rationale,
                family=f"{key_prefix}_stackvm",
                version=version,
                parameters={
                    "adapter": "strategies.mt5.alphamaster.formula_adapter",
                    **details,
                },
            )
        )
    return definitions

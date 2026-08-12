"""统一配置加载器。

从 configs/*.yaml 加载并合并配置；支持 schema_version 升级钩子。
所有模块通过 ``core.config.get_config()`` 获取单一配置对象，避免重复读取。
"""

from __future__ import annotations

import os
from copy import deepcopy
from functools import cache
from pathlib import Path
from typing import Any

import yaml

# 仓库根目录（core/config.py 的上两级）
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = REPO_ROOT / "configs"
_LLM_PROVIDER_DEFAULTS = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "timeout": 60,
        "max_retries": 3,
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "timeout": 60,
        "max_retries": 3,
    },
    "custom": {
        "api_key_env": "QUANTHUB_CUSTOM_LLM_API_KEY",
        "base_url": "http://localhost:1234/v1",
        "model": "local-model",
        "timeout": 60,
        "max_retries": 3,
    },
}


class SchemaVersionError(Exception):
    """配置 schema 版本不兼容时抛出。"""


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 到 base，返回新 dict（不修改入参）。"""
    result = deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = deepcopy(val)
    return result


def _resolve_env_placeholders(obj: Any) -> Any:
    """递归把 ``*_env`` 字段替换为对应环境变量值（仅读，不写入仓库）。

    约定：形如 ``{api_key_env: "FOO"}`` 的字段会被解析为环境变量 FOO 的值；
    若环境变量不存在则置为 None，由调用方决定是否报错。
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            # 保留原 key（便于调试来源），同时暴露无后缀字段（值为环境变量内容）
            out[k] = v
            if k.endswith("_env") and isinstance(v, str):
                field_name = k[: -len("_env")]
                out[field_name] = os.environ.get(v)
            else:
                out[k] = _resolve_env_placeholders(v)
        return out
    if isinstance(obj, list):
        return [_resolve_env_placeholders(x) for x in obj]
    return obj


def _migrate_schema(cfg: dict, current_schema: int) -> dict:
    """配置升级钩子：根据 schema_version 做兼容性迁移。

    当前 schema_version=1，无需迁移。
    未来 schema 升级时在此处追加 if 分支，逐版本向上迁移。
    """
    if current_schema < 1:
        raise SchemaVersionError(f"不支持的 schema_version: {current_schema}")
    # 示例（未来启用）:
    # if current_schema == 1:
    #     cfg = _migrate_v1_to_v2(cfg)
    #     current_schema = 2
    return cfg


def _apply_llm_env_overrides(cfg: dict) -> None:
    llm = cfg.setdefault("llm", {})
    provider = os.environ.get("QUANTHUB_LLM_PROVIDER", str(llm.get("provider", "deepseek")))
    llm["provider"] = provider
    active_string_overrides = {
        "QUANTHUB_LLM_BASE_URL": "base_url",
        "QUANTHUB_LLM_MODEL": "model",
    }
    active_integer_overrides = {
        "QUANTHUB_LLM_TIMEOUT": "timeout",
        "QUANTHUB_LLM_MAX_RETRIES": "max_retries",
    }
    provider_config = llm.setdefault(provider, {})
    for env_name, field in active_string_overrides.items():
        if value := os.environ.get(env_name):
            provider_config[field] = value
    for env_name, field in active_integer_overrides.items():
        if value := os.environ.get(env_name):
            try:
                provider_config[field] = int(value)
            except ValueError:
                pass
    for provider_id, defaults in _LLM_PROVIDER_DEFAULTS.items():
        provider_config = llm.setdefault(provider_id, {})
        for field, default in defaults.items():
            provider_config.setdefault(field, default)
        prefix = f"QUANTHUB_LLM_{provider_id.upper()}"
        for suffix, field in (("BASE_URL", "base_url"), ("MODEL", "model")):
            if value := os.environ.get(f"{prefix}_{suffix}"):
                provider_config[field] = value
        for suffix, field in (("TIMEOUT", "timeout"), ("MAX_RETRIES", "max_retries")):
            if value := os.environ.get(f"{prefix}_{suffix}"):
                try:
                    provider_config[field] = int(value)
                except ValueError:
                    pass


# maxsize=None：market 取值有限（None/a_shares/crypto），不会膨胀；
# 多市场交替调用时避免反复重读 base.yaml + 重跑 _resolve_env_placeholders。
# cache_clear() 语义保留，set_api_key 等场景仍可一键失效。
@cache
def get_config(market: str | None = None) -> dict:
    """加载并合并配置。

    Args:
        market: 可选，加载市场专属配置 ("a_shares" | "crypto")。
                None 时仅返回 base 配置。

    Returns:
        合并后的配置 dict。base.yaml 为底，叠加市场 yaml。
    """
    base_path = CONFIGS_DIR / "base.yaml"
    if not base_path.exists():
        raise FileNotFoundError(f"未找到基础配置: {base_path}")

    with base_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if market:
        market_path = CONFIGS_DIR / f"{market}.yaml"
        if not market_path.exists():
            raise FileNotFoundError(f"未找到市场配置: {market_path}")
        with market_path.open("r", encoding="utf-8") as f:
            market_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, market_cfg)

    # schema 升级
    schema_ver = int(cfg.get("schema_version", 1))
    cfg = _migrate_schema(cfg, schema_ver)

    _apply_llm_env_overrides(cfg)

    # 解析环境变量占位符
    cfg = _resolve_env_placeholders(cfg)
    alert = cfg.get("alert")
    if isinstance(alert, dict):
        enabled_override = os.environ.get("QUANTHUB_ALERT_ENABLED")
        if enabled_override is not None:
            alert["enabled"] = enabled_override == "1"
        channels_override = os.environ.get("QUANTHUB_ALERT_CHANNELS")
        if channels_override is not None:
            alert["channels"] = [
                item.strip() for item in channels_override.split(",") if item.strip()
            ]

    return cfg


def get_repo_root() -> Path:
    """返回仓库根目录 Path。"""
    return REPO_ROOT


def get_path(key: str, market: str | None = None) -> Path:
    """读取 paths.<key> 并返回绝对路径（相对仓库根解析）。"""
    cfg = get_config(market)
    raw = cfg.get("paths", {}).get(key)
    if raw is None:
        raise KeyError(f"paths.{key} 不存在于配置")
    p = Path(raw)
    return p if p.is_absolute() else REPO_ROOT / p

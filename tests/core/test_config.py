# -*- coding: utf-8 -*-
"""core.config 单测。"""
from __future__ import annotations

import os

from core.config import CONFIGS_DIR, get_config, get_repo_root, _deep_merge, _resolve_env_placeholders


def test_repo_root_exists():
    assert get_repo_root().exists()


def test_configs_dir_exists():
    assert CONFIGS_DIR.exists()
    assert (CONFIGS_DIR / "base.yaml").exists()


def test_base_config_loads():
    cfg = get_config()
    assert "live_trading" in cfg
    assert cfg["live_trading"] is False   # 默认研究模式
    assert cfg["schema_version"] == 1


def test_market_config_merge():
    cfg = get_config("a_shares")
    assert cfg["market"] == "a_shares"
    # base 字段仍在
    assert "live_trading" in cfg
    # 市场字段已合并
    assert "trading_hours" in cfg


def test_crypto_config():
    cfg = get_config("crypto")
    assert cfg["market"] == "crypto"
    assert "risk" in cfg


def test_deep_merge():
    base = {"a": 1, "b": {"x": 1, "y": 2}}
    override = {"b": {"y": 3, "z": 4}, "c": 5}
    out = _deep_merge(base, override)
    assert out == {"a": 1, "b": {"x": 1, "y": 3, "z": 4}, "c": 5}
    # 不修改入参
    assert base["b"]["y"] == 2


def test_resolve_env_placeholders(monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "secret123")
    obj = {"api_key_env": "FAKE_KEY", "other": {"token_env": "NOPE"}}
    out = _resolve_env_placeholders(obj)
    assert out["api_key"] == "secret123"
    assert out["api_key_env"] == "FAKE_KEY"
    assert out["other"]["token"] is None  # NOPE 未设置

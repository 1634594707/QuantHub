from __future__ import annotations

import asyncio
import builtins

from strategies.crypto.alphagpt import risk


def test_honeypot_check_fails_closed_when_executor_dependency_is_missing(monkeypatch) -> None:
    original_import = builtins.__import__

    def missing_execution(name, *args, **kwargs):
        if name == "execution.jupiter" or name.startswith("execution."):
            raise ImportError("solana dependency unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_execution)

    result = asyncio.run(risk.check_honeypot("TOKEN", 10_000))

    assert result is False

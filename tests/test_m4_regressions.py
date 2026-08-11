from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import pandas as pd
from starlette.responses import JSONResponse

from apps.okx_runner.private_ws import make_login_args
from apps.okx_runner.reconcile_scheduler import ReconcileScheduler
from apps.okx_runner.runner_errors import RunnerError
from core.backtest.strategies_demo import run_signal_backtest
from tools.observe_daily import section


def test_private_ws_login_uses_official_object_shape() -> None:
    args = make_login_args("api-key", "secret-key", "passphrase")

    assert set(args) == {"apiKey", "passphrase", "timestamp", "sign"}
    prehash = args["timestamp"] + "GET" + "/users/self/verify"
    expected = base64.b64encode(
        hmac.new(b"secret-key", prehash.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    assert args == {
        "apiKey": "api-key",
        "passphrase": "passphrase",
        "timestamp": args["timestamp"],
        "sign": expected,
    }


def test_runner_error_redacts_message_secrets() -> None:
    error = RunnerError("TEST", "request failed api_key=visible-secret")

    serialized = json.dumps(error.to_dict())

    assert "visible-secret" not in serialized
    assert "[REDACTED]" in serialized


def test_observation_section_preserves_business_failure() -> None:
    result = section("private_ws", lambda: {"ok": False, "login_response": None})

    assert result == {"ok": False, "detail": {"login_response": None}}


def test_backtest_executes_next_open_and_uses_net_pnl() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "open": [100.0, 100.0, 101.0],
            "close": [100.0, 101.0, 101.0],
        }
    )

    result = run_signal_backtest(
        frame,
        pd.Series([1.0, 0.0, 0.0]),
        initial_capital=1_000.0,
        commission=0.01,
    )

    assert result["trades"][0]["datetime"].startswith("2024-01-02")
    assert result["trades"][-1]["realized_pnl"] < 0
    assert result["metrics"]["trade_win_rate"] == 0.0
    assert result["final_equity"] == result["equity_curve"][-1]["equity"]


def test_backtest_metrics_are_json_safe_without_losing_trades() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "open": [100.0, 100.0, 101.0],
            "close": [100.0, 100.0, 101.0],
        }
    )

    result = run_signal_backtest(frame, pd.Series([1.0, 0.0, 0.0]), commission=0.0)

    assert result["metrics"]["profit_factor"] is None
    JSONResponse(result)


def test_scheduler_can_restart_after_stop(tmp_path: Path) -> None:
    calls: list[float] = []

    def reconcile() -> dict:
        calls.append(time.time())
        return {"passed": True, "difference_ids": []}

    scheduler = ReconcileScheduler(tmp_path)
    scheduler.configure(reconcile, "demo", interval_seconds=1.0)
    scheduler.start()
    scheduler.stop()
    assert not scheduler.is_running()

    scheduler.configure(reconcile, "demo", interval_seconds=1.0)
    scheduler.start()
    scheduler.stop()

    assert not scheduler.is_running()
    assert len(calls) >= 1

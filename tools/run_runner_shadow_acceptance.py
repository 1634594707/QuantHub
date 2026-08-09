"""Create auditable timed shadow evidence from local OKX market bars."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pandas as pd

from apps.okx_runner.adapter import DisabledAdapter
from apps.okx_runner.engine import RunnerEngine
from packages.strategy_package import RiskLimits, StrategyReleasePayload, create_release_package


def _package(key: bytes, source_hash: str):
    formula = '{"op":"pct_change","periods":2,"value":{"name":"close","op":"field"}}'
    payload = StrategyReleasePayload(
        strategy_id="okx-shadow-contract",
        version="1.0.0",
        target_market="okx",
        product_type="usdt_perpetual",
        runner_compatibility="1.0.0",
        formula=formula,
        formula_hash=sha256(formula.encode()).hexdigest(),
        parameters={"lookback": 2},
        universe={"symbols": ["BTC-USDT-SWAP"]},
        signal_frequency="1h",
        rebalance_frequency="4h",
        data_fields=("close",),
        data_delay_seconds=5,
        data_snapshot_id=source_hash,
        research_engine_version="shadow-contract-1.0.0",
        out_of_sample_results={"contract_fixture_only": 1.0},
        cost_assumptions={"fee_bps": 5, "spread_bps": 2, "slippage_bps": 3},
        risk_limits=RiskLimits(
            max_leverage=1,
            max_symbol_exposure=0.01,
            max_total_exposure=0.05,
            max_loss=50,
            max_drawdown=0.02,
        ),
        simulation_results={"status": "contract_fixture_only", "alpha_claim": False},
        allowed_environments=("shadow",),
        approved_by="local-shadow-contract",
        approved_at=datetime.now(UTC),
        audit_record_ids=("timed-local-market-replay",),
    )
    return create_release_package(payload, key)


def run(source: Path, interval_seconds: float) -> dict:
    frame = pd.read_parquet(source).tail(5)
    if len(frame) < 5:
        raise RuntimeError("shadow acceptance requires at least five source bars")
    closes = [float(value) for value in frame["close"]]
    source_times = [
        datetime.fromtimestamp(float(value), UTC).isoformat() for value in frame["time"]
    ]
    source_hash = sha256(
        json.dumps(list(zip(source_times, closes, strict=True)), separators=(",", ":")).encode()
    ).hexdigest()

    def timed_bars():
        for source_time, close in zip(source_times, closes, strict=True):
            event_time = datetime.now(UTC)
            time.sleep(interval_seconds)
            yield {
                "event_time": event_time.isoformat(),
                "observed_at": datetime.now(UTC).isoformat(),
                "source_event_time": source_time,
                "close": close,
            }

    key = b"local-shadow-acceptance-key-32b!"
    with tempfile.TemporaryDirectory() as temporary:
        engine = RunnerEngine(Path(temporary) / "shadow.db", DisabledAdapter(), key, "shadow")
        package = _package(key, source_hash)
        engine.import_package(package)
        runtime = engine.run_shadow_session(
            package.payload.strategy_id,
            package.payload.version,
            timed_bars(),
            feed_mode="timed_local_market_replay",
        )
    try:
        source_label = source.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        source_label = str(source)
    return {
        "accepted": True,
        "alpha_claim": False,
        "external_market_realtime": False,
        "local_stream_realtime": True,
        "interval_seconds": interval_seconds,
        "source": source_label,
        "source_hash": source_hash,
        "source_event_times": source_times,
        "network_note": "OKX public endpoint was unreachable from the acceptance environment",
        "runtime": runtime,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/OKX_K线数据/BTCUSDT_M5.parquet"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=0.25)
    args = parser.parse_args()
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    evidence = run(args.source.resolve(), args.interval_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "accepted": True,
                "observations": len(evidence["runtime"]["result"]["observations"]),
                "alpha_claim": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

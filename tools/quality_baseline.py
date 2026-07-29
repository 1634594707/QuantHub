"""Measure deterministic SQLite data-volume and query latency baselines."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from apps.api import database, store


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def run_baseline(
    *,
    records: int = 10_000,
    iterations: int = 20,
    max_write_ms: float = 15_000,
    max_list_p95_ms: float = 250,
) -> dict:
    if records < 1 or iterations < 1:
        raise ValueError("records 和 iterations 必须大于等于 1")
    original_db = store._DB
    with tempfile.TemporaryDirectory(prefix="quanthub-baseline-") as temporary:
        target = Path(temporary) / "baseline.db"
        store._DB = target
        database.dispose_engines()
        try:
            init_started = time.perf_counter()
            store._init()
            init_ms = (time.perf_counter() - init_started) * 1000

            write_started = time.perf_counter()
            with store._lock, store._conn() as connection:
                for index in range(records):
                    epoch = float(index + 1)
                    connection.execute(
                        """INSERT INTO signals
                           (id, instrument_id, symbol, market, timeframe, direction,
                            score, confidence, source, tags_json, meta_json, ts_iso,
                            ts_epoch, status, fingerprint, received_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            f"baseline-{index}",
                            f"a_shares:{index:06d}",
                            f"{index:06d}",
                            "a_shares",
                            "1d",
                            "buy",
                            0.5,
                            0.5,
                            "quality_baseline",
                            "[]",
                            "{}",
                            "2026-07-27T00:00:00+08:00",
                            epoch,
                            "new",
                            f"baseline-fingerprint-{index}",
                            epoch,
                        ),
                    )
            write_ms = (time.perf_counter() - write_started) * 1000

            list_latencies = []
            for _ in range(iterations):
                started = time.perf_counter()
                rows = store.list_signals(limit=200, source="quality_baseline")
                list_latencies.append((time.perf_counter() - started) * 1000)
                if len(rows) != min(records, 200):
                    raise RuntimeError("基线查询返回数量不一致")
            with store._lock, store._conn() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) AS count FROM signals WHERE source=?",
                    ("quality_baseline",),
                ).fetchone()["count"]
            database.dispose_engines()
            result = {
                "ok": write_ms <= max_write_ms
                and _percentile(list_latencies, 0.95) <= max_list_p95_ms,
                "records": int(count),
                "database_bytes": target.stat().st_size,
                "schema_init_ms": round(init_ms, 3),
                "bulk_write_ms": round(write_ms, 3),
                "list_median_ms": round(statistics.median(list_latencies), 3),
                "list_p95_ms": round(_percentile(list_latencies, 0.95), 3),
                "thresholds": {
                    "max_write_ms": max_write_ms,
                    "max_list_p95_ms": max_list_p95_ms,
                },
            }
            return result
        finally:
            database.dispose_engines()
            store._DB = original_db


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantHub quality baseline")
    parser.add_argument("--records", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--max-write-ms", type=float, default=15_000)
    parser.add_argument("--max-list-p95-ms", type=float, default=250)
    args = parser.parse_args()
    result = run_baseline(
        records=args.records,
        iterations=args.iterations,
        max_write_ms=args.max_write_ms,
        max_list_p95_ms=args.max_list_p95_ms,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

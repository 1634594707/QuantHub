from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from core.cross_sectional_research import (
    LABEL_HORIZONS,
    CrossSectionConfig,
    analyze_cross_sectional_panel,
)
from core.factor_research import FACTOR_META, _clean_frame, _factor_series
from core.point_in_time_universe import (
    a_share_tradability_reasons,
    assess_universe_frame_quality,
    build_snapshot_fingerprints,
    fingerprint_file,
    fingerprint_payload,
)


def select_files(root: Path, size: int, minimum_rows: int) -> list[tuple[Path, int]]:
    eligible = []
    for path in sorted(root.glob("*_daily.parquet")):
        rows = int(pq.ParquetFile(path).metadata.num_rows)
        if rows >= minimum_rows:
            eligible.append((path, rows))
    eligible.sort(key=lambda item: (-item[1], item[0].name))
    if len(eligible) < size:
        raise RuntimeError(f"只有 {len(eligible)} 个标的达到 {minimum_rows} 行")
    return eligible[:size]


def load_frames(
    selected: list[tuple[Path, int]], lookback_sessions: int
) -> tuple[dict[str, pd.DataFrame], list[dict], list[dict], dict[int, pd.Timestamp]]:
    raw_frames: dict[str, pd.DataFrame] = {}
    quality_rows = []
    common_sessions: set[int] | None = None
    for path, rows in selected:
        symbol = path.stem.split("_", 1)[0]
        frame = pd.read_parquet(path).tail(lookback_sessions + 160).reset_index(drop=True)
        quality = assess_universe_frame_quality(frame)
        quality_rows.append({"symbol": symbol, "path": path.as_posix(), **quality})
        if not quality["passed"]:
            continue
        raw_frames[symbol] = frame
        sessions = {int(value) for value in frame["time"].tail(lookback_sessions)}
        common_sessions = sessions if common_sessions is None else common_sessions & sessions
    if not common_sessions or len(common_sessions) < 500:
        raise RuntimeError(f"共同 ordinal session 只有 {len(common_sessions or [])} 个，低于 500")
    ordered_sessions = sorted(common_sessions)[-lookback_sessions:]
    session_dates = pd.bdate_range("2000-01-03", periods=len(ordered_sessions))
    session_map = dict(zip(ordered_sessions, session_dates, strict=True))
    frames: dict[str, pd.DataFrame] = {}
    members = []
    for symbol, raw in raw_frames.items():
        frame = raw.loc[raw["time"].isin(session_map)].copy()
        frame["datetime"] = frame["time"].map(session_map)
        reasons = a_share_tradability_reasons(frame)
        frame.loc[reasons.map(bool), ["open", "high", "low", "close", "tick_volume"]] = pd.NA
        frame = frame.rename(columns={"tick_volume": "volume"})
        frames[symbol] = frame[["datetime", "open", "high", "low", "close", "volume"]]
        members.append(
            {
                "symbol": symbol,
                "effective_from": session_dates[0].date().isoformat(),
                "effective_to": None,
                "status": "active",
                "industry": "",
                "market_cap": None,
                "beta": None,
                "is_st": False,
                "listed_at": session_dates[0].date().isoformat(),
                "delisted_at": None,
                "time_basis": "ordinal_session_mapped_for_cross_section_alignment",
                "source_first_session": min(session_map),
                "source_last_session": max(session_map),
            }
        )
    return frames, members, quality_rows, session_map


def build_all_factor_panels(
    frames: dict[str, pd.DataFrame], horizon: int
) -> dict[str, pd.DataFrame]:
    parts: dict[str, list[pd.DataFrame]] = {key: [] for key in FACTOR_META}
    for symbol, frame in frames.items():
        data = _clean_frame(frame)
        factors = _factor_series(data)
        close = data["close"]
        volume = data.get("volume", pd.Series(float("nan"), index=data.index))
        daily_volatility = close.pct_change().rolling(20, min_periods=10).std(ddof=0)
        labels: dict[str, pd.Series] = {}
        for label_horizon in LABEL_HORIZONS:
            forward = close.shift(-label_horizon).div(close).sub(1)
            labels[f"forward_return_{label_horizon}"] = forward
            labels[f"risk_adjusted_return_{label_horizon}"] = forward.div(
                daily_volatility.mul(math.sqrt(label_horizon)).replace(0, float("nan"))
            )
        common = {
            "datetime": pd.to_datetime(data["datetime"], errors="coerce"),
            "symbol": symbol,
            "forward_return": close.shift(-horizon).div(close).sub(1),
            "next_return": close.shift(-1).div(close).sub(1),
            "dollar_volume": close.mul(volume),
            **labels,
        }
        for factor_key, factor in factors.items():
            parts[factor_key].append(pd.DataFrame({**common, "factor": factor}))
    return {
        factor_key: pd.concat(rows, ignore_index=True).dropna(subset=["datetime"])
        for factor_key, rows in parts.items()
    }


def run(root: Path, output: Path, size: int, minimum_rows: int, lookback_sessions: int) -> dict:
    selected = select_files(root, size, minimum_rows)
    frames, members, quality_rows, session_map = load_frames(selected, lookback_sessions)
    file_manifest = [
        {
            "symbol": path.stem.split("_", 1)[0],
            "path": path.as_posix(),
            "rows": rows,
            "sha256": fingerprint_file(path),
        }
        for path, rows in selected
    ]
    snapshots = build_snapshot_fingerprints(
        universe_members=members,
        market_files=file_manifest,
        exposures=[],
    )
    factor_results = []
    failed = []
    panels = build_all_factor_panels(frames, horizon=5)
    for factor_key in FACTOR_META:
        try:
            result = analyze_cross_sectional_panel(
                panels[factor_key],
                members,
                CrossSectionConfig(
                    market="a_shares",
                    factor_key=factor_key,
                    horizon=5,
                    quantiles=5,
                    min_assets=max(30, int(size * 0.6)),
                    minimum_valid_assets=max(30, int(size * 0.6)),
                    minimum_effective_dates=120,
                    neutralize_industry=False,
                    neutralize_market_cap=False,
                    neutralize_beta=False,
                ),
            )
            factor_results.append(
                {
                    "factor": result["factor"],
                    "summary": result["summary"],
                    "stability": result["stability"],
                    "methodology": result["methodology"],
                }
            )
        except Exception as exc:  # noqa: BLE001 - every failed preregistered factor is evidence
            failed.append({"factor_key": factor_key, "error": str(exc)})
    artifact = {
        "artifact_version": "a-share-real-ordinal-baseline-v1",
        "generated_from": root.as_posix(),
        "market": "a_shares",
        "universe_size": len(frames),
        "requested_universe_size": size,
        "minimum_source_rows": minimum_rows,
        "common_sessions": len(session_map),
        "time_basis": "real_market_ordinal_sessions_without_claimed_calendar_dates",
        "calendar_date_evidence_available": False,
        "neutralization": {
            "industry": False,
            "market_cap": False,
            "beta": False,
            "reason": "本地源没有时点行业、市值与 Beta 暴露，禁止用当前静态值回填",
        },
        "quality": {
            "passed_symbols": sum(item["passed"] for item in quality_rows),
            "failed_symbols": sum(not item["passed"] for item in quality_rows),
            "rows": quality_rows,
        },
        "snapshots": snapshots,
        "factor_results": factor_results,
        "failed_factors": failed,
        "file_manifest": file_manifest,
    }
    artifact["artifact_sha256"] = fingerprint_payload(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/parquet/stocks"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("demo_artifacts/a_share_300_factor_baseline.json"),
    )
    parser.add_argument("--size", type=int, default=300)
    parser.add_argument("--minimum-rows", type=int, default=1250)
    parser.add_argument("--lookback-sessions", type=int, default=750)
    args = parser.parse_args()
    artifact = run(
        args.root,
        args.output,
        args.size,
        args.minimum_rows,
        args.lookback_sessions,
    )
    print(
        json.dumps(
            {
                "output": args.output.as_posix(),
                "universe_size": artifact["universe_size"],
                "common_sessions": artifact["common_sessions"],
                "factors": len(artifact["factor_results"]),
                "failed_factors": len(artifact["failed_factors"]),
                "artifact_sha256": artifact["artifact_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TARGET_MARKET_UNIVERSE_PROFILES: dict[str, dict[str, Any]] = {
    "a_shares": {
        "membership": "historical_constituents_and_listing_status",
        "time_basis": "exchange_session",
        "long_only": True,
        "lot_size": 100,
        "settlement": "T+1",
        "suspension_filter": True,
        "price_limit_filter": True,
    },
    "us_stocks": {
        "membership": "historical_exchange_or_index_constituents",
        "time_basis": "exchange_timestamp_america_new_york",
        "long_only": False,
        "lot_size": 1,
        "settlement": "T+1",
        "suspension_filter": True,
        "price_limit_filter": False,
    },
    "crypto": {
        "membership": "historical_listed_spot_or_perpetual_contracts",
        "time_basis": "utc_continuous",
        "long_only": False,
        "lot_size": None,
        "settlement": "continuous",
        "suspension_filter": True,
        "price_limit_filter": False,
    },
    "mt5": {
        "membership": "broker_contract_catalog_by_effective_period",
        "time_basis": "broker_server_timestamp",
        "long_only": False,
        "lot_size": None,
        "settlement": "broker_contract",
        "suspension_filter": True,
        "price_limit_filter": False,
    },
}


def validate_point_in_time_fields(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required = {
        "field",
        "event_time",
        "available_time",
        "source",
        "captured_at",
        "adjustment",
        "revision",
    }
    violations: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        missing = sorted(required - set(row))
        if missing:
            violations.append({"row": index, "reason": "missing_fields", "fields": missing})
            continue
        if row["available_time"] < row["event_time"]:
            violations.append({"row": index, "reason": "available_before_event"})
        if not str(row["source"]).strip() or not str(row["revision"]).strip():
            violations.append({"row": index, "reason": "source_or_revision_missing"})
    return {
        "passed": not violations,
        "rows": len(rows),
        "violations": violations,
        "future_information_blocked": any(
            item["reason"] == "available_before_event" for item in violations
        ),
        "contract_version": "point-in-time-field-v1",
    }


def assess_universe_frame_quality(frame: pd.DataFrame) -> dict[str, Any]:
    required = ["time", "open", "high", "low", "close", "tick_volume"]
    missing_columns = [column for column in required if column not in frame]
    if missing_columns:
        return {
            "passed": False,
            "missing_columns": missing_columns,
            "rows": len(frame),
            "duplicate_times": 0,
            "missing_values": 0,
            "invalid_ohlc_rows": len(frame),
            "abnormal_jump_rows": 0,
            "time_order_violations": 0,
        }
    numeric = frame[required].replace([np.inf, -np.inf], np.nan)
    close_returns = pd.to_numeric(numeric["close"], errors="coerce").pct_change()
    invalid_ohlc = (
        numeric[["open", "high", "low", "close"]].le(0).any(axis=1)
        | numeric["high"].lt(numeric[["open", "close", "low"]].max(axis=1))
        | numeric["low"].gt(numeric[["open", "close", "high"]].min(axis=1))
    )
    report = {
        "rows": len(frame),
        "missing_columns": [],
        "duplicate_times": int(frame["time"].duplicated().sum()),
        "missing_values": int(numeric.isna().sum().sum()),
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "abnormal_jump_rows": int(close_returns.abs().gt(0.35).sum()),
        "time_order_violations": int(pd.Series(frame["time"]).diff().le(0).sum()),
    }
    report["passed"] = not any(
        report[key]
        for key in (
            "duplicate_times",
            "missing_values",
            "invalid_ohlc_rows",
            "time_order_violations",
        )
    )
    return report


def a_share_tradability_reasons(
    frame: pd.DataFrame,
    *,
    is_st: bool = False,
    listing_age_sessions: int | None = None,
    minimum_listing_sessions: int = 60,
    minimum_volume: float = 1.0,
) -> pd.Series:
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["tick_volume"], errors="coerce")
    change = close.pct_change()
    reasons: list[list[str]] = []
    for index in range(len(frame)):
        row_reasons: list[str] = []
        if is_st:
            row_reasons.append("st")
        if (
            listing_age_sessions is not None
            and listing_age_sessions + index < minimum_listing_sessions
        ):
            row_reasons.append("insufficient_listing_age")
        if pd.isna(volume.iloc[index]) or float(volume.iloc[index]) < minimum_volume:
            row_reasons.append("suspended_or_no_volume")
        if pd.notna(change.iloc[index]) and abs(float(change.iloc[index])) >= 0.095:
            row_reasons.append("price_limit")
        reasons.append(row_reasons)
    return pd.Series(reasons, index=frame.index, dtype=object)


def restore_members_on_session(
    members: list[dict[str, Any]], session_id: int
) -> list[dict[str, Any]]:
    restored = []
    for member in members:
        if int(member["effective_from_session"]) > session_id:
            continue
        effective_to = member.get("effective_to_session")
        if effective_to is not None and int(effective_to) < session_id:
            continue
        if member.get("status") not in {"active", "suspended", "st"}:
            continue
        restored.append(member)
    return restored


def fingerprint_payload(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def fingerprint_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot_fingerprints(
    *,
    universe_members: list[dict[str, Any]],
    market_files: list[dict[str, Any]],
    exposures: list[dict[str, Any]],
) -> dict[str, str]:
    universe_hash = fingerprint_payload(universe_members)
    market_hash = fingerprint_payload(market_files)
    exposure_hash = fingerprint_payload(exposures)
    return {
        "universe_snapshot_sha256": universe_hash,
        "market_snapshot_sha256": market_hash,
        "exposure_snapshot_sha256": exposure_hash,
        "combined_snapshot_sha256": fingerprint_payload(
            {"universe": universe_hash, "market": market_hash, "exposure": exposure_hash}
        ),
    }

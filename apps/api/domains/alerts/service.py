from __future__ import annotations

import json
import math
import threading
import time
import uuid
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

from apps.api import store

_TIMEZONE = ZoneInfo("Asia/Shanghai")
_STOP_EVENT = threading.Event()
_MONITOR_THREAD: threading.Thread | None = None


def _rule_dict(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "rule_type": row["rule_type"],
        "symbol": row["symbol"],
        "market": row["market"],
        "threshold": row["threshold"],
        "enabled": bool(row["enabled"]),
        "frequency_minutes": int(row["frequency_minutes"]),
        "quiet_start": row["quiet_start"],
        "quiet_end": row["quiet_end"],
        "expires_at": row["expires_at"],
        "context": json.loads(row["context_json"] or "{}"),
        "last_checked_at": row["last_checked_at"],
        "last_triggered_at": row["last_triggered_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _event_dict(row) -> dict:
    try:
        related_modules_json = row["related_modules_json"]
    except (IndexError, KeyError):
        related_modules_json = None
    related_modules = json.loads(related_modules_json or "[]")
    return {
        "id": row["id"],
        "rule_id": row["rule_id"],
        "status": row["status"],
        "message": row["message"],
        "observed_value": row["observed_value"],
        "related_type": row["related_type"],
        "related_id": row["related_id"],
        "related_modules": related_modules,
        "delivery": json.loads(row["delivery_json"] or "{}"),
        "triggered_at": row["triggered_at"],
        "acknowledged_at": row["acknowledged_at"],
        "rule_name": row["rule_name"],
        "symbol": row["rule_symbol"],
        "market": row["rule_market"],
    }


def list_rules(user_id: str) -> dict:
    with store._lock, store._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM alert_rules WHERE user_id=? ORDER BY created_at DESC, id DESC",
            (user_id,),
        ).fetchall()
    items = [_rule_dict(row) for row in rows]
    return {"ok": True, "count": len(items), "rules": items}


def create_rule(user_id: str, payload: dict[str, Any]) -> dict:
    now = time.time()
    rule_id = f"ALERT-{uuid.uuid4().hex[:12].upper()}"
    with store._lock, store._conn() as connection:
        connection.execute(
            """INSERT INTO alert_rules
               (id, user_id, name, rule_type, symbol, market, threshold, enabled,
                frequency_minutes, quiet_start, quiet_end, expires_at, context_json,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule_id,
                user_id,
                payload["name"],
                payload["rule_type"],
                payload["symbol"],
                payload["market"],
                payload.get("threshold"),
                int(payload.get("enabled", True)),
                payload.get("frequency_minutes", 15),
                payload.get("quiet_start"),
                payload.get("quiet_end"),
                payload.get("expires_at"),
                json.dumps(payload.get("context", {}), ensure_ascii=False),
                now,
                now,
            ),
        )
        row = connection.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
    return _rule_dict(row)


def update_rule(rule_id: str, user_id: str, patch: dict[str, Any]) -> dict | None:
    allowed = {
        "name",
        "enabled",
        "threshold",
        "frequency_minutes",
        "quiet_start",
        "quiet_end",
        "expires_at",
    }
    values = {key: value for key, value in patch.items() if key in allowed}
    if not values:
        return get_rule(rule_id, user_id)
    assignments = ", ".join(f"{key}=?" for key in values)
    with store._lock, store._conn() as connection:
        result = connection.execute(
            f"UPDATE alert_rules SET {assignments}, updated_at=? WHERE id=? AND user_id=?",
            (*values.values(), time.time(), rule_id, user_id),
        )
        if result.rowcount == 0:
            return None
        row = connection.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
    return _rule_dict(row)


def get_rule(rule_id: str, user_id: str | None = None) -> dict | None:
    sql = "SELECT * FROM alert_rules WHERE id=?"
    params: list[Any] = [rule_id]
    if user_id is not None:
        sql += " AND user_id=?"
        params.append(user_id)
    with store._lock, store._conn() as connection:
        row = connection.execute(sql, params).fetchone()
    return _rule_dict(row) if row else None


def delete_rule(rule_id: str, user_id: str) -> bool:
    with store._lock, store._conn() as connection:
        result = connection.execute(
            "DELETE FROM alert_rules WHERE id=? AND user_id=?", (rule_id, user_id)
        )
    return result.rowcount > 0


def list_events(user_id: str, *, pending_only: bool = False, limit: int = 200) -> dict:
    sql = """SELECT e.*, r.name AS rule_name, r.symbol AS rule_symbol,
                    r.market AS rule_market, rr.modules_json AS related_modules_json
             FROM alert_events e JOIN alert_rules r ON r.id=e.rule_id
             LEFT JOIN research_runs rr ON e.related_type='research_run' AND rr.id=e.related_id
             WHERE r.user_id=?"""
    params: list[Any] = [user_id]
    if pending_only:
        sql += " AND e.status='pending'"
    sql += " ORDER BY e.triggered_at DESC, e.id DESC LIMIT ?"
    params.append(limit)
    with store._lock, store._conn() as connection:
        rows = connection.execute(sql, params).fetchall()
    items = [_event_dict(row) for row in rows]
    return {"ok": True, "count": len(items), "events": items}


def acknowledge_event(event_id: str, user_id: str) -> dict | None:
    now = time.time()
    with store._lock, store._conn() as connection:
        result = connection.execute(
            """UPDATE alert_events SET status='acknowledged', acknowledged_at=?
               WHERE id=? AND rule_id IN (SELECT id FROM alert_rules WHERE user_id=?)""",
            (now, event_id, user_id),
        )
        if result.rowcount == 0:
            return None
        row = connection.execute(
            """SELECT e.*, r.name AS rule_name, r.symbol AS rule_symbol,
                      r.market AS rule_market, rr.modules_json AS related_modules_json
               FROM alert_events e JOIN alert_rules r ON r.id=e.rule_id
               LEFT JOIN research_runs rr ON e.related_type='research_run' AND rr.id=e.related_id
               WHERE e.id=?""",
            (event_id,),
        ).fetchone()
    return _event_dict(row)


def _in_quiet_period(rule: dict, now: float) -> bool:
    if not rule["quiet_start"] or not rule["quiet_end"]:
        return False
    current = datetime.fromtimestamp(now, _TIMEZONE).strftime("%H:%M")
    start, end = rule["quiet_start"], rule["quiet_end"]
    return start <= current < end if start < end else current >= start or current < end


def _quote_observation(rule: dict) -> tuple[float | None, float | None]:
    from apps.api.domains.portfolio.service import quote_item

    quote = quote_item(rule["symbol"], rule["market"])
    price = quote.get("price")
    change = quote.get("chgPct")
    return (
        float(price) if isinstance(price, (int, float)) else None,
        float(change) if isinstance(change, (int, float)) else None,
    )


def _volatility(rule: dict) -> float | None:
    from apps.api.domains.market.service import fetch_kline

    result = fetch_kline(rule["symbol"], rule["market"], "1d", 21)
    closes = [
        float(item["c"])
        for item in result.get("candles", [])
        if isinstance(item.get("c"), (int, float))
    ]
    if len(closes) < 2:
        return None
    returns = [(current / previous - 1) * 100 for previous, current in pairwise(closes) if previous]
    if not returns:
        return None
    mean = sum(returns) / len(returns)
    return math.sqrt(sum((item - mean) ** 2 for item in returns) / len(returns))


def _latest_signal(rule: dict) -> tuple[bool, float | None, str | None]:
    checked = float(rule["last_checked_at"] or rule["created_at"])
    with store._lock, store._conn() as connection:
        row = connection.execute(
            """SELECT id, ts_epoch FROM signals
               WHERE symbol=? AND market=? AND ts_epoch>? ORDER BY ts_epoch DESC, id DESC LIMIT 1""",
            (rule["symbol"], rule["market"], checked),
        ).fetchone()
    return (row is not None, None, row["id"] if row else None)


def _evaluation_change(rule: dict) -> tuple[bool, str | None]:
    with store._lock, store._conn() as connection:
        rows = connection.execute(
            """SELECT id, summary_json FROM research_runs
               WHERE symbol=? AND market=? AND owner_id=?
                 AND status IN ('succeeded','partial')
               ORDER BY updated_at DESC, id DESC LIMIT 2""",
            (rule["symbol"], rule["market"], rule["user_id"]),
        ).fetchall()
    if not rows:
        return False, None
    latest_summary = json.loads(rows[0]["summary_json"] or "{}")
    latest_direction = latest_summary.get("research_decision", {}).get(
        "direction"
    ) or latest_summary.get("ensemble", {}).get("consensus", {}).get("direction")
    previous_direction = rule["context"].get("last_direction")
    rule["context"]["last_direction"] = latest_direction
    changed = (
        previous_direction is not None
        and latest_direction is not None
        and previous_direction != latest_direction
    )
    return changed, rows[0]["id"] if changed else None


def _latest_factor_snapshot(rule: dict) -> tuple[dict | None, dict | None]:
    symbol = rule["symbol"]
    universe_id = rule.get("context", {}).get("universe_id")
    if isinstance(universe_id, str) and universe_id:
        symbol = f"UNIVERSE:{universe_id}"
    with store._lock, store._conn() as connection:
        row = connection.execute(
            """SELECT id FROM research_runs
               WHERE symbol=? AND market=? AND owner_id=?
                 AND status IN ('succeeded','partial')
                 AND EXISTS (
                   SELECT 1 FROM json_each(research_runs.modules_json)
                   WHERE value IN ('factor_research', 'cross_sectional_factor_research')
                 )
               ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (symbol, rule["market"], rule["user_id"]),
        ).fetchone()
    if row is None:
        return None, None
    run = store.get_research_run(row["id"])
    result = next(
        (
            item.get("payload")
            for item in reversed(run.get("evidence", []))
            if item.get("kind") == "factor_research_result"
        ),
        None,
    )
    if isinstance(result, dict):
        return run, result
    cross_result = next(
        (
            item.get("payload")
            for item in reversed(run.get("evidence", []))
            if item.get("kind") == "cross_sectional_factor_result"
        ),
        None,
    )
    if isinstance(cross_result, dict) and isinstance(cross_result.get("factor"), dict):
        # 归一化为因子提醒的只读快照；横截面结果没有回撤字段，相关规则自然不触发。
        return run, {"factors": [cross_result["factor"]]}
    return run, result


def _factor_condition(rule: dict) -> tuple[bool, float | None, str | None, str | None]:
    run, result = _latest_factor_snapshot(rule)
    if run is None or not isinstance(result, dict):
        return False, None, None, None
    factor_key = rule["context"]["factor_key"]
    factor = next(
        (item for item in result.get("factors", []) if item.get("key") == factor_key),
        None,
    )
    if factor is None:
        return False, None, "research_run", run["id"]
    rule_type = rule["rule_type"]
    if rule_type == "factor_status_changed":
        current_status = factor.get("status")
        previous_status = rule["context"].get("last_factor_status")
        rule["context"]["last_factor_status"] = current_status
        return (
            previous_status is not None and current_status != previous_status,
            None,
            "research_run",
            run["id"],
        )
    if rule_type == "factor_ic_decay":
        current_ic = factor.get("test_ic")
        baseline = rule["context"]["baseline_test_ic"]
        if not isinstance(current_ic, (int, float)):
            return False, None, "research_run", run["id"]
        return (
            float(baseline) - float(current_ic) >= float(rule["threshold"]),
            float(current_ic),
            "research_run",
            run["id"],
        )
    if rule_type == "factor_drawdown_breach":
        drawdown = result.get("current_signal", {}).get("strategy_drawdown")
        if not isinstance(drawdown, (int, float)):
            return False, None, "research_run", run["id"]
        return (
            float(drawdown) <= -abs(float(rule["threshold"])),
            float(drawdown),
            "research_run",
            run["id"],
        )
    age_hours = max(0.0, (time.time() - float(run["updated_at"])) / 3600)
    return (
        age_hours >= float(rule["threshold"]),
        round(age_hours, 4),
        "research_run",
        run["id"],
    )


def _instrument_id(rule: dict) -> str | None:
    with store._lock, store._conn() as connection:
        row = connection.execute(
            """SELECT instrument_id FROM research_runs
               WHERE symbol=? AND market=? AND owner_id=? AND instrument_id IS NOT NULL
               ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (rule["symbol"], rule["market"], rule["user_id"]),
        ).fetchone()
    return str(row["instrument_id"]) if row else None


def _earnings_release(rule: dict) -> tuple[bool, float | None, str | None, str | None]:
    instrument_id = _instrument_id(rule)
    if instrument_id is None:
        return False, None, None, None
    checked = float(rule["last_checked_at"] or rule["created_at"])
    now = time.time()
    with store._lock, store._conn() as connection:
        row = connection.execute(
            """SELECT statement_id, available_at FROM financial_statements
               WHERE instrument_id=? AND available_at>? AND available_at<=?
               ORDER BY available_at DESC, statement_id DESC LIMIT 1""",
            (instrument_id, checked, now),
        ).fetchone()
    return (
        row is not None,
        float(row["available_at"]) if row else None,
        "financial_statement" if row else None,
        str(row["statement_id"]) if row else None,
    )


def _valuation_band(rule: dict) -> tuple[bool, float | None, str | None, str | None]:
    instrument_id = _instrument_id(rule)
    if instrument_id is None:
        return False, None, None, None
    snapshots = store.list_valuation_snapshots(
        instrument_id,
        as_of=datetime.now(UTC),
        limit=1,
    )
    if not snapshots:
        return False, None, None, None
    snapshot = snapshots[0]
    metric_key = str(rule["context"].get("metric") or "pe_ttm")
    metric = next(
        (item for item in snapshot.get("metrics", []) if item.get("key") == metric_key),
        None,
    )
    if not isinstance(metric, dict):
        return False, None, "valuation_snapshot", str(snapshot.get("snapshot_id") or "")
    percentile = metric.get("historical_percentile")
    if not isinstance(percentile, (int, float)):
        return False, None, "valuation_snapshot", str(snapshot.get("snapshot_id") or "")
    current = float(percentile)
    threshold = float(rule["threshold"])
    if threshold > 1:
        threshold /= 100
    previous = rule["context"].get("last_percentile")
    rule["context"]["last_percentile"] = current
    crossed = isinstance(previous, (int, float)) and (
        (float(previous) < threshold <= current) or (float(previous) > threshold >= current)
    )
    return crossed, current, "valuation_snapshot", str(snapshot.get("snapshot_id") or "")


def _major_company_event(rule: dict) -> tuple[bool, float | None, str | None, str | None]:
    instrument_id = _instrument_id(rule)
    if instrument_id is None:
        return False, None, None, None
    checked = float(rule["last_checked_at"] or rule["created_at"])
    now = time.time()
    with store._lock, store._conn() as connection:
        rows = connection.execute(
            """SELECT event_id, available_at, payload_json FROM company_events
               WHERE instrument_id=? AND available_at>? AND available_at<=?
               ORDER BY available_at DESC, event_id DESC LIMIT 20""",
            (instrument_id, checked, now),
        ).fetchall()
    row = next(
        (
            item
            for item in rows
            if (payload := json.loads(item["payload_json"] or "{}"))
            and payload.get("importance") in {"high", "critical"}
            and payload.get("verification_status") in {"verified", "corroborated"}
            and payload.get("repost_of") is None
        ),
        None,
    )
    return (
        row is not None,
        float(row["available_at"]) if row else None,
        "company_event" if row else None,
        str(row["event_id"]) if row else None,
    )


def _macro_calendar(rule: dict) -> tuple[bool, float | None, str | None, str | None]:
    checked = float(rule["last_checked_at"] or rule["created_at"])
    now = time.time()
    horizon = now + max(1, int(rule["context"].get("lead_hours", 72))) * 3600
    with store._lock, store._conn() as connection:
        rows = connection.execute(
            """SELECT event_id, event_at, available_at, payload_json FROM macro_events
               WHERE available_at<=? AND (available_at>? OR event_at BETWEEN ? AND ?)
               ORDER BY COALESCE(event_at, available_at), event_id LIMIT 50""",
            (now, checked, now, horizon),
        ).fetchall()
    seen = set(rule["context"].get("seen_event_ids") or [])
    row = next((item for item in rows if str(item["event_id"]) not in seen), None)
    if row is None:
        return False, None, None, None
    event_id = str(row["event_id"])
    rule["context"]["seen_event_ids"] = [*list(seen)[-99:], event_id]
    event_at = row["event_at"] if row["event_at"] is not None else row["available_at"]
    return True, float(event_at), "macro_event", event_id


def _condition(rule: dict) -> tuple[bool, float | None, str | None, str | None]:
    rule_type = rule["rule_type"]
    threshold = rule["threshold"]
    if rule_type in {
        "price_above",
        "price_below",
        "change_pct_above",
        "change_pct_below",
        "risk_invalidated",
    }:
        price, change = _quote_observation(rule)
        if rule_type == "price_above":
            return price is not None and price >= threshold, price, "instrument", rule["symbol"]
        if rule_type == "price_below":
            return price is not None and price <= threshold, price, "instrument", rule["symbol"]
        if rule_type == "change_pct_above":
            return change is not None and change >= threshold, change, "instrument", rule["symbol"]
        if rule_type == "change_pct_below":
            return change is not None and change <= threshold, change, "instrument", rule["symbol"]
        condition = rule["context"].get("condition")
        triggered = price is not None and (
            (condition == "above" and price >= threshold)
            or (condition == "below" and price <= threshold)
        )
        return triggered, price, "research_run", rule["context"].get("research_run_id")
    if rule_type == "volatility_above":
        value = _volatility(rule)
        return value is not None and value >= threshold, value, "instrument", rule["symbol"]
    if rule_type == "signal_created":
        triggered, value, related_id = _latest_signal(rule)
        return triggered, value, "signal", related_id
    if rule_type == "evaluation_changed":
        triggered, related_id = _evaluation_change(rule)
        return triggered, None, "research_run", related_id
    if rule_type == "earnings_released":
        return _earnings_release(rule)
    if rule_type == "valuation_band_crossed":
        return _valuation_band(rule)
    if rule_type == "major_company_event":
        return _major_company_event(rule)
    if rule_type == "macro_calendar":
        return _macro_calendar(rule)
    if rule_type in {
        "factor_status_changed",
        "factor_ic_decay",
        "factor_drawdown_breach",
        "factor_data_stale",
    }:
        return _factor_condition(rule)
    return False, None, None, None


def _save_check(rule: dict, now: float, triggered: bool) -> None:
    with store._lock, store._conn() as connection:
        connection.execute(
            """UPDATE alert_rules SET context_json=?, last_checked_at=?,
               last_triggered_at=CASE WHEN ? THEN ? ELSE last_triggered_at END,
               updated_at=? WHERE id=?""",
            (
                json.dumps(rule["context"], ensure_ascii=False),
                now,
                int(triggered),
                now,
                now,
                rule["id"],
            ),
        )


def _create_event(
    rule: dict, value: float | None, related_type: str | None, related_id: str | None, now: float
) -> dict:
    from core.alert import AlertMessage, get_notifier

    message = f"{rule['name']}：{rule['symbol']} 已满足 {rule['rule_type']}"
    delivery = get_notifier().send(
        AlertMessage(
            title=rule["name"],
            content=message,
            level="warning",
            source="alert_center",
            tags=[rule["symbol"]],
        )
    )
    event_id = f"EVENT-{uuid.uuid4().hex[:12].upper()}"
    with store._lock, store._conn() as connection:
        connection.execute(
            """INSERT INTO alert_events
               (id, rule_id, status, message, observed_value, related_type, related_id,
                delivery_json, triggered_at) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                rule["id"],
                message,
                value,
                related_type,
                related_id,
                json.dumps(delivery),
                now,
            ),
        )
        row = connection.execute(
            """SELECT e.*, r.name AS rule_name, r.symbol AS rule_symbol,
                      r.market AS rule_market, rr.modules_json AS related_modules_json
               FROM alert_events e JOIN alert_rules r ON r.id=e.rule_id
               LEFT JOIN research_runs rr ON e.related_type='research_run' AND rr.id=e.related_id
               WHERE e.id=?""",
            (event_id,),
        ).fetchone()
    return _event_dict(row)


def check_rule(rule: dict, *, force: bool = False) -> dict:
    now = time.time()
    if not rule["enabled"] or (rule["expires_at"] is not None and rule["expires_at"] <= now):
        return {"ok": True, "checked": False, "triggered": False, "event": None}
    if (
        not force
        and rule["last_checked_at"] is not None
        and now - rule["last_checked_at"] < rule["frequency_minutes"] * 60
    ):
        return {"ok": True, "checked": False, "triggered": False, "event": None}
    triggered, value, related_type, related_id = _condition(rule)
    quiet = _in_quiet_period(rule, now)
    _save_check(rule, now, triggered)
    event = (
        _create_event(rule, value, related_type, related_id, now)
        if triggered and not quiet
        else None
    )
    return {"ok": True, "checked": True, "triggered": bool(event), "quiet": quiet, "event": event}


def check_all_rules(*, force: bool = False) -> dict:
    with store._lock, store._conn() as connection:
        rows = connection.execute("SELECT * FROM alert_rules WHERE enabled=1").fetchall()
    results = []
    for row in rows:
        rule = _rule_dict(row)
        try:
            results.append({"rule_id": rule["id"], **check_rule(rule, force=force)})
        except Exception as exc:  # noqa: BLE001 - isolate failures between independent rules
            results.append({"rule_id": rule["id"], "ok": False, "error": str(exc)})
    return {
        "ok": all(item.get("ok") for item in results),
        "count": len(results),
        "results": results,
    }


def _monitor_loop() -> None:
    while not _STOP_EVENT.wait(60):
        check_all_rules()


def start_monitor() -> None:
    global _MONITOR_THREAD
    if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
        return
    _STOP_EVENT.clear()
    _MONITOR_THREAD = threading.Thread(
        target=_monitor_loop, name="quanthub-alert-monitor", daemon=True
    )
    _MONITOR_THREAD.start()


def stop_monitor() -> None:
    _STOP_EVENT.set()
    if _MONITOR_THREAD is not None:
        _MONITOR_THREAD.join(timeout=2)

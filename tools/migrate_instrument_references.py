"""Instrument 引用核查、回填与主数据合并工具。"""

from __future__ import annotations

import argparse
import json

from apps.api import store
from apps.api.domains.instrument import service as instrument_service

REFERENCE_TABLES = (
    ("holdings", "code", "market"),
    ("watchlist", "sym", "market"),
    ("research_runs", "symbol", "market"),
    ("signals", "symbol", "market"),
    ("experiments", "symbol", "market"),
    ("simulation_orders", "symbol", "market"),
    ("ledger_trades", "code", "market"),
    ("ledger_positions", "code", "market"),
)


def audit_references(*, apply: bool = False) -> dict:
    changes: list[dict] = []
    errors: list[dict] = []
    records: list[dict] = []
    with store._lock, store._conn() as connection:
        for table, code_column, market_column in REFERENCE_TABLES:
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "instrument_id" not in columns:
                errors.append({"table": table, "error": "缺少 instrument_id 列"})
                continue
            rows = connection.execute(
                f"SELECT rowid, instrument_id, {code_column} AS code, {market_column} AS market FROM {table}"
            ).fetchall()
            for row in rows:
                records.append(
                    {
                        "table": table,
                        "rowid": row["rowid"],
                        "instrument_id": row["instrument_id"],
                        "code": row["code"],
                        "market": row["market"],
                    }
                )
    for row in records:
        try:
            instrument = instrument_service.resolve_strict(row["code"], row["market"])
        except instrument_service.InstrumentResolutionError as exc:
            errors.append({"table": row["table"], "rowid": row["rowid"], "error": str(exc)})
            continue
        if row["instrument_id"] == instrument.instrument_id:
            continue
        changes.append(
            {
                "table": row["table"],
                "rowid": row["rowid"],
                "before": row["instrument_id"],
                "after": instrument.instrument_id,
            }
        )
    if apply and changes:
        with store._lock, store._conn() as connection:
            for change in changes:
                connection.execute(
                    f"UPDATE {change['table']} SET instrument_id=? WHERE rowid=?",
                    (change["after"], change["rowid"]),
                )
    return {"ok": not errors, "apply": apply, "changes": changes, "errors": errors}


def merge_instruments(
    *,
    source_code: str,
    source_market: str,
    target_code: str,
    target_market: str,
    apply: bool = False,
) -> dict:
    source = instrument_service.resolve_strict(source_code, source_market)
    target = instrument_service.resolve_strict(target_code, target_market)
    updates: list[dict] = []
    with store._lock, store._conn() as connection:
        for table, code_column, market_column in REFERENCE_TABLES:
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "instrument_id" not in columns:
                continue
            count = connection.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE instrument_id=?",
                (source.instrument_id,),
            ).fetchone()["count"]
            if not count:
                continue
            updates.append({"table": table, "rows": count})
            if apply:
                connection.execute(
                    f"""UPDATE {table} SET instrument_id=?, {code_column}=?, {market_column}=?
                        WHERE instrument_id=?""",
                    (target.instrument_id, target.code, target.market, source.instrument_id),
                )
        if apply and source.instrument_id != target.instrument_id:
            connection.execute(
                "DELETE FROM instruments WHERE code=? AND market=?",
                (source.code, source.market),
            )
        if not apply:
            connection.rollback()
    return {
        "ok": True,
        "apply": apply,
        "source": source.to_dict(),
        "target": target.to_dict(),
        "updates": updates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="核查或迁移 Instrument 引用")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--apply", action="store_true")
    merge = subparsers.add_parser("merge")
    merge.add_argument("--source-code", required=True)
    merge.add_argument("--source-market", required=True)
    merge.add_argument("--target-code", required=True)
    merge.add_argument("--target-market", required=True)
    merge.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.command == "audit":
        result = audit_references(apply=args.apply)
    else:
        result = merge_instruments(
            source_code=args.source_code,
            source_market=args.source_market,
            target_code=args.target_code,
            target_market=args.target_market,
            apply=args.apply,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

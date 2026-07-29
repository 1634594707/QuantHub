from __future__ import annotations

import json
from urllib.parse import quote

from apps.api import store


def _path_segment(value: object) -> str:
    return quote(str(value), safe="")


def search(query: str, limit_per_group: int = 6) -> dict:
    normalized = query.strip()
    if not normalized:
        return {"ok": True, "query": normalized, "count": 0, "items": []}
    pattern = f"%{normalized}%"
    params = (pattern, pattern, pattern, pattern, pattern, pattern, limit_per_group)
    with store._lock, store._conn() as connection:
        instruments = connection.execute(
            """SELECT code, market, exchange, name, asset_class
               FROM instruments
               WHERE code LIKE ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE
                  OR market LIKE ? COLLATE NOCASE OR exchange LIKE ? COLLATE NOCASE
                  OR asset_class LIKE ? COLLATE NOCASE OR (market || ':' || code) LIKE ? COLLATE NOCASE
               ORDER BY ts DESC LIMIT ?""",
            params,
        ).fetchall()
        definitions = connection.execute(
            """SELECT id, name, strategy_key, market
               FROM strategy_definitions
               WHERE archived_at IS NULL AND (
                 id LIKE ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE
                 OR strategy_key LIKE ? COLLATE NOCASE OR market LIKE ? COLLATE NOCASE
                 OR description LIKE ? COLLATE NOCASE OR tags LIKE ? COLLATE NOCASE)
               ORDER BY updated_at DESC, id DESC LIMIT ?""",
            params,
        ).fetchall()
        experiments = connection.execute(
            """SELECT id, definition_id, symbol, market, timeframe, status
               FROM experiments
               WHERE archived_at IS NULL AND (
                 id LIKE ? COLLATE NOCASE OR definition_id LIKE ? COLLATE NOCASE
                 OR symbol LIKE ? COLLATE NOCASE OR market LIKE ? COLLATE NOCASE
                 OR timeframe LIKE ? COLLATE NOCASE OR note LIKE ? COLLATE NOCASE)
               ORDER BY COALESCE(updated_at, created_at) DESC, id DESC LIMIT ?""",
            params,
        ).fetchall()
        research_runs = connection.execute(
            """SELECT id, symbol, market, timeframe, status, modules_json
               FROM research_runs
               WHERE id LIKE ? COLLATE NOCASE OR symbol LIKE ? COLLATE NOCASE
                  OR market LIKE ? COLLATE NOCASE OR timeframe LIKE ? COLLATE NOCASE
                  OR status LIKE ? COLLATE NOCASE OR note LIKE ? COLLATE NOCASE
               ORDER BY updated_at DESC, id DESC LIMIT ?""",
            params,
        ).fetchall()
        signals = connection.execute(
            """SELECT id, symbol, market, timeframe, direction, status, source
               FROM signals
               WHERE id LIKE ? COLLATE NOCASE OR symbol LIKE ? COLLATE NOCASE
                  OR market LIKE ? COLLATE NOCASE OR timeframe LIKE ? COLLATE NOCASE
                  OR source LIKE ? COLLATE NOCASE OR tags_json LIKE ? COLLATE NOCASE
               ORDER BY ts_epoch DESC, id DESC LIMIT ?""",
            params,
        ).fetchall()
        orders = connection.execute(
            """SELECT id, signal_id, symbol, market, side, status, order_type
               FROM simulation_orders
               WHERE id LIKE ? COLLATE NOCASE OR COALESCE(signal_id, '') LIKE ? COLLATE NOCASE
                  OR symbol LIKE ? COLLATE NOCASE OR market LIKE ? COLLATE NOCASE
                  OR status LIKE ? COLLATE NOCASE OR order_type LIKE ? COLLATE NOCASE
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            params,
        ).fetchall()

    items: list[dict] = []
    items.extend(
        {
            "id": f"instrument:{row['market']}:{row['code']}",
            "group": "instruments",
            "marker": "标",
            "label": f"{row['code']} {row['name']}".strip(),
            "detail": f"{row['market']} · {row['exchange']} · {row['asset_class']}",
            "path": f"/research/{_path_segment(row['code'])}?market={_path_segment(row['market'])}&tf=1d",
        }
        for row in instruments
    )
    items.extend(
        {
            "id": f"definition:{row['id']}",
            "group": "definitions",
            "marker": "策",
            "label": row["name"],
            "detail": f"{row['strategy_key']} · {row['market']}",
            "path": f"/strategy-lab?definition_id={_path_segment(row['id'])}",
            "secondary_label": "创建实验",
            "secondary_path": f"/strategy-lab?definition_id={_path_segment(row['id'])}&action=create_experiment",
        }
        for row in definitions
    )
    items.extend(
        {
            "id": f"experiment:{row['id']}",
            "group": "experiments",
            "marker": "验",
            "label": f"{row['symbol']} · {row['timeframe']}",
            "detail": f"{row['status']} · {row['market']} · {str(row['id'])[:12]}",
            "path": f"/strategy-lab?definition_id={_path_segment(row['definition_id'])}&experiment_id={_path_segment(row['id'])}",
        }
        for row in experiments
    )
    for row in research_runs:
        modules = json.loads(row["modules_json"] or "[]")
        module_label = " + ".join(str(item) for item in modules) or "空白研究"
        items.append(
            {
                "id": f"research:{row['id']}",
                "group": "research",
                "marker": "研",
                "label": f"{row['symbol']} · {module_label}",
                "detail": f"{row['status']} · {row['timeframe']}",
                "path": f"/research/{_path_segment(row['symbol'])}?market={_path_segment(row['market'])}&tf={_path_segment(row['timeframe'])}&view=history&run_id={_path_segment(row['id'])}",
            }
        )
    items.extend(
        {
            "id": f"signal:{row['id']}",
            "group": "signals",
            "marker": "信",
            "label": f"{row['symbol']} · {row['direction']}",
            "detail": f"{row['status']} · {row['source']} · {row['timeframe']}",
            "path": f"/signals?signal_id={_path_segment(row['id'])}",
        }
        for row in signals
    )
    items.extend(
        {
            "id": f"order:{row['id']}",
            "group": "orders",
            "marker": "单",
            "label": f"{row['symbol']} · {row['side']}",
            "detail": f"{row['status']} · {row['order_type']} · {str(row['id'])[:12]}",
            "path": f"/simulation?order_id={_path_segment(row['id'])}",
        }
        for row in orders
    )
    return {"ok": True, "query": normalized, "count": len(items), "items": items}

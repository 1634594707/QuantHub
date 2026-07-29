from __future__ import annotations

from apps.api import store
from apps.api.domains.automation import repository as automation_repository
from apps.api.domains.market_data.service import check_data_source, data_source_status
from apps.api.domains.tasks import service as tasks_service

from . import repository
from .schemas import DataSourceIncidentCheck


def _analysis_incidents(limit: int) -> list[dict]:
    incidents = []
    for task in store.list_analysis_tasks(limit=limit):
        refreshed = tasks_service.refresh_timeout(task)
        if refreshed["status"] not in {"failed", "timeout"}:
            continue
        incidents.append(
            {
                "id": f"analysis:{refreshed['id']}",
                "source": "analysis_task",
                "entity_id": refreshed["id"],
                "status": refreshed["status"],
                "occurred_at": refreshed["finished_at"] or refreshed["updated_at"],
                "error": refreshed["error"] or "分析任务失败",
                "context": {
                    "kind": refreshed["kind"],
                    "symbol": refreshed["symbol"],
                    "market": refreshed["market"],
                    "attempt": refreshed["attempt"],
                },
                "actions": [
                    {
                        "type": "retry_analysis_task",
                        "task_id": refreshed["id"],
                        "label": "重试分析任务",
                    }
                ],
            }
        )
    return incidents


def _automation_incidents(limit: int) -> list[dict]:
    incidents = []
    for run in automation_repository.list_runs(status="failed", limit=limit):
        actions = [{"type": "retry_automation_run", "run_id": run["id"], "label": "重试自动化"}]
        if run["acknowledged_at"] is None:
            actions.append(
                {
                    "type": "acknowledge_automation_run",
                    "run_id": run["id"],
                    "label": "确认告警",
                }
            )
        incidents.append(
            {
                "id": f"automation:{run['id']}",
                "source": "automation_run",
                "entity_id": run["id"],
                "status": "acknowledged" if run["acknowledged_at"] else "failed",
                "occurred_at": run["finished_at"] or run["created_at"],
                "error": run["error"] or "自动化任务失败",
                "context": {"job_name": run["job_name"], "attempt": run["attempt"]},
                "actions": actions,
            }
        )
    return incidents


def _ledger_incidents(limit: int) -> list[dict]:
    incidents = []
    for order in store.list_simulation_orders(limit=10_000):
        for execution in order["executions"]:
            if execution["ledger_sync_status"] != "failed":
                continue
            incidents.append(
                {
                    "id": f"ledger:{order['id']}:{execution['id']}",
                    "source": "ledger_sync",
                    "entity_id": execution["id"],
                    "status": "failed",
                    "occurred_at": execution["executed_at"],
                    "error": execution["ledger_sync_error"] or "账本同步失败",
                    "context": {
                        "order_id": order["id"],
                        "symbol": order["symbol"],
                        "market": order["market"],
                    },
                    "actions": [
                        {
                            "type": "retry_ledger_sync",
                            "order_id": order["id"],
                            "execution_id": execution["id"],
                            "label": "重试账本同步",
                        }
                    ],
                }
            )
    return incidents[-limit:]


def _data_source_incidents() -> list[dict]:
    snapshot = data_source_status()
    incidents = []
    for source in snapshot["sources"]:
        if not source.get("last_error"):
            continue
        persisted = repository.observe_data_source_failure(
            source["source"],
            source["operation"],
            source["last_error"],
            source.get("last_called_at") or snapshot["generated_at"],
        )
        incidents.append(
            {
                "id": f"data_source:{persisted['id']}",
                "source": "data_source",
                "entity_id": persisted["id"],
                "status": "failed",
                "occurred_at": persisted["started_at"],
                "error": persisted["error"],
                "context": {
                    "source": source["source"],
                    "operation": source["operation"],
                    "calls": source["calls"],
                    "error_rate": source["error_rate"],
                },
                "actions": [
                    {
                        "type": "check_data_source",
                        "incident_id": persisted["id"],
                        "label": "在当前页检查",
                    }
                ],
            }
        )
    active_ids = {item["entity_id"] for item in incidents}
    for persisted in repository.list_data_source_incidents(include_acknowledged=False):
        if persisted["id"] in active_ids:
            continue
        actions = []
        if persisted["status"] == "open":
            actions.append(
                {
                    "type": "check_data_source",
                    "incident_id": persisted["id"],
                    "label": "在当前页检查",
                }
            )
        elif persisted["status"] == "recovered":
            actions.append(
                {
                    "type": "acknowledge_data_source_recovery",
                    "incident_id": persisted["id"],
                    "label": "确认恢复",
                }
            )
        incidents.append(
            {
                "id": f"data_source:{persisted['id']}",
                "source": "data_source",
                "entity_id": persisted["id"],
                "status": persisted["status"],
                "occurred_at": persisted["started_at"],
                "error": persisted["error"],
                "context": {
                    "source": persisted["source"],
                    "operation": persisted["operation"],
                    "recovered_at": persisted["recovered_at"],
                },
                "actions": actions,
            }
        )
    return incidents


def check_incident_data_source(req: DataSourceIncidentCheck) -> dict:
    incident = repository.get_data_source_incident(req.incident_id)
    if incident is None:
        return {"ok": False, "error": "数据源故障记录不存在"}
    if incident["source"] != req.source or incident["operation"] != req.operation:
        return {"ok": False, "error": "检查请求与故障记录不一致"}
    result = check_data_source(req)
    updated = repository.record_data_source_check(req.incident_id, result)
    return {"ok": bool(result.get("ok")), "check": result, "incident": updated}


def acknowledge_data_source_recovery(incident_id: str, resolution: str) -> dict:
    incident = repository.acknowledge_data_source_recovery(incident_id, resolution.strip())
    if incident is None:
        return {"ok": False, "error": "故障记录不存在或尚未恢复"}
    return {"ok": True, "incident": incident}


def data_source_history(limit: int = 200) -> dict:
    incidents = repository.list_data_source_incidents(limit=limit)
    return {"ok": True, "count": len(incidents), "incidents": incidents}


def list_incidents(*, limit: int = 100, cursor: str | None = None) -> dict:
    incidents = [
        *_analysis_incidents(10_000),
        *_automation_incidents(10_000),
        *_ledger_incidents(10_000),
        *_data_source_incidents(),
    ]
    incidents.sort(key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
    total = len(incidents)
    if cursor:
        cursor_value, cursor_id = store._decode_cursor(cursor)
        incidents = [
            item
            for item in incidents
            if (float(item["occurred_at"]), str(item["id"])) < (cursor_value, cursor_id)
        ]
    has_more = len(incidents) > limit
    items = incidents[:limit]
    next_cursor = (
        store._encode_cursor(float(items[-1]["occurred_at"]), str(items[-1]["id"]))
        if has_more and items
        else None
    )
    return {
        "ok": True,
        "count": len(items),
        "total": total,
        "next_cursor": next_cursor,
        "incidents": items,
    }

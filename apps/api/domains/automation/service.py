"""自动化服务：任务覆盖、立即运行、运行历史、告警与审计。"""

from __future__ import annotations

import importlib
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from apps.api import store

from . import repository
from .schemas import FactorResearchJobCreate


class AutomationNotFoundError(LookupError):
    """自动化任务或运行记录不存在。"""


class AutomationConflictError(RuntimeError):
    """当前状态不允许执行请求的操作。"""


_TIMEZONE = ZoneInfo("Asia/Shanghai")
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="automation")


def _configured_jobs() -> list[dict]:
    try:
        from apps.scheduler import jobs as scheduler_jobs
    except Exception as exc:
        raise RuntimeError("scheduler 未配置") from exc

    try:
        rows = scheduler_jobs._build_jobs()
    except Exception as exc:
        raise RuntimeError(f"构建任务失败: {exc}") from exc
    return rows


def _next_run(cron: str) -> str:
    trigger = CronTrigger.from_crontab(cron, timezone=_TIMEZONE)
    now = datetime.now(_TIMEZONE)
    next_fire = trigger.get_next_fire_time(None, now)
    if next_fire is None:
        raise ValueError("Cron 无法计算下次执行时间")
    return next_fire.isoformat()


def _merged_jobs() -> list[dict]:
    overrides = repository.list_overrides()
    jobs: list[dict] = []
    for row in _configured_jobs():
        override = overrides.get(row["name"])
        cron = override["cron"] if override else row["cron"]
        enabled = override["enabled"] if override else bool(row.get("enabled", True))
        jobs.append(
            {
                "name": row["name"],
                "market": row["market"],
                "cron": cron,
                "func_name": row["func_name"],
                "custom": not row["func_name"].startswith("__run_strategy__:"),
                "enabled": enabled,
                "next_run": _next_run(cron) if enabled else None,
                "updated_at": override["updated_at"] if override else None,
                "updated_by": override["updated_by"] if override else None,
            }
        )
    jobs.sort(key=lambda item: (item["market"], item["name"]))
    return jobs


def list_jobs() -> dict:
    """列出全部配置任务，并合并持久化启停与 Cron 覆盖。"""
    try:
        jobs = _merged_jobs()
    except Exception as exc:  # noqa: BLE001 - expose scheduler configuration failures to the UI
        return {"ok": False, "error": str(exc), "jobs": []}
    return {"ok": True, "count": len(jobs), "jobs": jobs}


def get_job(name: str) -> dict:
    """按精确任务名查询任务。"""
    result = list_jobs()
    if not result.get("ok"):
        return result
    for job in result["jobs"]:
        if job["name"] == name:
            return {"ok": True, "job": job}
    return {"ok": False, "error": f"未找到任务: {name}"}


def list_factor_research_jobs() -> dict:
    jobs = repository.list_factor_research_jobs()
    return {"ok": True, "count": len(jobs), "jobs": jobs, "timezone": str(_TIMEZONE)}


def create_factor_research_job(payload: FactorResearchJobCreate) -> dict:
    universe = store.get_factor_universe(payload.request.universe_id)
    if universe is None:
        raise AutomationNotFoundError(f"股票池不存在: {payload.request.universe_id}")
    if payload.request.transaction_cost_profile is not None:
        if payload.request.transaction_cost_profile.market != universe["market"]:
            raise ValueError("transaction_cost_profile.market 与股票池市场不一致")
    request = payload.request.model_dump(mode="json", exclude_none=True)
    try:
        job = repository.create_factor_research_job(
            name=payload.name,
            universe_id=payload.request.universe_id,
            cron=payload.cron(),
            enabled=payload.enabled,
            request=request,
            actor=payload.actor,
        )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise AutomationConflictError(f"因子研究作业名称已存在: {payload.name}") from exc
        raise
    repository.add_audit(
        action="create_factor_research_job",
        entity_type="factor_research_job",
        entity_id=job["id"],
        actor=payload.actor,
        before=None,
        after=job,
        result="succeeded",
    )
    return job


def update_factor_research_job(job_id: str, patch: dict, *, actor: str) -> dict:
    before = repository.get_factor_research_job(job_id)
    if before is None:
        raise AutomationNotFoundError(f"因子研究作业不存在: {job_id}")
    after = repository.update_factor_research_job(job_id, patch, actor)
    repository.add_audit(
        action="update_factor_research_job",
        entity_type="factor_research_job",
        entity_id=job_id,
        actor=actor,
        before=before,
        after=after,
        result="succeeded",
    )
    return after


def _require_job(name: str) -> dict:
    result = get_job(name)
    if not result.get("ok"):
        raise AutomationNotFoundError(result.get("error") or f"未找到任务: {name}")
    return result["job"]


def status() -> dict:
    """返回自动化控制台聚合状态。"""
    result = list_jobs()
    if not result.get("ok"):
        return result
    jobs = result["jobs"]
    runs = repository.list_runs(limit=1000)
    by_market: dict[str, int] = {}
    for job in jobs:
        by_market[job["market"]] = by_market.get(job["market"], 0) + 1
    failed = [run for run in runs if run["status"] == "failed"]
    return {
        "ok": True,
        "total": len(jobs),
        "enabled_count": sum(1 for job in jobs if job["enabled"]),
        "by_market": by_market,
        "custom_entry_count": sum(1 for job in jobs if job["custom"]),
        "generic_entry_count": sum(1 for job in jobs if not job["custom"]),
        "running_count": sum(1 for run in runs if run["status"] in {"queued", "running"}),
        "failed_count": len(failed),
        "unacknowledged_alert_count": sum(1 for run in failed if run["acknowledged_at"] is None),
        "running": any(run["status"] == "running" for run in runs),
        "note": "任务配置覆盖、立即运行、历史、重试和告警均由本控制台持久化管理。",
    }


def update_job(
    name: str,
    *,
    enabled: bool | None,
    cron: str | None,
    actor: str,
) -> dict:
    before = _require_job(name)
    next_enabled = before["enabled"] if enabled is None else enabled
    next_cron = before["cron"] if cron is None else cron
    try:
        _next_run(next_cron)
        repository.save_override(
            name,
            enabled=next_enabled,
            cron=next_cron,
            actor=actor,
        )
        after = _require_job(name)
        repository.add_audit(
            action="update_job",
            entity_type="automation_job",
            entity_id=name,
            actor=actor,
            before=before,
            after=after,
            result="succeeded",
        )
        return after
    except Exception as exc:
        repository.add_audit(
            action="update_job",
            entity_type="automation_job",
            entity_id=name,
            actor=actor,
            before=before,
            after=None,
            result="failed",
            error=str(exc),
        )
        raise


def _execute_job(func_name: str):
    if func_name.startswith("__run_factor_research__:"):
        from apps.api.domains.factor_research.schemas import CrossSectionResearchRequest
        from apps.api.domains.factor_research.service import run_cross_sectional_research

        job_id = func_name.split(":", 1)[1]
        job = repository.get_factor_research_job(job_id)
        if job is None:
            raise AutomationNotFoundError(f"因子研究作业不存在: {job_id}")
        result = run_cross_sectional_research(CrossSectionResearchRequest(**job["request"]))
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "因子研究作业失败")
        from apps.api.domains.alerts.service import check_all_rules

        check_all_rules(force=True)
        return {
            "research_run_id": result["run_id"],
            "factor_research_job_id": job_id,
        }
    if func_name.startswith("__run_strategy__:"):
        from strategies import configured_strategy_config, get_strategy

        strategy_name = func_name.split(":", 1)[1]
        strategy = get_strategy(
            strategy_name,
            config=configured_strategy_config(strategy_name),
        )
        return strategy.produce()

    module_path, separator, function_name = func_name.rpartition(".")
    if not separator or not module_path or not function_name:
        raise ValueError(f"无效任务入口: {func_name}")
    module = importlib.import_module(module_path)
    function = getattr(module, function_name)
    return function()


def _result_log(job: dict, result) -> str:
    lines = [
        f"任务: {job['name']}",
        f"入口: {job['func_name']}",
        "状态: succeeded",
    ]
    if result is not None:
        try:
            rendered = json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            rendered = repr(result)
        lines.append(f"结果: {rendered}")
    return "\n".join(lines)


def _result_reference(result) -> tuple[str | None, str | None]:
    """只提取明确、可复现的业务产出引用，不从日志文本猜测。"""
    if isinstance(result, dict):
        explicit_type = result.get("result_type")
        explicit_id = result.get("result_id")
        if isinstance(explicit_type, str) and isinstance(explicit_id, str):
            return explicit_type, explicit_id
        research_run_id = result.get("research_run_id")
        if isinstance(research_run_id, str) and research_run_id:
            run = store.get_research_run(research_run_id)
            result_type = (
                "factor_research"
                if run
                and any(
                    module in run.get("modules", [])
                    for module in ("factor_research", "cross_sectional_factor_research")
                )
                else "research_run"
            )
            return result_type, research_run_id
        signal_id = result.get("signal_id")
        if isinstance(signal_id, str) and signal_id:
            return "signal", signal_id
        order_id = result.get("order_id")
        if isinstance(order_id, str) and order_id:
            return "simulation_order", order_id
    if isinstance(result, (list, tuple)):
        references = {_result_reference(item) for item in result}
        references.discard((None, None))
        if len(references) == 1:
            return references.pop()
    return None, None


def _execute_run(run_id: str, actor: str = "local-user") -> None:
    run = repository.get_run(run_id)
    if run is None:
        return
    started_at = time.time()
    repository.update_run(run_id, {"status": "running", "started_at": started_at})
    try:
        job = _require_job(run["job_name"])
        result = _execute_job(job["func_name"])
        result_type, result_id = _result_reference(result)
        finished_at = time.time()
        completed = repository.update_run(
            run_id,
            {
                "status": "succeeded",
                "log": _result_log(job, result),
                "error": None,
                "finished_at": finished_at,
                "duration_ms": round((finished_at - started_at) * 1000),
                "result_type": result_type,
                "result_id": result_id,
            },
        )
        repository.add_audit(
            action="complete_run",
            entity_type="automation_run",
            entity_id=run_id,
            actor=actor,
            before=run,
            after=completed,
            result="succeeded",
        )
    except Exception as exc:  # noqa: BLE001 - persist any background runner failure
        finished_at = time.time()
        failed = repository.update_run(
            run_id,
            {
                "status": "failed",
                "log": traceback.format_exc(),
                "error": str(exc),
                "finished_at": finished_at,
                "duration_ms": round((finished_at - started_at) * 1000),
            },
        )
        repository.add_audit(
            action="complete_run",
            entity_type="automation_run",
            entity_id=run_id,
            actor=actor,
            before=run,
            after=failed,
            result="failed",
            error=str(exc),
        )


def submit_run(
    name: str,
    *,
    actor: str,
    trigger_type: str = "manual",
    parent_run_id: str | None = None,
    attempt: int = 1,
) -> dict:
    job = _require_job(name)
    if not job["enabled"]:
        raise AutomationConflictError(f"任务已停用: {name}")
    if trigger_type == "scheduled":
        active = repository.find_active_run(name, trigger_type)
        if active is not None:
            return active
    run = repository.create_run(
        name,
        trigger_type=trigger_type,
        attempt=attempt,
        parent_run_id=parent_run_id,
    )
    repository.add_audit(
        action="run_job" if trigger_type == "manual" else "retry_run",
        entity_type="automation_run",
        entity_id=run["id"],
        actor=actor,
        before=None,
        after=run,
        result="queued",
    )
    try:
        _EXECUTOR.submit(_execute_run, run["id"], actor)
    except Exception as exc:
        failed = repository.update_run(
            run["id"],
            {"status": "failed", "error": str(exc), "log": traceback.format_exc()},
        )
        repository.add_audit(
            action="dispatch_run",
            entity_type="automation_run",
            entity_id=run["id"],
            actor=actor,
            before=run,
            after=failed,
            result="failed",
            error=str(exc),
        )
        raise
    return repository.get_run(run["id"])


def recover_pending_runs() -> dict:
    recovered = []
    for run in repository.list_runs(limit=10_000):
        if run["status"] not in {"queued", "running"}:
            continue
        repository.update_run(run["id"], {"status": "queued", "started_at": None})
        _EXECUTOR.submit(_execute_run, run["id"], "recovery-worker")
        recovered.append(run["id"])
    return {"ok": True, "count": len(recovered), "run_ids": recovered}


def list_runs(
    *,
    job_name: str | None = None,
    run_status: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> dict:
    page = repository.list_runs_page(
        job_name=job_name, status=run_status, limit=limit, cursor=cursor
    )
    return {
        "ok": True,
        "count": len(page["items"]),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "runs": page["items"],
    }


def get_run(run_id: str) -> dict:
    run = repository.get_run(run_id)
    if run is None:
        raise AutomationNotFoundError(f"未找到运行记录: {run_id}")
    return run


def retry_run(run_id: str, *, actor: str) -> dict:
    previous = get_run(run_id)
    if previous["status"] != "failed":
        raise AutomationConflictError("只有失败运行可以重试")
    if previous["acknowledged_at"] is None:
        repository.update_run(
            run_id,
            {"acknowledged_at": time.time(), "acknowledged_by": actor},
        )
    return submit_run(
        previous["job_name"],
        actor=actor,
        trigger_type="retry",
        parent_run_id=run_id,
        attempt=previous["attempt"] + 1,
    )


def acknowledge_run(run_id: str, *, actor: str) -> dict:
    before = get_run(run_id)
    if before["status"] != "failed":
        raise AutomationConflictError("只有失败运行可以确认告警")
    if before["acknowledged_at"] is not None:
        return before
    after = repository.update_run(
        run_id,
        {"acknowledged_at": time.time(), "acknowledged_by": actor},
    )
    repository.add_audit(
        action="acknowledge_alert",
        entity_type="automation_run",
        entity_id=run_id,
        actor=actor,
        before=before,
        after=after,
        result="succeeded",
    )
    return after


def alerts(*, limit: int = 100) -> dict:
    runs = [
        run
        for run in repository.list_runs(status="failed", limit=limit)
        if run["acknowledged_at"] is None
    ]
    return {"ok": True, "count": len(runs), "alerts": runs}


def audit_logs(*, limit: int = 100, cursor: str | None = None) -> dict:
    page = repository.list_audit_page(limit=limit, cursor=cursor)
    return {
        "ok": True,
        "count": len(page["items"]),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "audit": page["items"],
    }

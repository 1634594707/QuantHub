"""APScheduler 定时任务调度器。

负责:
    - 选币（okx_grid selector）
    - 情绪扫描（sentiment daily_scan_cron）
    - 公告监控（perks_monitor cron）
    - 晨会简报（morning_brief cron）
    - 选股（selector cron）

cron 表达式来自 configs/a_shares.yaml / crypto.yaml 的 modules.<name>.cron
"""

from __future__ import annotations

import logging
from collections.abc import Callable

# ======= 先触发策略注册，再看板/调度器共用同一注册表 =======
from strategies import discover_and_register

discover_and_register()

from core.config import get_config
from strategies import configured_strategy_config, get_strategy

logger = logging.getLogger(__name__)

# 各策略任务的实际执行函数在策略模块内实现，此处仅注册调度
JobFunc = Callable[[], None]

# 市场 → 模块 → 固定入口函数（A股等自定义 runner）；无则走通用 _run_strategy
_CUSTOM_JOB_FUNCS: dict[str, dict[str, str]] = {
    "a_shares": {
        "sentiment": "strategies.a_shares.sentiment.run_daily_scan",
        "selector": "strategies.a_shares.selector.run_daily_select",
        "morning_brief": "strategies.a_shares.morning_brief.generate",
        "perks_monitor": "strategies.a_shares.perks_monitor.scan_announcements",
        "news_scanner": "strategies.a_shares.news_scanner.scan",
        "supertrend": "strategies.a_shares.supertrend.run_scan",
    },
    "ai_analysis": {
        "pa_agent": "strategies.ai_analysis.pa_agent.run_scheduled",
    },
}

_MARKETS = ["a_shares", "crypto", "mt5", "ai_analysis"]


def _build_jobs() -> list[dict]:
    """从配置构建任务清单。返回 [{name, market, cron, func_name}]。

    支持多市场（a_shares / crypto / mt5）。若模块在 _CUSTOM_JOB_FUNCS 中
    则使用模块级入口；否则使用通用 _run_strategy 入口。
    """
    jobs: list[dict] = []
    for market in _MARKETS:
        cfg = get_config(market)
        modules = cfg.get("modules", {})
        for name, info in modules.items():
            if not info.get("enabled", False):
                continue
            cron = info.get("cron") or info.get("daily_scan_cron")
            if not cron:
                continue
            custom = _CUSTOM_JOB_FUNCS.get(market, {}).get(name)
            if custom:
                func_name = custom
            else:
                # 通用入口：运行策略 produce()，已内部发布到信号总线
                func_name = f"__run_strategy__:{name}"
            jobs.append(
                {"name": f"{market}_{name}", "market": market, "cron": cron, "func_name": func_name}
            )
    from apps.api import store
    from apps.api.domains.automation import repository as automation_repository

    for factor_job in automation_repository.list_factor_research_jobs():
        universe = store.get_factor_universe(factor_job["universe_id"])
        if universe is None:
            logger.error(
                "跳过缺少股票池的因子研究作业 %s: %s",
                factor_job["id"],
                factor_job["universe_id"],
            )
            continue
        jobs.append(
            {
                "name": f"factor_research_{factor_job['id']}",
                "market": universe["market"],
                "cron": factor_job["cron"],
                "func_name": f"__run_factor_research__:{factor_job['id']}",
                "enabled": factor_job["enabled"],
            }
        )
    overrides = automation_repository.list_overrides()
    for job in jobs:
        override = overrides.get(job["name"])
        if override is not None:
            job["cron"] = override["cron"]
            job["enabled"] = override["enabled"]
    return jobs


def start() -> None:
    """启动调度器（阻塞）。"""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as e:
        raise ImportError("apscheduler 未安装，请运行: pip install apscheduler") from e

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    jobs = _build_jobs()
    for job in jobs:
        if not job.get("enabled", True):
            continue
        # 解析 cron: "0 18 * * 1-5" -> CronTrigger
        parts = job["cron"].split()
        if len(parts) != 5:
            logger.warning("无效 cron: %s", job["cron"])
            continue
        minute, hour, day, month, day_of_week = parts
        try:
            scheduler.add_job(
                _dispatch_job,
                CronTrigger(
                    minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week
                ),
                args=[job["name"]],
                id=job["name"],
                name=job["name"],
                replace_existing=True,
            )
            logger.info("注册任务 %s: %s", job["name"], job["cron"])
        except Exception:
            logger.exception("注册任务失败: %s", job["name"])

    logger.info("调度器启动，共 %d 个任务", len(jobs))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器停止")


def _run_strategy(strategy_name: str) -> None:
    """通用入口：执行指定策略的 produce()（策略内部会发布信号到总线）。"""
    try:
        strategy = get_strategy(
            strategy_name,
            config=configured_strategy_config(strategy_name),
        )
    except Exception:
        logger.exception("未找到策略: %s", strategy_name)
        return
    try:
        strategy.produce()
    except Exception:
        logger.exception("策略执行失败: %s", strategy_name)


def _dispatch_job(job_name: str) -> None:
    """APScheduler 只创建持久化运行记录，任务由自动化执行器消费。"""
    from apps.api.domains.automation import service as automation_service

    try:
        automation_service.submit_run(
            job_name,
            actor="scheduler",
            trigger_type="scheduled",
        )
    except Exception:
        logger.exception("任务入队失败: %s", job_name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start()

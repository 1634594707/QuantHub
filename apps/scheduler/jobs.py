# -*- coding: utf-8 -*-
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
from typing import Callable

# ======= 先触发策略注册，再看板/调度器共用同一注册表 =======
from strategies import discover_and_register

discover_and_register()

from core.config import get_config
from strategies import get_strategy

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
            jobs.append({"name": f"{market}_{name}", "market": market,
                         "cron": cron, "func_name": func_name})
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
        # 解析 cron: "0 18 * * 1-5" -> CronTrigger
        parts = job["cron"].split()
        if len(parts) != 5:
            logger.warning("无效 cron: %s", job["cron"])
            continue
        minute, hour, day, month, day_of_week = parts
        try:
            scheduler.add_job(
                _dispatch_job, CronTrigger(minute=minute, hour=hour, day=day,
                                           month=month, day_of_week=day_of_week),
                args=[job["func_name"]], id=job["name"], name=job["name"],
                replace_existing=True,
            )
            logger.info("注册任务 %s: %s", job["name"], job["cron"])
        except Exception:  # noqa: BLE001
            logger.exception("注册任务失败: %s", job["name"])

    logger.info("调度器启动，共 %d 个任务", len(jobs))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器停止")


def _run_strategy(strategy_name: str) -> None:
    """通用入口：执行指定策略的 produce()（策略内部会发布信号到总线）。"""
    try:
        strategy = get_strategy(strategy_name)
    except Exception:  # noqa: BLE001
        logger.exception("未找到策略: %s", strategy_name)
        return
    try:
        strategy.produce()
    except TypeError:
        # 部分策略 produce() 需要参数（如 mt5 alphamaster 需要 timeframe）
        # 按模块配置中的 timeframe 或默认 1h 传参
        try:
            strategy.produce(timeframe="1h")
        except Exception:  # noqa: BLE001
            logger.exception("策略执行失败: %s", strategy_name)
    except Exception:  # noqa: BLE001
        logger.exception("策略执行失败: %s", strategy_name)


def _dispatch_job(func_name: str) -> None:
    """按函数全路径动态导入并执行；通用策略入口以 __run_strategy__:<name> 标识。"""
    import importlib
    if func_name.startswith("__run_strategy__:"):
        strategy_name = func_name.split(":", 1)[1]
        _run_strategy(strategy_name)
        return
    module_path, _, fn_name = func_name.rpartition(".")
    try:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, fn_name)
        fn()
    except Exception:  # noqa: BLE001
        logger.exception("任务执行失败: %s", func_name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start()

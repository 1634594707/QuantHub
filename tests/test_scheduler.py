"""apps.scheduler 定时任务构建测试。"""

from __future__ import annotations

from apps.scheduler import jobs


def _names() -> set[str]:
    return {j["name"] for j in jobs._build_jobs()}


def test_enabled_strategies_scheduled():
    names = _names()
    # A股 6 个已启用模块全部进调度（含原先缺 cron 的 news_scanner/supertrend）
    for n in [
        "a_shares_sentiment",
        "a_shares_selector",
        "a_shares_morning_brief",
        "a_shares_perks_monitor",
        "a_shares_news_scanner",
        "a_shares_supertrend",
    ]:
        assert n in names, f"缺失调度任务: {n}"
    # ai_analysis / pa_agent 通过新建 configs/ai_analysis.yaml 进调度
    assert "ai_analysis_pa_agent" in names


def test_disabled_markets_not_scheduled():
    names = _names()
    # crypto / mt5 模块默认关闭，不应出现在调度中
    assert "crypto_okx_grid" not in names
    assert "crypto_alphagpt" not in names
    assert "mt5_alphamaster" not in names


def test_custom_job_funcs_resolve():
    """自定义入口函数（含 pa_agent.run_scheduled）必须可动态导入。"""
    import importlib

    for job in jobs._build_jobs():
        fn = job["func_name"]
        if not fn.startswith("__run_strategy__:"):
            module_path, _, fn_name = fn.rpartition(".")
            mod = importlib.import_module(module_path)
            assert hasattr(mod, fn_name), f"入口不可解析: {fn}"

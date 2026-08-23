from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from apps.api import store

MODE_SECTIONS = {
    "quick": [("summary", "结论"), ("evidence", "依据"), ("risk", "风险与观察")],
    "investor": [
        ("summary", "研究结论"),
        ("fundamentals", "财报与盈利趋势"),
        ("valuation", "估值与敏感度"),
        ("events", "事件与宏观传导"),
        ("risk", "风险与失效条件"),
    ],
    "professional": [
        ("summary", "结构化结论"),
        ("evidence", "原始证据与口径"),
        ("calculation", "确定性计算"),
        ("inference", "模型推断与不确定性"),
        ("risk", "门禁与失效条件"),
    ],
    "quant": [
        ("summary", "量化结论"),
        ("factors", "因子与股票池"),
        ("experiment", "策略与实验数据"),
        ("risk", "风险与复现条件"),
    ],
}


def _decision(run: dict) -> dict:
    return (
        ((run.get("summary") or {}).get("research_decision") or {})
        if isinstance(run.get("summary"), dict)
        else {}
    )


def _section_body(key: str, run: dict, mode: str) -> tuple[str, list[str]]:
    summary = run.get("summary") or {}
    evidence = run.get("evidence") or []
    ids = [str(item.get("id")) for item in evidence if item.get("id")]
    decision = _decision(run)
    direction = decision.get("direction", "insufficient")
    conflicts = decision.get("conflicts") or []
    if key == "summary":
        body = f"研究参考：{run.get('symbol')} 当前统一研究方向为「{direction}」。"
        if conflicts:
            body += f" 存在方向冲突（{len(conflicts)} 项），不得据此形成执行结论。"
        return body, ids[:3]
    if key == "fundamentals":
        value = summary.get("fundamentals") or {}
        return (
            f"财务质量：{value.get('financial_quality', '数据缺口')}；盈利趋势：{value.get('earnings_trend', '数据缺口')}。",
            ids,
        )
    if key == "valuation":
        value = summary.get("valuation") or {}
        return (
            f"估值区间：{value.get('valuation_range', '数据缺口')}；历史分位：{value.get('valuation_percentile', '未知')}。关键假设变化需要重新运行确定性计算。",
            ids,
        )
    if key == "events":
        return "公司事件、行业暴露和宏观传导分别评估；宏观结论必须同时具备事件与标的暴露证据。", ids
    if key == "evidence":
        return (
            f"已保存 {len(evidence)} 条带来源证据。模型只读取证据摘要，不直接改写结构化结论。",
            ids,
        )
    if key == "calculation":
        return "财务指标、估值分位和市场指标由确定性模块计算；本章节不引入未经保存的数字。", ids
    if key == "inference":
        return "模型推断与事实、计算结果分开标注；预测内容应附时间范围、反例和失效条件。", ids
    if key == "factors":
        return "因子、股票池、版本和实验数据沿用研究运行快照，当前模式只改变术语与章节密度。", ids
    if key == "experiment":
        return "策略实验结果必须绑定数据版本和复现条件，半成品报告不会进入导出或执行流程。", ids
    if key == "risk":
        warning = (
            "；".join(str(item) for item in conflicts)
            if conflicts
            else "证据不足、数据过期和执行门禁由程序强制保留。"
        )
        return f"风险提示：研究参考，不是收益承诺。{warning}", ids
    return "该章节暂无可用证据，已明确标记为缺口。", ids


def generate_report(report: dict, run: dict, *, only_section: str | None = None) -> dict:
    sections = MODE_SECTIONS.get(report["mode"], MODE_SECTIONS["investor"])
    store.append_research_report_event(
        report["id"],
        event_type="report_started",
        payload={"mode": report["mode"], "research_run_id": run["id"]},
    )
    selected = [item for item in sections if only_section is None or item[0] == only_section]
    for position, (key, title) in enumerate(selected):
        section = store.create_research_report_section(
            report["id"], section_key=key, position=position, title=title
        )
        store.append_research_report_event(
            report["id"],
            event_type="section_started",
            section_id=section["id"],
            payload={"section_key": key, "title": title},
        )
        body, evidence_ids = _section_body(key, run, report["mode"])
        # 以固定小段生成 delta，前端可断点续传且不会暴露供应商 chunk 格式。
        for index in range(0, len(body), 120):
            delta = body[index : index + 120]
            store.append_research_report_event(
                report["id"],
                event_type="delta",
                section_id=section["id"],
                payload={"section_key": key, "delta": delta},
            )
        store.update_research_report_section(
            section["id"], {"status": "completed", "body": body, "evidence_ids": evidence_ids}
        )
        store.append_research_report_event(
            report["id"],
            event_type="section_completed",
            section_id=section["id"],
            payload={"section_key": key, "evidence_ids": evidence_ids},
        )
    final = store.get_research_report(report["id"])
    snapshot = {
        "report_id": report["id"],
        "research_run_id": run["id"],
        "mode": report["mode"],
        "sections": final.get("sections", []) if final else [],
        "decision": _decision(run),
        "data_cutoff": datetime.fromtimestamp(float(run.get("updated_at", 0)), UTC).isoformat(),
    }
    digest = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    status = "completed" if only_section is None else "completed"
    store.update_research_report(
        report["id"],
        {
            "status": status,
            "data_cutoff": snapshot["data_cutoff"],
            "model_version": "deterministic-explanation-v1",
            "prompt_version": "research-report-v1",
            "snapshot": snapshot,
            "content_hash": digest,
        },
    )
    store.append_research_report_event(
        report["id"],
        event_type="report_completed",
        payload={"content_hash": digest, "snapshot": snapshot},
    )
    return store.get_research_report(report["id"]) or report

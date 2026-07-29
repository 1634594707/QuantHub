"""新闻分析评估指标（P/R/F1/accuracy）。

用于 ``tools/eval_news_metrics.py`` 校验本地 LLM 是否达到验收阈值：
    - 情绪 F1（三分类 macro-F1）≥ 0.80
    - 主题准确率 ≥ 0.75
    - NER 准确率（relaxed：text+type 完全相等）≥ 0.70
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """计算单类 precision / recall / f1。"""
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def sentiment_metrics(preds: list[str], golds: list[str]) -> dict[str, Any]:
    """三分类情绪 macro-F1 + accuracy + per-class P/R/F1。"""
    labels = ["positive", "negative", "neutral"]
    per_class: dict[str, dict[str, float]] = {}
    f1_sum = 0.0
    correct = 0
    for lab in labels:
        tp = sum(1 for p, g in zip(preds, golds, strict=False) if p == lab and g == lab)
        fp = sum(1 for p, g in zip(preds, golds, strict=False) if p == lab and g != lab)
        fn = sum(1 for p, g in zip(preds, golds, strict=False) if p != lab and g == lab)
        p, r, f = _prf(tp, fp, fn)
        per_class[lab] = {"precision": p, "recall": r, "f1": f, "support": tp + fn}
        f1_sum += f
    correct = sum(1 for p, g in zip(preds, golds, strict=False) if p == g)
    accuracy = correct / len(golds) if golds else 0.0
    return {
        "accuracy": accuracy,
        "macro_f1": f1_sum / len(labels) if labels else 0.0,
        "per_class": per_class,
    }


def topic_metrics(preds: list[str], golds: list[str]) -> dict[str, Any]:
    """主题准确率 + per-class accuracy（support 计数）。"""
    correct = sum(1 for p, g in zip(preds, golds, strict=False) if p == g)
    accuracy = correct / len(golds) if golds else 0.0
    support: Counter = Counter(golds)
    correct_per: Counter = Counter()
    for p, g in zip(preds, golds, strict=False):
        if p == g:
            correct_per[g] += 1
    per_class = {
        lab: {
            "support": support.get(lab, 0),
            "correct": correct_per.get(lab, 0),
            "recall": correct_per.get(lab, 0) / support[lab] if support.get(lab, 0) else 0.0,
        }
        for lab in sorted(support)
    }
    return {"accuracy": accuracy, "per_class": per_class}


def _normalize_entities(raw: Any) -> set[tuple[str, str]]:
    """把实体列表归一为 (text_lower, type) 集合（relaxed 匹配用）。"""
    out: set[tuple[str, str]] = set()
    if not isinstance(raw, list):
        return out
    for e in raw:
        if isinstance(e, dict):
            text = str(e.get("text", "") or "").strip().lower()
            etype = str(e.get("type", "") or "").strip().lower()
            if text and etype:
                out.add((text, etype))
        elif isinstance(e, dict) and "text" in e:
            text = str(e["text"]).strip().lower()
            out.add((text, "org"))
    return out


def ner_metrics(preds: list[list[dict]], golds: list[list[dict]]) -> dict[str, Any]:
    """NER 评估（relaxed：text+type 完全相等即 TP，micro 聚合）。

    ``accuracy`` 定义为 (TP) / (TP + FP + FN)，与 P/R 共用分母。
    """
    tp = fp = fn = 0
    exact_match = 0
    for p_list, g_list in zip(preds, golds, strict=False):
        p_set = _normalize_entities(p_list)
        g_set = _normalize_entities(g_list)
        tp += len(p_set & g_set)
        fp += len(p_set - g_set)
        fn += len(g_set - p_set)
        if p_set == g_set:
            exact_match += 1
    precision, recall, f1 = _prf(tp, fp, fn)
    accuracy = tp / (tp + fp + fn) if (tp + fp + fn) else 0.0
    exact_acc = exact_match / len(golds) if golds else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,  # token-level relaxed accuracy
        "exact_match_accuracy": exact_acc,  # set-equality per document
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def compute_metrics(predictions: list[dict], golds: list[dict]) -> dict[str, Any]:
    """聚合三项指标。

    Args:
        predictions: ``NewsAnalysis.to_dict()`` 列表（含 sentiment.label/topic/entities）
        golds: 标注样本列表（含 gold_sentiment/gold_topic/gold_entities）
    Returns:
        一级 key：sentiment / topic / ner / n_samples / n_degraded / thresholds / passed
    """
    n = min(len(predictions), len(golds))
    preds_sent = [predictions[i].get("sentiment", {}).get("label", "neutral") for i in range(n)]
    golds_sent = [golds[i].get("gold_sentiment", "neutral") for i in range(n)]
    preds_topic = [predictions[i].get("topic", "unknown") for i in range(n)]
    golds_topic = [golds[i].get("gold_topic", "unknown") for i in range(n)]
    preds_ent = [predictions[i].get("entities", []) for i in range(n)]
    golds_ent = [golds[i].get("gold_entities", []) for i in range(n)]

    sent = sentiment_metrics(preds_sent, golds_sent)
    top = topic_metrics(preds_topic, golds_topic)
    ner = ner_metrics(preds_ent, golds_ent)

    n_degraded = sum(1 for p in predictions[:n] if p.get("engine") != "semantic+api")

    thresholds = {
        "sentiment_f1": 0.80,
        "topic_accuracy": 0.75,
        "ner_accuracy": 0.70,
    }
    passed = (
        sent["macro_f1"] >= thresholds["sentiment_f1"]
        and top["accuracy"] >= thresholds["topic_accuracy"]
        and ner["accuracy"] >= thresholds["ner_accuracy"]
    )

    return {
        "n_samples": n,
        "n_degraded": n_degraded,
        "sentiment": sent,
        "topic": top,
        "ner": ner,
        "thresholds": thresholds,
        "passed": passed,
    }

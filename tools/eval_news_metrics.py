"""本地 LLM 新闻分析评估脚本。

用法（需先启动 LM Studio + 加载 Qwen2.5）::

    uv run python -m tools.eval_news_metrics \\
        --samples data/news_samples/labeled_news.jsonl \\
        --report outputs/news_eval_report.json

验收阈值（任一不达标即 Phase 1 验收失败）：
    - 情绪 macro-F1 ≥ 0.80
    - 主题准确率 ≥ 0.75
    - NER 准确率（relaxed） ≥ 0.70

注意：LM Studio 离线时本脚本会跑降级路径，结果必然不达标，
仅作为「降级链可用性」验证；正式验收须 LM Studio 在线。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from core.data_feed.base import News
from strategies.a_shares.news_analyzer.analyzer import NewsAnalyzer
from strategies.a_shares.news_analyzer.metrics import compute_metrics

logger = logging.getLogger(__name__)


def load_samples(path: Path) -> list[dict]:
    """加载 JSONL 标注样本。"""
    samples: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("第 %d 行 JSON 解析失败: %s", line_no, e)
    return samples


def sample_to_news(s: dict) -> News:
    """标注样本 → ``News`` 对象（评估用，ts 用固定时间便于复现）。"""
    return News(
        title=s.get("title", ""),
        content="",  # akshare 抓取时 content 为空，评估保持一致
        ts=datetime(2024, 1, 1),
        source=s.get("source", "eval"),
        url=None,
        symbols=[],
    )


def run_evaluation(
    samples: list[dict], analyzer: NewsAnalyzer, batch_size: int = 5
) -> tuple[list[dict], list[dict]]:
    """对样本逐批调用 analyzer，返回 (predictions, golds)。"""
    predictions: list[dict] = []
    golds: list[dict] = []
    news_list = [sample_to_news(s) for s in samples]

    for start in range(0, len(news_list), batch_size):
        chunk_news = news_list[start : start + batch_size]
        chunk_gold = samples[start : start + batch_size]
        batch = analyzer.analyze_batch(chunk_news)
        for it in batch.items:
            predictions.append(it.to_dict())
        golds.extend(chunk_gold)
        logger.info(
            "已评估 %d/%d (engine=%s, degraded=%s)",
            len(predictions),
            len(samples),
            batch.engine,
            not batch.ok,
        )

    return predictions, golds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地 LLM 新闻分析评估")
    parser.add_argument(
        "--samples",
        default="data/news_samples/labeled_news.jsonl",
        help="标注样本 JSONL 路径",
    )
    parser.add_argument(
        "--report",
        default="outputs/news_eval_report.json",
        help="评估报告输出路径",
    )
    parser.add_argument(
        "--batch-size", type=int, default=5, help="批量分析大小（与 analyzer 对齐）"
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="强制跳过 LLM（验证降级路径，不用于正式验收）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    samples_path = Path(args.samples)
    if not samples_path.exists():
        logger.error("样本文件不存在: %s", samples_path)
        return 2

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    samples = load_samples(samples_path)
    logger.info("加载 %d 条标注样本", len(samples))

    analyzer = NewsAnalyzer.from_config("a_shares")
    if args.no_llm:
        # 强制探活失败，走降级路径
        analyzer._avail_cached = False  # noqa: SLF001
        analyzer._avail_ts = float("inf")  # noqa: SLF001 永不刷新

    online = analyzer.is_available()
    logger.info("LM Studio 在线: %s", online)
    if not online and not args.no_llm:
        logger.warning("LM Studio 离线，将走降级路径，结果仅供降级链验证，不构成正式验收。")

    predictions, golds = run_evaluation(samples, analyzer, batch_size=args.batch_size)
    metrics = compute_metrics(predictions, golds)

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "samples_path": str(samples_path),
        "n_samples": metrics["n_samples"],
        "n_degraded": metrics["n_degraded"],
        "lmstudio_online": online,
        "metrics": metrics,
    }

    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print("\n" + "=" * 60)
    print(f"样本数: {metrics['n_samples']}  降级数: {metrics['n_degraded']}")
    print(f"LM Studio 在线: {online}")
    print("-" * 60)
    s = metrics["sentiment"]
    print(f"情绪  accuracy={s['accuracy']:.4f}  macro_f1={s['macro_f1']:.4f}  (阈值≥0.80)")
    t = metrics["topic"]
    print(f"主题  accuracy={t['accuracy']:.4f}  (阈值≥0.75)")
    n = metrics["ner"]
    print(
        f"NER   precision={n['precision']:.4f}  recall={n['recall']:.4f}  f1={n['f1']:.4f}  accuracy={n['accuracy']:.4f}  (阈值≥0.70)"
    )
    print("-" * 60)
    print(f"验收结果: {'PASSED ✓' if metrics['passed'] else 'FAILED ✗'}")
    print(f"报告已写入: {report_path}")
    print("=" * 60)

    return 0 if metrics["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

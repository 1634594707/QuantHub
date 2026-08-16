from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only stock research data acceptance")
    parser.add_argument(
        "--universe",
        default="configs/research/a_share_acceptance_universe.json",
    )
    parser.add_argument(
        "--output",
        default="docs/Plan/evidence/stock-research-roadmap-2026-08-16/data-report.json",
    )
    return parser.parse_args()


def json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "as_tuple"):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    return value


def main() -> int:
    args = parse_args()
    universe_path = Path(args.universe).resolve()
    output_path = Path(args.output).resolve()
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    samples = universe.get("samples") or []
    generated_at = datetime.now(UTC)

    with tempfile.TemporaryDirectory(prefix="quanthub-data-acceptance-") as temp_dir:
        os.environ["QUANTHUB_STORE_PATH"] = str(Path(temp_dir) / "store.db")

        from apps.api import database
        from apps.api.domains.financials.service import evaluate_fundamentals
        from packages.financial_data import AkshareValuationReferenceProvider

        results: list[dict[str, Any]] = []
        for sample in samples:
            symbol = str(sample["symbol"])
            instrument_id = f"a_shares:{symbol}"
            item: dict[str, Any] = {
                "symbol": symbol,
                "label": sample.get("label"),
                "industry_template": sample.get("industry_template"),
                "passed": False,
            }
            try:
                fundamentals = evaluate_fundamentals(
                    instrument_id=instrument_id,
                    market="a_shares",
                    as_of=generated_at,
                )
                references = AkshareValuationReferenceProvider().fetch_references(
                    instrument_id=instrument_id,
                    as_of=generated_at,
                )
                historical_counts = {
                    key: len(values) for key, values in references.historical_values.items()
                }
                item.update(
                    {
                        "passed": fundamentals["fetched_statement_count"] >= 3
                        and references.shares_outstanding > 0
                        and any(historical_counts.values()),
                        "financials": {
                            "provider": fundamentals["provider"]["provider"],
                            "statement_count": fundamentals["fetched_statement_count"],
                            "financial_quality": fundamentals["financial_quality"],
                            "earnings_trend": fundamentals["earnings_trend"],
                            "available_at": fundamentals["provenance"]["available_at"],
                            "source_url": fundamentals["provenance"].get("source_url"),
                        },
                        "valuation_references": {
                            "source": references.provenance.source,
                            "quality_status": references.provenance.quality_status,
                            "quality_reasons": references.provenance.quality_reasons,
                            "shares_outstanding": references.shares_outstanding,
                            "shares_at": references.shares_at,
                            "industry": (
                                references.comparable_group.industry
                                if references.comparable_group
                                else None
                            ),
                            "historical_counts": historical_counts,
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001 - acceptance report must retain provider failures
                item["error"] = f"{type(exc).__name__}: {exc}"
            results.append(item)
        database.dispose_engines()

    failures = [item for item in results if not item["passed"]]
    report = {
        "generated_at": generated_at.isoformat(),
        "universe": Path(args.universe).as_posix(),
        "store_mode": "temporary",
        "passed": not failures and len(results) == len(samples) and bool(results),
        "checks": len(results),
        "failures": failures,
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(json_value(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "checks": len(results),
                "failures": len(failures),
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

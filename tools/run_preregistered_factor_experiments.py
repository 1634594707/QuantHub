from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from core.factor_experiment_suite import build_preregistered_experiments
from core.point_in_time_universe import fingerprint_payload


def load_wide(baseline: dict) -> dict[str, pd.DataFrame]:
    selected = baseline["file_manifest"]
    common_sessions: set[int] | None = None
    frames = {}
    for item in selected:
        frame = pd.read_parquet(item["path"]).tail(750)
        frames[item["symbol"]] = frame
        sessions = {int(value) for value in frame["time"]}
        common_sessions = sessions if common_sessions is None else common_sessions & sessions
    if not common_sessions:
        raise RuntimeError("没有共同会话")
    sessions = sorted(common_sessions)

    def field(name: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                symbol: frame.set_index("time")[name].reindex(sessions)
                for symbol, frame in frames.items()
            },
            index=sessions,
        )

    return {
        "open_price": field("open"),
        "high": field("high"),
        "low": field("low"),
        "close": field("close"),
        "volume": field("tick_volume"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("demo_artifacts/a_share_300_factor_baseline.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("demo_artifacts/a_share_preregistered_experiments_01_07.json"),
    )
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    experiments = build_preregistered_experiments(**load_wide(baseline))
    suite_path = Path("core/factor_experiment_suite.py")
    definitions = [
        {
            key: experiment.get(key)
            for key in (
                "experiment_id",
                "hypothesis",
                "primary_label",
                "parameter_budget",
                "target_market",
                "pass_criteria",
                "execution_constraints",
                "limitations",
            )
            if key in experiment
        }
        for experiment in experiments
    ]
    deterministic_ai_metadata = {"used": False, "reason": "deterministic_research_run"}
    artifact = {
        "artifact_version": "a-share-preregistered-experiments-v2",
        "baseline_artifact_sha256": baseline["artifact_sha256"],
        "time_basis": baseline["time_basis"],
        "target_market": "a_shares",
        "experiments": experiments,
        "completed_experiments": len(experiments),
        "passed_experiments": sum(item["status"] == "passed" for item in experiments),
        "failed_experiments": sum(item["status"] == "failed" for item in experiments),
        "evidence_policy": "success_and_failure_evidence_preserved",
        "provenance": {
            "data": {
                "version": baseline["artifact_version"],
                "snapshot_hash": baseline["artifact_sha256"],
            },
            "formula": {
                "version": "factor-experiment-suite-v2",
                "source_hash": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
            },
            "experiment": {
                "version": "preregistered-experiment-contract-v1",
                "definition_hash": fingerprint_payload(definitions),
            },
            "model": {
                "version": "not_used",
                "hash": fingerprint_payload(deterministic_ai_metadata),
            },
            "prompt": {
                "version": "not_used",
                "hash": fingerprint_payload(deterministic_ai_metadata),
            },
            "cost": {
                "version": "a-share-execution-constraints-v1",
                "hash": fingerprint_payload(
                    [item.get("execution_constraints", []) for item in experiments]
                ),
            },
            "result": {
                "version": "cross-sectional-candidate-report-v1",
                "hash": fingerprint_payload(experiments),
            },
        },
    }
    artifact["artifact_sha256"] = fingerprint_payload(artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": args.output.as_posix(),
                "completed": artifact["completed_experiments"],
                "passed": artifact["passed_experiments"],
                "failed": artifact["failed_experiments"],
                "artifact_sha256": artifact["artifact_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

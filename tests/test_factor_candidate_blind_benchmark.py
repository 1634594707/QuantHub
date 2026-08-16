from __future__ import annotations

from unittest.mock import patch

from tools.run_factor_candidate_blind_benchmark import (
    BATCHES,
    PROTOCOL,
    SOURCE_ORDER,
    _adjacent_parameter_candidate_ids,
    _brain_candidate_specs,
    _manual_proposals,
    run_benchmark,
)


def test_adjacent_parameter_detection_does_not_label_distinct_mechanisms() -> None:
    specs = _brain_candidate_specs("a" * 32, _manual_proposals())

    assert _adjacent_parameter_candidate_ids(specs) == set()


def test_blind_benchmark_records_ai_unavailability_without_refill() -> None:
    unavailable = {
        "status": "unavailable",
        "candidate_count": 0,
        "requested_candidates": PROTOCOL["candidate_budget_per_source_per_batch"],
        "error": "RuntimeError: test provider unavailable",
    }
    with patch(
        "tools.run_factor_candidate_blind_benchmark.generate_ai_proposals",
        return_value=([], unavailable),
    ):
        result = run_benchmark()

    assert len(result["batches"]) == len(BATCHES)
    assert set(result["aggregate"]) == set(SOURCE_ORDER)
    for batch in result["batches"]:
        assert batch["generation_context"]["validation_labels_exposed"] is False
        assert batch["confirmation_labels_accessed"] is False
        assert batch["sources"]["ai"]["generated_count"] == 0
        assert batch["sources"]["ai"]["generation_shortfall"] == 6
        assert batch["sources"]["ai"]["generation"]["status"] == "unavailable"
        for source in SOURCE_ORDER:
            assert batch["sources"][source]["requested_budget"] == 6
    conclusion = result["conclusion"]
    assert conclusion["fixed_budget_protocol_executed"] is True
    assert conclusion["fixed_budget_five_source_comparison_completed"] is False
    assert conclusion["required_metric_schema_recorded"] is True
    assert conclusion["required_five_source_metrics_completed"] is False
    assert conclusion["multi_batch_ai_quality_test_completed"] is False
    assert conclusion["prompt_or_model_quality_improvement_supported"] is False
    assert result["locked_confirmation_evaluated"] is False
    assert result["live_trading_enabled"] is False

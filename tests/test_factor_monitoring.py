import unittest
from unittest.mock import patch

import numpy as np

from apps.api.domains.factor_research.schemas import (
    FactorCandidateInboxRequest,
    FactorDriftMonitoringRequest,
    FactorRetirementImpactRequest,
    FactorSimulationAttributionRequest,
    FactorSimulationValidationRequest,
)
from apps.api.domains.factor_research.service import (
    analyze_factor_drift,
    attribute_factor_simulation_gap,
    build_factor_candidate_inbox,
    preview_factor_retirement_impact,
    validate_factor_simulation,
)


class FactorMonitoringTests(unittest.TestCase):
    def test_candidate_inbox_separates_sources_states_and_backtest_gate(self) -> None:
        base = {
            "economic_hypothesis": "流动性冲击后存在短期反转",
            "formula_ast": {"op": "rank", "value": {"op": "field", "name": "close"}},
            "data_requirements": ["close", "amount"],
            "duplicate_risk": "low",
            "future_information_check_passed": True,
            "causal_check_passed": True,
            "data_check_passed": True,
            "estimated_compute_units": 50,
        }
        candidates = [
            {**base, "candidate_id": source, "source": source}
            for source in ("human", "ai", "template", "random_dsl", "symbolic_regression")
        ]
        candidates[0].update({"approved_by": "researcher", "budget_approved": True})
        candidates[1]["future_information_check_passed"] = False
        response = build_factor_candidate_inbox(FactorCandidateInboxRequest(candidates=candidates))[
            "inbox"
        ]

        self.assertEqual(response["count"], 5)
        self.assertEqual(set(response["source_counts"]), {item["source"] for item in candidates})
        self.assertEqual(response["backtest_ready_count"], 1)
        self.assertFalse(response["single_score_used"])
        ai = next(item for item in response["candidates"] if item["source"] == "ai")
        self.assertFalse(ai["start_backtest_entry_visible"])
        self.assertIn("future_information_check", ai["blockers"])
        self.assertIn("research_status", ai["states"])
        self.assertIn("trading_status", ai["states"])
        self.assertIn("ai_review", ai["states"])

    def test_drift_monitor_preregisters_thresholds_and_locates_affected_strategies(self) -> None:
        rng = np.random.default_rng(31)
        reference = rng.normal(0, 1, 300)
        current = rng.normal(2, 1.8, 120)
        correlated_reference = {
            "factor": reference.tolist(),
            "peer": (reference * 0.9 + rng.normal(0, 0.1, 300)).tolist(),
        }
        correlated_current = {
            "factor": current.tolist(),
            "peer": rng.normal(0, 1, 120).tolist(),
        }
        response = analyze_factor_drift(
            FactorDriftMonitoringRequest(
                factor_key="momentum_20",
                auto_degrade=False,
                reference_values=reference.tolist(),
                current_values=current.tolist(),
                reference_ic=0.06,
                current_ic=-0.01,
                reference_coverage=0.95,
                current_coverage=0.70,
                current_cost_bps=30,
                current_capacity_ratio=0.4,
                reference_correlated_factors=correlated_reference,
                current_correlated_factors=correlated_current,
                thresholds={
                    "maximum_ic_decay": 0.5,
                    "maximum_coverage_drop": 0.1,
                    "maximum_psi": 0.2,
                    "maximum_distribution_distance": 0.3,
                    "maximum_correlation_shift": 0.2,
                    "maximum_cost_bps": 20,
                    "minimum_capacity_ratio": 0.8,
                },
                affected_strategies=[
                    {"strategy_id": "strategy-a", "factor_keys": ["momentum_20"], "active": True},
                    {"strategy_id": "strategy-b", "factor_keys": ["quality"], "active": True},
                ],
            )
        )["monitoring"]

        self.assertTrue(response["degrade_required"])
        self.assertTrue(response["thresholds_preregistered"])
        self.assertIn("direction_flip", response["alerts"])
        self.assertIn("population_stability_index", response["alerts"])
        self.assertIn("correlation_structure_shift", response["alerts"])
        self.assertEqual(response["affected_strategy_count"], 1)
        self.assertEqual(response["affected_strategies"][0]["strategy_id"], "strategy-a")
        self.assertEqual(
            response["required_action"], "alert_degrade_and_locate_within_one_schedule_cycle"
        )
        self.assertEqual(response["lifecycle_action"]["status"], "disabled")
        self.assertTrue(response["completed_within_schedule_cycle"])

    def test_drift_monitor_degrades_once_and_locates_strategies(self) -> None:
        rng = np.random.default_rng(32)
        request = FactorDriftMonitoringRequest(
            factor_key="momentum_20",
            reference_values=rng.normal(0, 1, 100).tolist(),
            current_values=rng.normal(2, 1, 100).tolist(),
            reference_ic=0.06,
            current_ic=-0.02,
            reference_coverage=0.95,
            current_coverage=0.60,
            current_cost_bps=30,
            current_capacity_ratio=0.4,
            thresholds={
                "maximum_ic_decay": 0.5,
                "maximum_coverage_drop": 0.1,
                "maximum_psi": 0.2,
                "maximum_distribution_distance": 0.3,
                "maximum_correlation_shift": 0.2,
                "maximum_cost_bps": 20,
                "minimum_capacity_ratio": 0.8,
            },
            affected_strategies=[
                {"strategy_id": "strategy-a", "factor_keys": ["momentum_20"], "active": True}
            ],
        )
        definition = {"id": "definition-1"}
        evidence = {
            "formula_definition_hash": "a" * 64,
            "formula_hash": "b" * 64,
            "formula_version": "1.0.0",
            "data_snapshot_hash": "c" * 64,
            "cumulative_attempts": 1,
            "validation_window": {"start": "2025-01-01", "end": "2025-12-31"},
            "cost_profile_version": "cost-v1",
            "gate_version": "gate-v1",
        }
        passed = {"state": "research_passed", "evidence": evidence}
        degraded = {"id": "event-2", "state": "degraded", "evidence": evidence}
        with (
            patch("apps.api.domains.factor_research.service._ensure_builtin_factor_definitions"),
            patch(
                "apps.api.domains.factor_research.service.store.get_factor_definition",
                return_value=definition,
            ),
            patch(
                "apps.api.domains.factor_research.service.store.ensure_factor_lifecycle_draft",
                side_effect=[passed, degraded],
            ),
            patch(
                "apps.api.domains.factor_research.service.transition_factor_lifecycle",
                return_value={"ok": True, "event": degraded},
            ) as transition,
        ):
            first = analyze_factor_drift(request)["monitoring"]
            second = analyze_factor_drift(request)["monitoring"]

        self.assertEqual(first["lifecycle_action"]["status"], "degraded")
        self.assertEqual(second["lifecycle_action"]["status"], "already_degraded")
        self.assertEqual(transition.call_count, 1)
        transition_evidence = transition.call_args.args[2].evidence
        self.assertEqual(transition_evidence["affected_strategy_count"], 1)
        self.assertFalse(transition_evidence["live_trading_enabled"])

    def test_retirement_preview_preserves_history_and_shows_replacement_impact(self) -> None:
        preview = preview_factor_retirement_impact(
            FactorRetirementImpactRequest(
                factor_key="momentum_20",
                replacement_factor_key="residual_momentum",
                strategies=[
                    {
                        "strategy_id": "strategy-a",
                        "factor_keys": ["momentum_20", "quality"],
                    },
                    {"strategy_id": "strategy-b", "factor_keys": ["quality"]},
                ],
                portfolio_allocations=[
                    {"portfolio_id": "shadow-a", "factor_key": "momentum_20", "weight": 0.25}
                ],
            )
        )["preview"]

        self.assertEqual(preview["impacted_strategy_count"], 1)
        self.assertEqual(preview["impacted_portfolio_weight"], 0.25)
        self.assertIn(
            "residual_momentum", preview["impacted_strategies"][0]["projected_factor_keys"]
        )
        self.assertFalse(preview["definition_deletion_allowed"])
        self.assertEqual(
            preview["required_change"],
            "append_retirement_event_and_preserve_historical_definition",
        )

    def test_simulation_gate_requires_full_cycle_audit_and_preregistered_targets(self) -> None:
        execution = {
            "signal_time": "2026-07-01T15:00:00+08:00",
            "tradable_time": "2026-07-02T09:30:00+08:00",
            "theoretical_price": 10.0,
            "simulated_price": 10.02,
            "slippage_bps": 20.0,
            "rejection_reason": None,
            "capacity_used": 0.04,
        }
        passed = validate_factor_simulation(
            FactorSimulationValidationRequest(
                completed_rebalance_cycles=1,
                after_cost_return=0.03,
                fill_rate=0.95,
                capacity_ratio=0.9,
                thresholds={
                    "minimum_after_cost_return": 0.0,
                    "minimum_fill_rate": 0.9,
                    "minimum_capacity_ratio": 0.8,
                },
                execution_records=[execution],
            )
        )["validation"]
        blocked = validate_factor_simulation(
            FactorSimulationValidationRequest(
                completed_rebalance_cycles=0,
                after_cost_return=0.03,
                fill_rate=0.95,
                capacity_ratio=0.9,
                thresholds={
                    "minimum_after_cost_return": 0.0,
                    "minimum_fill_rate": 0.9,
                    "minimum_capacity_ratio": 0.8,
                },
                execution_records=[execution],
            )
        )["validation"]

        self.assertTrue(passed["eligible_for_trading_validated"])
        self.assertFalse(passed["live_trading_enabled"])
        self.assertFalse(blocked["eligible_for_trading_validated"])
        self.assertIn("complete_rebalance_cycle", blocked["violations"])

    def test_research_simulation_gap_is_decomposed_into_locked_components(self) -> None:
        response = attribute_factor_simulation_gap(
            FactorSimulationAttributionRequest(
                research_returns=[0.02, 0.01],
                simulation_returns=[0.012, 0.006],
                signal_decay=[-0.002, -0.001],
                data_delay=[-0.001, 0.0],
                execution=[-0.001, -0.001],
                costs=[-0.001, -0.001],
                portfolio_constraints=[-0.001, -0.001],
                research_metrics={
                    "ic": 0.06,
                    "coverage": 0.95,
                    "turnover": 0.3,
                    "cost_bps": 10.0,
                    "fill_rate": 1.0,
                },
                simulation_metrics={
                    "ic": 0.04,
                    "coverage": 0.90,
                    "turnover": 0.35,
                    "cost_bps": 15.0,
                    "fill_rate": 0.92,
                },
            )
        )["attribution"]

        self.assertAlmostEqual(response["total_gap"], -0.012)
        self.assertEqual(
            set(response["component_names_locked"]),
            {"signal_decay", "data_delay", "execution", "costs", "portfolio_constraints"},
        )
        self.assertAlmostEqual(response["unexplained_residual"], -0.002)
        self.assertAlmostEqual(response["metric_deltas"]["ic"], -0.02)


if __name__ == "__main__":
    unittest.main()

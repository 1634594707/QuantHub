from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from apps.api.domains.factor_research.schemas import (
    FactorDiscoveryEfficiencyRequest,
    FactorPortfolioConstraintRequest,
    FactorRobustnessRequest,
)
from apps.api.domains.factor_research.service import (
    analyze_factor_robustness,
    compare_factor_discovery_efficiency,
    validate_factor_portfolio_constraints,
)
from core.factor_robustness import (
    MARKET_PORTFOLIO_PROFILES,
    data_perturbation_test,
    nested_nonlinear_benchmark,
    orthogonalized_incremental_ic,
    parameter_plateau_test,
    pareto_rank,
    placebo_test,
    portfolio_incremental_value_report,
    simple_portfolio_benchmarks,
    validate_target_market_portfolio_constraints,
)


class FactorRobustnessTests(unittest.TestCase):
    def test_discovery_sources_are_compared_under_the_same_budget(self) -> None:
        candidates = []
        profiles = {
            "ai": [(True, False, True), (True, False, False), (False, False, False)],
            "template": [(True, False, False), (False, False, False), (False, False, False)],
            "random_dsl": [(True, True, False), (True, False, False), (False, False, False)],
            "symbolic_regression": [
                (True, False, False),
                (True, False, False),
                (False, False, False),
            ],
        }
        for source, rows in profiles.items():
            for index, (valid, duplicate, passed) in enumerate(rows, start=1):
                candidates.append(
                    {
                        "candidate_id": f"{source}-{index}",
                        "source": source,
                        "validation_passed": valid,
                        "duplicate": duplicate,
                        "research_passed": passed,
                        "compute_units": index,
                        "llm_tokens": 100 if source == "ai" else 0,
                    }
                )
        response = compare_factor_discovery_efficiency(
            FactorDiscoveryEfficiencyRequest(candidates=candidates, per_source_budget=3)
        )

        self.assertTrue(response["ok"])
        report = response["report"]
        self.assertEqual(report["fixed_candidate_budget"], 3)
        self.assertEqual({item["source"] for item in report["sources"]}, set(profiles))
        self.assertEqual(report["winner"], "ai")
        self.assertTrue(report["deterministic"])
        self.assertEqual(report["ai_vs_random_dsl"]["novel_valid_rate_delta"], 0.333334)
        self.assertTrue(report["ai_vs_random_dsl"]["reproducible_improvement_observed"])
        self.assertIn("失败候选", report["selection_bias_warning"])

    def test_service_exposes_all_requested_robustness_reports(self) -> None:
        factor = np.linspace(-1, 1, 80)
        response = analyze_factor_robustness(
            FactorRobustnessRequest(
                factor=factor.tolist(),
                label=(factor * 0.02).tolist(),
                deployed_factors={"existing": (factor**2).tolist()},
                parameter_results=[
                    {"period": 10, "ic": 0.04},
                    {"period": 20, "ic": 0.05},
                    {"period": 30, "ic": 0.04},
                ],
                parameter_name="period",
                parameter_metric="ic",
                parameter_threshold=0.03,
                pareto_candidates=[
                    {"key": "a", "ic": 0.05, "turnover": 0.2},
                    {"key": "b", "ic": 0.04, "turnover": 0.4},
                ],
                pareto_objectives={"ic": "maximize", "turnover": "minimize"},
                factor_returns={
                    "a": (factor * 0.01).tolist(),
                    "b": (np.sin(np.arange(80)) * 0.01).tolist(),
                },
                expected_ics={"a": 0.05, "b": 0.02},
                seed=7,
            )
        )

        self.assertTrue(response["ok"])
        self.assertTrue(response["deterministic"])
        self.assertFalse(response["dynamic_code_execution"])
        self.assertEqual(
            set(response["reports"]),
            {
                "placebo",
                "perturbation",
                "orthogonalization",
                "parameter_plateau",
                "pareto",
                "portfolio_benchmarks",
            },
        )

    def test_parameter_plateau_requires_adjacent_passing_values(self) -> None:
        report = parameter_plateau_test(
            [
                {"period": 5, "rank_ic": 0.01},
                {"period": 10, "rank_ic": 0.04},
                {"period": 15, "rank_ic": 0.05},
                {"period": 20, "rank_ic": 0.045},
                {"period": 30, "rank_ic": 0.01},
            ],
            parameter="period",
            metric="rank_ic",
            threshold=0.03,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["robust_parameters"], [10.0, 15.0, 20.0])
        self.assertEqual(report["plateaus"][0]["size"], 3)

    def test_pareto_rank_preserves_tradeoffs(self) -> None:
        ranked = pareto_rank(
            [
                {"key": "balanced", "ic": 0.05, "turnover": 0.3},
                {"key": "high_ic", "ic": 0.08, "turnover": 0.8},
                {"key": "dominated", "ic": 0.04, "turnover": 0.5},
            ],
            {"ic": "maximize", "turnover": "minimize"},
        )

        fronts = {item["key"] for item in ranked if item["pareto_front"]}
        self.assertEqual(fronts, {"balanced", "high_ic"})
        self.assertEqual(
            next(item for item in ranked if item["key"] == "dominated")["pareto_rank"], 2
        )

    def test_placebo_and_perturbation_gates_are_deterministic(self) -> None:
        rng = np.random.default_rng(17)
        factor = pd.Series(np.linspace(-2, 2, 400))
        label = factor * 0.02 + rng.normal(0, 0.003, len(factor))
        liquidity = pd.Series(np.linspace(1_000_000, 20_000_000, len(factor)))

        placebo = placebo_test(
            factor,
            label,
            permutations=100,
            random_factors=50,
            seed=9,
        )
        repeated = placebo_test(
            factor,
            label,
            permutations=100,
            random_factors=50,
            seed=9,
        )
        perturbation = data_perturbation_test(
            factor,
            label,
            liquidity=liquidity,
            seed=11,
        )

        self.assertEqual(placebo, repeated)
        self.assertTrue(placebo["passed"])
        self.assertLessEqual(placebo["empirical_p_value"], 0.05)
        self.assertEqual(placebo["pseudo_event_trials"], 100)
        self.assertEqual(
            {item["scenario"] for item in perturbation["scenarios"]},
            {
                "missing_values",
                "price_noise",
                "cost_increase",
                "execution_delay",
                "capacity_shrink",
            },
        )
        self.assertTrue(perturbation["passed"])

    def test_orthogonalization_reports_incremental_ic(self) -> None:
        rng = np.random.default_rng(101)
        deployed = rng.normal(size=500)
        alpha = np.sin(np.arange(500) / 11)
        candidate = deployed * 5 + alpha
        label = alpha + rng.normal(0, 0.05, 500)

        report = orthogonalized_incremental_ic(
            candidate,
            {"deployed_value": deployed},
            label,
        )

        self.assertGreater(report["incremental_rank_ic"], report["original_rank_ic"])
        self.assertLess(report["residual_variance_ratio"], 0.1)
        self.assertEqual(report["deployed_factor_count"], 1)

    def test_simple_portfolio_benchmarks_are_long_only_and_auditable(self) -> None:
        rng = np.random.default_rng(6)
        report = simple_portfolio_benchmarks(
            {
                "momentum": rng.normal(0.001, 0.01, 200),
                "quality": rng.normal(0.0008, 0.006, 200),
                "value": rng.normal(0.0005, 0.012, 200),
            },
            {"momentum": 0.05, "quality": 0.04, "value": 0.02},
            ridge_penalty=0.5,
        )

        self.assertEqual(
            {item["method"] for item in report["methods"]},
            {"equal_weight", "ic_weight", "risk_parity", "ridge_linear"},
        )
        for method in report["methods"]:
            self.assertAlmostEqual(sum(method["weights"].values()), 1.0, places=6)
            self.assertTrue(all(weight >= 0 for weight in method["weights"].values()))
            self.assertEqual(method["observations"], 100)
        self.assertEqual(report["outer_folds"], 3)
        self.assertEqual(len(report["folds"]), 3)
        self.assertTrue(
            all(fold["training_end_offset"] < fold["test_start_offset"] for fold in report["folds"])
        )
        self.assertFalse(report["confirmation_set_used_for_weight_selection"])
        self.assertFalse(report["nonlinear_models_included"])

    def test_incremental_value_reports_adoption_and_hard_risk_rejection(self) -> None:
        candidate = [0.01, 0.012, -0.004, 0.009, 0.008] * 20
        benchmark = [0.004, 0.005, -0.003, 0.003, 0.004] * 20
        turnover = [0.1] * len(candidate)

        adopted = portfolio_incremental_value_report(
            candidate,
            benchmark,
            candidate_turnover=turnover,
            benchmark_turnover=[0.05] * len(candidate),
            candidate_capacity=[2_000_000] * len(candidate),
            benchmark_capacity=[1_000_000] * len(candidate),
            transaction_cost_bps=10,
            risk_constraints={"maximum_drawdown": 0.2, "minimum_cvar_95": -0.05},
        )
        rejected = portfolio_incremental_value_report(
            candidate,
            benchmark,
            candidate_turnover=turnover,
            risk_constraints={"maximum_turnover": 0.01},
        )

        self.assertTrue(adopted["adopted"])
        self.assertIn("total_return", adopted["improved_objectives"])
        self.assertIn("capacity", adopted["improved_objectives"])
        self.assertFalse(rejected["adopted"])
        self.assertEqual(rejected["decision"], "research_valid_combination_not_adopted")
        self.assertIn("maximum_turnover", rejected["risk_violations"])

    def test_nonlinear_model_requires_stable_nested_outperformance(self) -> None:
        rng = np.random.default_rng(2026)
        first = rng.uniform(-2, 2, 240)
        second = rng.uniform(-1.5, 1.5, 240)
        nonlinear_label = (
            0.8 * first**2 - 0.6 * second**2 + 0.4 * first * second + rng.normal(0, 0.08, 240)
        )
        nonlinear = nested_nonlinear_benchmark(
            {"first": first, "second": second},
            nonlinear_label,
            minimum_improvement=0.05,
        )
        linear_label = 1.2 * first - 0.7 * second + rng.normal(0, 0.08, 240)
        linear = nested_nonlinear_benchmark(
            {"first": first, "second": second},
            linear_label,
            minimum_improvement=0.05,
        )

        self.assertTrue(nonlinear["eligible_for_simulation"])
        self.assertTrue(nonlinear["stable_outperformance"])
        self.assertFalse(linear["eligible_for_simulation"])
        self.assertTrue(nonlinear["nested_time_series_validation"])
        self.assertFalse(nonlinear["confirmation_set_used_for_selection"])
        self.assertTrue(
            all(
                fold["training_end_offset"] < fold["test_start_offset"]
                for fold in nonlinear["outer_folds"]
            )
        )

    def test_robustness_service_exposes_nonlinear_gate(self) -> None:
        rng = np.random.default_rng(8)
        first = rng.normal(size=120)
        second = rng.normal(size=120)
        response = analyze_factor_robustness(
            FactorRobustnessRequest(
                factor=first.tolist(),
                label=(first * 0.01).tolist(),
                nonlinear_features={"first": first.tolist(), "second": second.tolist()},
                nonlinear_label=(first**2 + second**2).tolist(),
            )
        )

        self.assertIn("nonlinear_benchmark", response["reports"])

    def test_target_market_profiles_and_constraint_gate(self) -> None:
        self.assertEqual(set(MARKET_PORTFOLIO_PROFILES), {"a_shares", "us_stocks", "crypto", "mt5"})
        self.assertEqual(
            len({profile["settlement"] for profile in MARKET_PORTFOLIO_PROFILES.values()}),
            3,
        )
        symbols = [f"stock_{index}" for index in range(10)]
        compliant = validate_target_market_portfolio_constraints(
            market="a_shares",
            weights={symbol: 0.1 for symbol in symbols},
            industries={symbol: "industry" for symbol in symbols},
            benchmark_industry_weights={"industry": 1.0},
            average_daily_values={symbol: 10_000_000 for symbol in symbols},
            proposed_trade_values={symbol: 500_000 for symbol in symbols},
            turnover=0.4,
        )
        rejected = validate_factor_portfolio_constraints(
            FactorPortfolioConstraintRequest(
                market="a_shares",
                weights={"short": -0.1, "large": 1.1},
                industries={"short": "finance", "large": "technology"},
                benchmark_industry_weights={"finance": 0.5, "technology": 0.5},
                average_daily_values={"short": 1_000_000, "large": 1_000_000},
                proposed_trade_values={"short": 200_000, "large": 200_000},
                turnover=0.8,
            )
        )["validation"]

        self.assertTrue(compliant["passed"])
        self.assertFalse(rejected["passed"])
        self.assertEqual(
            set(rejected["violations"]),
            {
                "long_only",
                "maximum_industry_deviation",
                "maximum_participation_rate",
                "maximum_turnover",
                "maximum_weight",
            },
        )


if __name__ == "__main__":
    unittest.main()

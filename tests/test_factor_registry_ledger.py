from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from apps.api import database, store
from apps.api.domains.factor_research import service
from apps.api.domains.factor_research.schemas import (
    FactorAiSearchRoundRequest,
    FactorCandidateValidationRequest,
    FactorConfirmationSetOpenRequest,
    FactorDefinitionCreate,
    FactorDefinitionRef,
    FactorExperimentCreate,
    FactorExperimentEventCreate,
    FactorLifecycleTransitionRequest,
    FactorPreRegistration,
    FactorRedundancyRequest,
    FactorResearchDataPartition,
    FactorResearchDataSplit,
    FactorResearchPlanCreate,
    TokenFormulaImportRequest,
)


def momentum_definition(
    *, key: str = "dsl_momentum", family: str = "momentum", periods: int = 20
) -> FactorDefinitionCreate:
    return FactorDefinitionCreate(
        key=key,
        label="DSL 动量",
        market="all",
        ast={
            "op": "pct_change",
            "periods": periods,
            "value": {"op": "field", "name": "close"},
        },
        family=family,
        parameters={"periods": periods},
        rationale="价格趋势可能在短期延续",
    )


def pre_registration(maximum_candidates: int = 4) -> FactorPreRegistration:
    return FactorPreRegistration(
        primary_metric="rank_ic_mean",
        secondary_metrics=["turnover", "coverage"],
        pass_criteria={"minimum_rank_ic": 0.03, "maximum_adjusted_p_value": 0.05},
        maximum_candidates=maximum_candidates,
        maximum_llm_tokens=20_000,
        confirmation_set_openings=0,
    )


class FactorRegistryLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db = store._DB
        self.temp_dir = Path(tempfile.mkdtemp(prefix="quanthub-factor-ledger-"))
        database.dispose_engines()
        store._DB = self.temp_dir / "store.db"
        store._init()

    def tearDown(self) -> None:
        database.dispose_engines()
        store._DB = self.original_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def register(self) -> dict:
        result = service.register_factor_definition(momentum_definition())
        self.assertTrue(result["ok"])
        validation = service.validate_factor_candidate_data(
            FactorCandidateValidationRequest(
                factor_key="dsl_momentum",
                rows=[{"close": float(value)} for value in range(1, 101)],
            )
        )
        self.assertTrue(validation["ok"])
        self.validation_id = validation["validation"]["id"]
        return result["definition"]

    @staticmethod
    def lifecycle_evidence(definition: dict, **extra) -> dict:
        return {
            "formula_definition_hash": definition["definition_hash"],
            "formula_hash": definition["formula_hash"],
            "formula_version": definition["version"],
            "data_snapshot_hash": "d" * 64,
            "cumulative_attempts": 1,
            "validation_window": {"start": "2021-01-01", "end": "2025-12-31"},
            "cost_profile_version": "a-share-cost-v1",
            "gate_version": "factor-gate-v1",
            **extra,
        }

    def test_builtin_fourteen_factors_are_seeded_idempotently(self) -> None:
        first = service.seed_builtin_factor_definitions()
        second = service.seed_builtin_factor_definitions()
        listed = service.list_registered_factor_definitions()

        self.assertEqual(first["count"], 14)
        self.assertEqual(second["count"], 14)
        self.assertEqual(listed["count"], 14)
        self.assertEqual(
            {item["key"] for item in listed["definitions"]},
            {
                "trend_strength",
                "momentum_20",
                "macd_histogram",
                "adx_direction",
                "mean_reversion",
                "rsi_reversal",
                "bollinger_reversal",
                "breakout_20",
                "volume_confirmation",
                "obv_momentum",
                "chaikin_flow",
                "low_volatility",
                "atr_contraction",
                "downside_risk",
            },
        )
        self.assertTrue(
            all(item["ast"]["op"] == "builtin_factor" for item in listed["definitions"])
        )

    def test_factor_lifecycle_is_append_only_and_program_gate_locked(self) -> None:
        definition = self.register()
        self.create_plan("plan-lifecycle")
        experiment = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id="plan-lifecycle",
                hypothesis="锁定样本外门禁生命周期测试",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                parameter_grid={"periods": [20]},
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )["experiment"]
        for status in ("queued", "running"):
            service.append_factor_experiment_event(
                experiment["id"], FactorExperimentEventCreate(status=status)
            )
        service.append_factor_experiment_event(
            experiment["id"],
            FactorExperimentEventCreate(
                status="succeeded",
                result={
                    "candidate_results": [
                        {
                            "candidate_key": "momentum_20",
                            "raw_p_value": 0.01,
                            "effective_sample_size": 180,
                        }
                    ]
                },
            ),
        )

        exploratory = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="exploratory",
                target_market="a_shares",
                actor="researcher-1",
                rule="candidate_approved",
                evidence=self.lifecycle_evidence(definition),
            ),
        )
        unstable = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="research_passed",
                target_market="a_shares",
                actor_type="system",
                actor="statistical-gate",
                rule="locked_out_of_sample_statistical_gate",
                evidence=self.lifecycle_evidence(
                    definition,
                    locked_out_of_sample=True,
                    statistical_gate_passed=True,
                    ai_accessed_locked_labels=False,
                    window_majority_passed=True,
                    group_stability_passed=True,
                    parameter_plateau_passed=False,
                    research_plan_id="plan-lifecycle",
                    experiment_ids=[experiment["id"]],
                ),
            ),
        )
        research_passed = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="research_passed",
                target_market="a_shares",
                actor_type="system",
                actor="statistical-gate",
                rule="locked_out_of_sample_statistical_gate",
                evidence=self.lifecycle_evidence(
                    definition,
                    locked_out_of_sample=True,
                    statistical_gate_passed=True,
                    ai_accessed_locked_labels=False,
                    window_majority_passed=True,
                    group_stability_passed=True,
                    parameter_plateau_passed=True,
                    research_plan_id="plan-lifecycle",
                    experiment_ids=[experiment["id"]],
                ),
            ),
        )
        incomplete_simulation = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="trading_validated",
                target_market="a_shares",
                actor_type="system",
                actor="trading-gate",
                rule="target_market_trading_gate",
                evidence=self.lifecycle_evidence(
                    definition,
                    cost_passed=True,
                    capacity_passed=True,
                    execution_passed=True,
                    incremental_value_passed=True,
                    simulation_validation_passed=True,
                    after_cost_performance_passed=True,
                    fill_rate_passed=True,
                    completed_rebalance_cycles=0,
                    execution_record_count=20,
                    simulation_run_id="paper-run-incomplete",
                    observation_started_at="2026-08-01T00:00:00+00:00",
                    observation_ended_at="2026-08-08T00:00:00+00:00",
                    observation_days_completed=7,
                    observation_period_completed=True,
                ),
            ),
        )
        short_simulation = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="trading_validated",
                target_market="a_shares",
                actor_type="system",
                actor="trading-gate",
                rule="target_market_trading_gate",
                evidence=self.lifecycle_evidence(
                    definition,
                    cost_passed=True,
                    capacity_passed=True,
                    execution_passed=True,
                    incremental_value_passed=True,
                    simulation_validation_passed=True,
                    after_cost_performance_passed=True,
                    fill_rate_passed=True,
                    completed_rebalance_cycles=1,
                    execution_record_count=20,
                    simulation_run_id="paper-run-short",
                    observation_started_at="2026-08-01T00:00:00+00:00",
                    observation_ended_at="2026-08-07T23:59:59+00:00",
                    observation_days_completed=6.99998,
                    observation_period_completed=True,
                ),
            ),
        )
        trading_validated = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="trading_validated",
                target_market="a_shares",
                actor_type="system",
                actor="trading-gate",
                rule="target_market_trading_gate",
                evidence=self.lifecycle_evidence(
                    definition,
                    cost_passed=True,
                    capacity_passed=True,
                    execution_passed=True,
                    incremental_value_passed=True,
                    simulation_validation_passed=True,
                    after_cost_performance_passed=True,
                    fill_rate_passed=True,
                    completed_rebalance_cycles=1,
                    execution_record_count=20,
                    simulation_run_id="paper-run-001",
                    observation_started_at="2026-08-01T00:00:00+00:00",
                    observation_ended_at="2026-08-08T00:00:00+00:00",
                    observation_days_completed=7,
                    observation_period_completed=True,
                ),
            ),
        )
        degraded = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="degraded",
                target_market="a_shares",
                actor_type="system",
                actor="drift-monitor",
                rule="ic_decay",
                evidence=self.lifecycle_evidence(
                    definition,
                    degradation_reason="监控期 IC 衰减",
                ),
            ),
        )
        premature_retirement = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="retired",
                target_market="a_shares",
                actor="risk-reviewer",
                rule="retirement_review",
                evidence=self.lifecycle_evidence(
                    definition,
                    observed_periods=2,
                    required_observation_periods=5,
                    human_reviewed=True,
                    retirement_reason="持续衰减",
                ),
            ),
        )
        retired = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="retired",
                target_market="a_shares",
                actor="risk-reviewer",
                rule="retirement_review",
                evidence=self.lifecycle_evidence(
                    definition,
                    observed_periods=5,
                    required_observation_periods=5,
                    human_reviewed=True,
                    retirement_reason="持续衰减且恢复门禁未通过",
                ),
            ),
        )
        history = service.get_factor_lifecycle("dsl_momentum", "1.0.0", "a_shares")

        self.assertTrue(exploratory["ok"])
        self.assertFalse(unstable["ok"])
        self.assertIn("parameter_plateau_passed=True", unstable["error"])
        self.assertTrue(research_passed["ok"])
        self.assertFalse(incomplete_simulation["ok"])
        self.assertIn("完整模拟再平衡周期", incomplete_simulation["error"])
        self.assertFalse(short_simulation["ok"])
        self.assertIn("至少 7 个真实自然日", short_simulation["error"])
        self.assertTrue(trading_validated["ok"])
        self.assertTrue(degraded["ok"])
        self.assertFalse(premature_retirement["ok"])
        self.assertIn("观察周期", premature_retirement["error"])
        self.assertTrue(retired["ok"])
        self.assertEqual(history["current_by_market"]["a_shares"]["state"], "retired")
        self.assertEqual(
            [item["event_sequence"] for item in history["events"]],
            [1, 2, 3, 4, 5, 6],
        )
        self.assertEqual(
            history["events"][2]["evidence"]["formula_definition_hash"],
            definition["definition_hash"],
        )

    def test_ai_and_training_selection_cannot_upgrade_lifecycle(self) -> None:
        definition = self.register()
        ai_attempt = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="exploratory",
                target_market="a_shares",
                actor_type="ai",
                actor="review-model",
                rule="candidate_approved",
                evidence=self.lifecycle_evidence(definition),
            ),
        )
        training_attempt = service.transition_factor_lifecycle(
            "dsl_momentum",
            "1.0.0",
            FactorLifecycleTransitionRequest(
                state="exploratory",
                target_market="a_shares",
                actor_type="system",
                actor="training-ranker",
                rule="training_selected",
                evidence=self.lifecycle_evidence(definition),
            ),
        )

        self.assertFalse(ai_attempt["ok"])
        self.assertIn("不能修改因子生命周期", ai_attempt["error"])
        self.assertFalse(training_attempt["ok"])
        self.assertIn("候选批准或覆盖率门禁", training_attempt["error"])
        history = service.get_factor_lifecycle("dsl_momentum", "1.0.0", "a_shares")
        self.assertEqual([item["state"] for item in history["events"]], ["draft"])

    def test_token_formula_import_persists_both_engine_vocabularies(self) -> None:
        crypto = service.import_token_formula_definitions(
            TokenFormulaImportRequest(
                engine="alphagpt",
                formulas=[[4, 15], [2, 3, 8]],
                key_prefix="crypto_ai",
                label_prefix="Crypto AI",
            )
        )
        mt5 = service.import_token_formula_definitions(
            TokenFormulaImportRequest(
                engine="alphamaster",
                formulas=[[2], [9], [23]],
                key_prefix="mt5_ai",
                label_prefix="MT5 AI",
            )
        )

        self.assertTrue(crypto["ok"])
        self.assertTrue(mt5["ok"])
        self.assertEqual(crypto["count"], 2)
        self.assertEqual(mt5["count"], 3)
        restored = service.get_registered_factor_definition("mt5_ai_003", "1.0.0")
        self.assertEqual(restored["definition"]["ast"]["engine"], "alphamaster")
        self.assertEqual(restored["definition"]["parameters"]["token_names"], ["MACD_HIST"])

        invalid = service.import_token_formula_definitions(
            TokenFormulaImportRequest(
                engine="alphagpt",
                formulas=[[6]],
                key_prefix="invalid_ai",
            )
        )
        self.assertFalse(invalid["ok"])
        self.assertIn("缺少操作数", invalid["error"])

    def create_plan(
        self,
        plan_id: str,
        *,
        maximum_candidates: int = 20,
        maximum_compute_units: int = 1_000,
        maximum_llm_tokens: int = 100_000,
        maximum_round_candidates: int = 100,
        maximum_formula_complexity: int = 30,
        maximum_duplicate_rate: float = 0.25,
        stop_conditions: dict | None = None,
        data_split: FactorResearchDataSplit | None = None,
    ) -> dict:
        result = service.create_factor_research_plan_record(
            FactorResearchPlanCreate(
                id=plan_id,
                title=f"研究计划 {plan_id}",
                target_market="a_shares",
                maximum_candidates=maximum_candidates,
                maximum_compute_units=maximum_compute_units,
                maximum_llm_tokens=maximum_llm_tokens,
                maximum_confirmation_set_openings=1,
                maximum_round_candidates=maximum_round_candidates,
                maximum_formula_complexity=maximum_formula_complexity,
                maximum_duplicate_rate=maximum_duplicate_rate,
                stop_conditions=stop_conditions or {},
                data_split=data_split,
            )
        )
        self.assertTrue(result["ok"])
        return result["plan"]

    def test_definition_registry_is_versioned_validated_and_restorable(self) -> None:
        saved = self.register()

        self.assertEqual(saved["input_fields"], ["close"])
        self.assertEqual(saved["validation"]["shape"], "series")
        self.assertEqual(len(saved["formula_hash"]), 64)
        restored = service.get_registered_factor_definition("dsl_momentum", "1.0.0")
        self.assertEqual(restored["definition"]["definition_hash"], saved["definition_hash"])

        changed_without_version = service.register_factor_definition(
            momentum_definition(periods=60)
        )
        self.assertFalse(changed_without_version["ok"])
        self.assertIn("必须提升版本", changed_without_version["error"])

        invalid = service.register_factor_definition(
            FactorDefinitionCreate(
                key="future_factor",
                label="未来函数",
                market="all",
                ast={
                    "op": "lag",
                    "periods": -1,
                    "value": {"op": "field", "name": "close"},
                },
            )
        )
        self.assertFalse(invalid["ok"])
        self.assertIn("未来数据", invalid["error"])

    def test_explicit_alias_is_allowed_but_undeclared_duplicate_is_rejected(self) -> None:
        canonical = self.register()
        alias = service.register_factor_definition(
            momentum_definition(key="dsl_momentum_alias", family="momentum")
        )
        duplicate = service.register_factor_definition(
            momentum_definition(key="renamed_duplicate", family="another_hypothesis")
        )

        self.assertTrue(alias["ok"])
        self.assertEqual(alias["definition"]["formula_hash"], canonical["formula_hash"])
        self.assertFalse(duplicate["ok"])
        self.assertIn("完全重复", duplicate["error"])

    def test_candidate_cannot_enter_experiment_without_real_data_coverage_proof(self) -> None:
        self.register()
        self.create_plan("plan-validation-gate")
        insufficient = service.validate_factor_candidate_data(
            FactorCandidateValidationRequest(
                factor_key="dsl_momentum",
                rows=[{"close": float(value)} for value in range(1, 10)],
            )
        )
        blocked = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id="plan-validation-gate",
                hypothesis="伪造验证凭证应被拒绝",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id="missing-validation",
                target_market="a_shares",
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )

        self.assertFalse(insufficient["ok"])
        self.assertIn("没有任何有效值", insufficient["error"])
        self.assertFalse(blocked["ok"])
        self.assertIn("覆盖率验证", blocked["error"])

    def test_persisted_definitions_can_run_redundancy_analysis(self) -> None:
        self.register()
        scaled = service.register_factor_definition(
            FactorDefinitionCreate(
                key="dsl_momentum_scaled",
                label="两倍动量",
                market="all",
                ast={
                    "op": "mul",
                    "left": {
                        "op": "pct_change",
                        "periods": 20,
                        "value": {"op": "field", "name": "close"},
                    },
                    "right": {"op": "const", "value": 2},
                },
                family="momentum",
            )
        )
        report = service.analyze_factor_redundancy(
            FactorRedundancyRequest(
                definitions=[
                    FactorDefinitionRef(key="dsl_momentum"),
                    FactorDefinitionRef(key="dsl_momentum_scaled"),
                ],
                rows=[
                    {
                        "close": float(value),
                        "market_regime": "trend" if value <= 100 else "range",
                    }
                    for value in range(1, 201)
                ],
            )
        )

        self.assertTrue(scaled["ok"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["redundant_count"], 1)
        self.assertEqual(report["redundant_pairs"][0]["relation"], "constant_multiple")
        self.assertAlmostEqual(report["redundant_pairs"][0]["scale"], 2.0)
        self.assertAlmostEqual(report["correlation_pairs"][0]["tail_pearson"], 1.0)
        self.assertEqual(
            {item["regime"] for item in report["correlation_pairs"][0]["regime_correlations"]},
            {"range", "trend"},
        )

    def test_experiment_ledger_preserves_preregistration_ai_metadata_and_attempts(self) -> None:
        self.register()
        self.create_plan("plan-momentum-a-share")
        request = FactorExperimentCreate(
            research_plan_id="plan-momentum-a-share",
            hypothesis="20 日动量在 A 股横截面具有正向 Rank IC",
            source="ai",
            factor_key="dsl_momentum",
            candidate_validation_id=self.validation_id,
            target_market="a_shares",
            data_start=date(2021, 1, 1),
            data_end=date(2025, 12, 31),
            parameter_grid={"periods": [10, 20], "horizon": [1, 5]},
            model={"provider": "openai", "model": "gpt-5.6-sol", "temperature": 0},
            prompt={"version": "factor-proposal-v1", "input_fingerprint": "a" * 64},
            applicable_regimes=["趋势市场", "高流动性"],
            invalidation_conditions=["成本后 Rank IC 连续三个窗口低于零"],
            falsification_tests=["标签打乱", "参数平台测试"],
            ai_trace={"token_usage": {"total_tokens": 1200}, "output_raw": "原始结构化提案"},
            pre_registration=pre_registration(),
        )

        first = service.create_factor_experiment_record(request)
        second = service.create_factor_experiment_record(
            request.model_copy(
                update={
                    "source": "parameter_search",
                    "parent_experiment_id": first["experiment"]["id"],
                    "model": {},
                    "prompt": {},
                }
            )
        )
        listed = service.list_factor_experiment_records(research_plan_id="plan-momentum-a-share")

        self.assertTrue(first["ok"])
        self.assertTrue(first["statistical_status_locked"])
        self.assertEqual(first["experiment"]["parameter_combinations"], 4)
        self.assertEqual(first["experiment"]["attempt_number"], 1)
        self.assertEqual(
            first["experiment"]["proposal"]["ai_trace"]["token_usage"]["total_tokens"],
            1200,
        )
        provenance = first["experiment"]["provenance"]
        self.assertEqual(provenance["schema_version"], "factor-experiment-provenance-v1")
        self.assertEqual(provenance["model"]["version"], "gpt-5.6-sol")
        self.assertEqual(provenance["prompt"]["version"], "factor-proposal-v1")
        self.assertTrue(
            all(
                len(provenance[key]["hash"]) == 64
                for key in ("experiment", "model", "prompt", "cost", "result")
            )
        )
        self.assertEqual(second["experiment"]["attempt_number"], 2)
        self.assertEqual(listed["cumulative_attempts"], 2)
        self.assertEqual(listed["experiments"][1]["model"]["model"], "gpt-5.6-sol")

    def test_failed_experiment_is_append_only_and_retry_requires_new_record(self) -> None:
        self.register()
        self.create_plan("plan-failure-audit")
        created = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id="plan-failure-audit",
                hypothesis="检验失败记录能否完整保留",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                parameter_grid={"periods": [20]},
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )["experiment"]

        queued = service.append_factor_experiment_event(
            created["id"], FactorExperimentEventCreate(status="queued")
        )
        running = service.append_factor_experiment_event(
            created["id"], FactorExperimentEventCreate(status="running")
        )
        failed = service.append_factor_experiment_event(
            created["id"],
            FactorExperimentEventCreate(
                status="failed",
                failure_reason="有效样本覆盖不足",
                failure_code="insufficient_coverage",
                evidence={"coverage": 0.42, "required": 0.8},
            ),
        )
        invalid_retry = service.append_factor_experiment_event(
            created["id"], FactorExperimentEventCreate(status="queued")
        )

        self.assertTrue(queued["ok"])
        self.assertTrue(running["ok"])
        self.assertEqual(failed["experiment"]["status"], "failed")
        self.assertEqual(len(failed["experiment"]["events"]), 4)
        self.assertEqual(
            [item["event_sequence"] for item in failed["experiment"]["events"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(failed["experiment"]["events"][-1]["evidence"]["coverage"], 0.42)
        self.assertEqual(
            failed["experiment"]["events"][-1]["failure_code"],
            "insufficient_coverage",
        )
        self.assertFalse(invalid_retry["ok"])
        self.assertIn("重试必须新建实验记录", invalid_retry["error"])

    def test_candidate_and_ai_contract_budgets_are_enforced(self) -> None:
        self.register()
        self.create_plan("plan-budget", maximum_candidates=3)
        over_budget = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id="plan-budget",
                hypothesis="参数预算测试",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                parameter_grid={"periods": [10, 20], "horizon": [1, 5]},
                pre_registration=pre_registration(maximum_candidates=3),
            )
        )
        self.assertFalse(over_budget["ok"])
        self.assertIn("maximum_candidates", over_budget["error"])

        with self.assertRaisesRegex(ValidationError, "provider"):
            FactorExperimentCreate(
                research_plan_id="plan-ai-metadata",
                hypothesis="缺少 AI 元数据",
                source="ai",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                pre_registration=pre_registration(),
            )

    def test_research_plan_is_immutable_and_enforces_total_compute_budget(self) -> None:
        self.register()
        plan = self.create_plan(
            "plan-compute-budget",
            maximum_candidates=10,
            maximum_compute_units=5,
        )
        first = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id=plan["id"],
                hypothesis="第一次计算预算占用",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                estimated_compute_units=4,
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )
        second = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id=plan["id"],
                hypothesis="第二次计算预算占用",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                estimated_compute_units=2,
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )
        changed_plan = service.create_factor_research_plan_record(
            FactorResearchPlanCreate(
                id=plan["id"],
                title="试图修改既有计划",
                target_market="a_shares",
                maximum_candidates=100,
                maximum_compute_units=100,
            )
        )
        detail = service.get_factor_research_plan_record(plan["id"])

        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertIn("maximum_compute_units", second["error"])
        self.assertFalse(changed_plan["ok"])
        self.assertIn("不可修改", changed_plan["error"])
        self.assertEqual(detail["usage"]["compute_units"], 4)

    def test_confirmation_data_split_requires_ordered_hashed_partitions(self) -> None:
        with self.assertRaisesRegex(ValidationError, "发现集必须早于滚动验证集"):
            FactorResearchDataSplit(
                discovery=FactorResearchDataPartition(
                    start=date(2022, 1, 1), end=date(2023, 1, 1), data_fingerprint="a" * 64
                ),
                rolling_validation=FactorResearchDataPartition(
                    start=date(2023, 1, 1), end=date(2024, 1, 1), data_fingerprint="b" * 64
                ),
                locked_confirmation=FactorResearchDataPartition(
                    start=date(2025, 1, 1), end=date(2025, 12, 31), data_fingerprint="c" * 64
                ),
                purge_periods=5,
                embargo_periods=2,
            )
        with self.assertRaisesRegex(ValidationError, "64 characters"):
            FactorResearchDataPartition(
                start=date(2020, 1, 1), end=date(2021, 1, 1), data_fingerprint="not-a-hash"
            )
        with self.assertRaisesRegex(ValidationError, "明确确认不可逆"):
            FactorConfirmationSetOpenRequest(
                experiment_id="experiment",
                confirmation_data_fingerprint="c" * 64,
                opened_by="researcher",
                irreversible_ack=False,
            )

    def test_confirmation_set_can_open_once_and_blocks_further_tuning(self) -> None:
        self.register()
        data_split = FactorResearchDataSplit(
            discovery=FactorResearchDataPartition(
                start=date(2020, 1, 1), end=date(2021, 12, 31), data_fingerprint="a" * 64
            ),
            rolling_validation=FactorResearchDataPartition(
                start=date(2022, 1, 10), end=date(2024, 12, 31), data_fingerprint="b" * 64
            ),
            locked_confirmation=FactorResearchDataPartition(
                start=date(2025, 1, 10), end=date(2025, 12, 31), data_fingerprint="c" * 64
            ),
            purge_periods=5,
            embargo_periods=2,
        )
        plan = self.create_plan("plan-locked-confirmation", data_split=data_split)
        preregistered = pre_registration(maximum_candidates=1).model_copy(
            update={"confirmation_set_openings": 1}
        )
        experiment = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id=plan["id"],
                hypothesis="在锁定确认集开启前完成预注册滚动验证",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                data_start=date(2020, 1, 1),
                data_end=date(2024, 12, 31),
                pre_registration=preregistered,
            )
        )["experiment"]
        request = FactorConfirmationSetOpenRequest(
            experiment_id=experiment["id"],
            confirmation_data_fingerprint="c" * 64,
            opened_by="researcher-a",
            irreversible_ack=True,
        )

        premature = service.open_factor_confirmation_set(plan["id"], request)
        self.assertFalse(premature["ok"])
        self.assertIn("已成功完成", premature["error"])

        for status in ("queued", "running"):
            service.append_factor_experiment_event(
                experiment["id"], FactorExperimentEventCreate(status=status)
            )
        service.append_factor_experiment_event(
            experiment["id"],
            FactorExperimentEventCreate(
                status="succeeded",
                result={
                    "candidate_results": [
                        {
                            "candidate_key": "momentum_20",
                            "raw_p_value": 0.02,
                            "effective_sample_size": 220,
                        }
                    ]
                },
            ),
        )

        mismatch = service.open_factor_confirmation_set(
            plan["id"],
            request.model_copy(update={"confirmation_data_fingerprint": "d" * 64}),
        )
        self.assertFalse(mismatch["ok"])
        self.assertIn("数据指纹", mismatch["error"])

        opened = service.open_factor_confirmation_set(plan["id"], request)
        replay = service.open_factor_confirmation_set(plan["id"], request)
        changed = service.open_factor_confirmation_set(
            plan["id"], request.model_copy(update={"opened_by": "researcher-b"})
        )
        detail = service.get_factor_confirmation_set_opening(plan["id"])
        blocked = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id=plan["id"],
                hypothesis="查看确认集后继续调参应被阻止",
                source="parameter_search",
                parent_experiment_id=experiment["id"],
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                data_start=date(2020, 1, 1),
                data_end=date(2024, 12, 31),
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )

        self.assertTrue(opened["ok"])
        self.assertFalse(opened["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(changed["ok"])
        self.assertTrue(detail["opened"])
        self.assertEqual(detail["opening"]["experiment_id"], experiment["id"])
        self.assertFalse(blocked["ok"])
        self.assertIn("新的研究计划", blocked["error"])
        usage = service.get_factor_research_plan_record(plan["id"])["usage"]
        self.assertEqual(usage["confirmation_set_openings"], 1)
        self.assertEqual(usage["confirmation_set_openings_reserved"], 1)

    def test_confirmation_set_requires_preregistered_opening_budget(self) -> None:
        self.register()
        data_split = FactorResearchDataSplit(
            discovery=FactorResearchDataPartition(
                start=date(2020, 1, 1), end=date(2021, 12, 31), data_fingerprint="a" * 64
            ),
            rolling_validation=FactorResearchDataPartition(
                start=date(2022, 1, 10), end=date(2024, 12, 31), data_fingerprint="b" * 64
            ),
            locked_confirmation=FactorResearchDataPartition(
                start=date(2025, 1, 10), end=date(2025, 12, 31), data_fingerprint="c" * 64
            ),
            purge_periods=5,
            embargo_periods=2,
        )
        plan = self.create_plan("plan-no-opening-prereg", data_split=data_split)
        experiment = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id=plan["id"],
                hypothesis="未预注册确认集开启",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                data_start=date(2020, 1, 1),
                data_end=date(2024, 12, 31),
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )["experiment"]
        for status in ("queued", "running"):
            service.append_factor_experiment_event(
                experiment["id"], FactorExperimentEventCreate(status=status)
            )
        service.append_factor_experiment_event(
            experiment["id"],
            FactorExperimentEventCreate(
                status="succeeded",
                result={
                    "candidate_results": [
                        {
                            "candidate_key": "momentum_20",
                            "raw_p_value": 0.02,
                            "effective_sample_size": 220,
                        }
                    ]
                },
            ),
        )
        blocked = service.open_factor_confirmation_set(
            plan["id"],
            FactorConfirmationSetOpenRequest(
                experiment_id=experiment["id"],
                confirmation_data_fingerprint="c" * 64,
                opened_by="researcher",
                irreversible_ack=True,
            ),
        )

        self.assertFalse(blocked["ok"])
        self.assertIn("未预注册", blocked["error"])

    def test_multiple_testing_uses_all_terminal_candidates_in_the_plan(self) -> None:
        self.register()
        self.create_plan("plan-global-bh", maximum_candidates=3)
        first = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id="plan-global-bh",
                hypothesis="第一批两个参数候选",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                parameter_grid={"periods": [10, 20]},
                pre_registration=pre_registration(maximum_candidates=2),
            )
        )["experiment"]
        for status in ("queued", "running"):
            service.append_factor_experiment_event(
                first["id"], FactorExperimentEventCreate(status=status)
            )
        succeeded = service.append_factor_experiment_event(
            first["id"],
            FactorExperimentEventCreate(
                status="succeeded",
                result={
                    "candidate_results": [
                        {
                            "candidate_key": "momentum_10",
                            "raw_p_value": 0.01,
                            "effective_sample_size": 180,
                            "excess_returns": [
                                0.01 + ((index % 5) - 2) * 0.001 for index in range(60)
                            ],
                        },
                        {
                            "candidate_key": "momentum_20",
                            "raw_p_value": 0.04,
                            "effective_sample_size": 175,
                            "excess_returns": [
                                0.002 + ((index % 7) - 3) * 0.001 for index in range(60)
                            ],
                        },
                    ]
                },
            ),
        )
        second = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id="plan-global-bh",
                hypothesis="失败候选也保留在累计试验中",
                source="parameter_search",
                parent_experiment_id=first["id"],
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                parameter_grid={"periods": [60]},
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )["experiment"]
        for status in ("queued", "running"):
            service.append_factor_experiment_event(
                second["id"], FactorExperimentEventCreate(status=status)
            )
        service.append_factor_experiment_event(
            second["id"],
            FactorExperimentEventCreate(
                status="failed",
                failure_reason="覆盖不足",
                failure_code="insufficient_coverage",
            ),
        )

        report = service.factor_plan_multiple_testing("plan-global-bh")

        self.assertTrue(succeeded["ok"])
        self.assertEqual(report["cumulative_registered_candidates"], 3)
        self.assertEqual(report["corrected_candidates"], 3)
        self.assertEqual(report["rows"][0]["batch_adjusted_p_value"], 0.02)
        self.assertAlmostEqual(report["rows"][0]["global_adjusted_p_value"], 0.03)
        self.assertAlmostEqual(report["rows"][1]["global_adjusted_p_value"], 0.06)
        self.assertEqual(report["rows"][2]["global_adjusted_p_value"], 1.0)
        self.assertEqual(report["rows"][2]["experiment_status"], "failed")
        self.assertIn("deflated_sharpe", report["rows"][0])
        self.assertEqual(report["rows"][0]["deflated_sharpe"]["trials"], 3)
        self.assertTrue(report["reality_check"]["available"])
        self.assertLess(report["reality_check"]["p_value"], 0.05)

    def test_ai_proposal_context_contains_catalog_failures_clusters_and_budget(self) -> None:
        self.register()
        self.create_plan(
            "plan-ai-context",
            maximum_candidates=10,
            maximum_round_candidates=5,
            maximum_formula_complexity=20,
            maximum_duplicate_rate=0.2,
            stop_conditions={"maximum_rounds": 2},
        )
        experiment = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id="plan-ai-context",
                hypothesis="为下一轮保留结构化失败反馈",
                source="human",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                pre_registration=pre_registration(maximum_candidates=1),
            )
        )["experiment"]
        for status in ("queued", "running"):
            service.append_factor_experiment_event(
                experiment["id"], FactorExperimentEventCreate(status=status)
            )
        service.append_factor_experiment_event(
            experiment["id"],
            FactorExperimentEventCreate(
                status="failed",
                failure_reason="历史覆盖不足",
                failure_code="insufficient_coverage",
            ),
        )

        result = service.factor_ai_proposal_context("plan-ai-context")
        context = result["context"]

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["context_fingerprint"]), 64)
        self.assertIn("close", {item["field"] for item in context["data_catalog"]})
        self.assertIn(
            "dsl_momentum",
            {item["key"] for item in context["existing_factor_definitions"]},
        )
        self.assertIn("family", context["redundancy_clusters"])
        self.assertEqual(context["failure_feedback"]["insufficient_coverage"]["count"], 1)
        self.assertEqual(context["remaining_budget"]["candidates"], 9)
        self.assertEqual(context["remaining_budget"]["maximum_formula_complexity"], 20)
        self.assertFalse(context["confirmation_labels_exposed"])

    def test_ai_search_round_gates_are_persisted_and_immutable(self) -> None:
        self.create_plan(
            "plan-ai-rounds",
            maximum_candidates=7,
            maximum_llm_tokens=2_000,
            maximum_round_candidates=4,
            maximum_formula_complexity=12,
            maximum_duplicate_rate=0.25,
            stop_conditions={"maximum_rounds": 2, "minimum_novel_candidates": 2},
        )
        request = FactorAiSearchRoundRequest(
            round_id="round-001",
            candidate_count=4,
            duplicate_count=1,
            formula_complexities=[8, 9, 10, 12],
            llm_tokens=1_000,
            input_fingerprint="a" * 64,
            approved_by="researcher-1",
            approved_candidate_ids=["hypothesis-001"],
            budget_approved_ack=True,
        )

        allowed = service.validate_factor_ai_search_round("plan-ai-rounds", request)
        replay = service.validate_factor_ai_search_round("plan-ai-rounds", request)
        conflict = service.validate_factor_ai_search_round(
            "plan-ai-rounds",
            request.model_copy(update={"candidate_count": 3, "formula_complexities": [8, 9, 10]}),
        )
        approval_conflict = service.validate_factor_ai_search_round(
            "plan-ai-rounds",
            request.model_copy(update={"approved_by": "different-researcher"}),
        )
        stopped = service.validate_factor_ai_search_round(
            "plan-ai-rounds",
            FactorAiSearchRoundRequest(
                round_id="round-002",
                candidate_count=4,
                duplicate_count=2,
                formula_complexities=[8, 9, 10, 13],
                llm_tokens=1_500,
                input_fingerprint="b" * 64,
                approved_by="researcher-1",
                approved_candidate_ids=["hypothesis-002"],
                budget_approved_ack=True,
            ),
        )
        after_stop = service.validate_factor_ai_search_round(
            "plan-ai-rounds",
            FactorAiSearchRoundRequest(
                round_id="round-003",
                candidate_count=1,
                formula_complexities=[1],
                input_fingerprint="c" * 64,
                approved_by="researcher-1",
                approved_candidate_ids=["hypothesis-003"],
                budget_approved_ack=True,
            ),
        )
        listed = service.list_factor_ai_search_round_records("plan-ai-rounds")

        self.assertTrue(allowed["round"]["allowed"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(conflict["ok"])
        self.assertFalse(approval_conflict["ok"])
        self.assertEqual(allowed["round"]["approval"]["approved_by"], "researcher-1")
        self.assertTrue(stopped["round"]["stopped"])
        self.assertIn("duplicate_rate_budget", stopped["gate_violations"])
        self.assertIn("formula_complexity_budget", stopped["gate_violations"])
        self.assertIn("total_candidate_budget", stopped["gate_violations"])
        self.assertIn("total_llm_token_budget", stopped["gate_violations"])
        self.assertTrue(after_stop["round"]["stopped"])
        self.assertIn("search_already_stopped", after_stop["gate_violations"])
        self.assertEqual(listed["count"], 3)
        self.assertEqual(listed["usage"]["candidates"], 9)

    def test_ai_batch_of_one_hundred_candidates_is_corrected_as_one_plan(self) -> None:
        self.register()
        self.create_plan(
            "plan-ai-100",
            maximum_candidates=100,
            maximum_compute_units=10_000,
            maximum_llm_tokens=50_000,
        )
        experiment = service.create_factor_experiment_record(
            FactorExperimentCreate(
                research_plan_id="plan-ai-100",
                hypothesis="固定预算下批量生成 100 个参数候选",
                source="ai",
                factor_key="dsl_momentum",
                candidate_validation_id=self.validation_id,
                target_market="a_shares",
                parameter_grid={"candidate": list(range(100))},
                estimated_compute_units=1_000,
                model={"provider": "openai", "model": "gpt-5.6-sol", "temperature": 0},
                prompt={"version": "batch-v1", "input_fingerprint": "b" * 64},
                invalidation_conditions=["全局校正后不显著"],
                falsification_tests=["标签打乱"],
                ai_trace={"token_usage": {"total_tokens": 5000}, "output_raw": "100 candidates"},
                pre_registration=FactorPreRegistration(
                    primary_metric="rank_ic_mean",
                    pass_criteria={"maximum_global_p_value": 0.05},
                    maximum_candidates=100,
                    maximum_llm_tokens=10_000,
                ),
            )
        )["experiment"]
        for status in ("queued", "running"):
            service.append_factor_experiment_event(
                experiment["id"], FactorExperimentEventCreate(status=status)
            )
        candidates = [
            {
                "candidate_key": f"ai_candidate_{index:03d}",
                "raw_p_value": (index + 1) / 1_000,
                "effective_sample_size": 200,
            }
            for index in range(100)
        ]
        completed = service.append_factor_experiment_event(
            experiment["id"],
            FactorExperimentEventCreate(
                status="succeeded", result={"candidate_results": candidates}
            ),
        )

        report = service.factor_plan_multiple_testing("plan-ai-100")

        self.assertTrue(completed["ok"])
        self.assertEqual(report["corrected_candidates"], 100)
        self.assertEqual(report["cumulative_registered_candidates"], 100)
        self.assertTrue(all("global_adjusted_p_value" in row for row in report["rows"]))


if __name__ == "__main__":
    unittest.main()

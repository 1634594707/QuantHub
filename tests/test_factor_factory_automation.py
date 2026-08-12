from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from apps.api import database, store
from apps.api.domains.factor_factory.alpha_mining import (
    _ai_messages,
    generate_ai_proposals,
    generate_alpha_batch,
    parse_alpha_expression,
)
from apps.api.domains.factor_factory.schemas import (
    FactorFactoryGateThresholds,
    FactorFactoryStartRequest,
)
from apps.api.domains.factor_factory.service import (
    _archive_admission_gate,
    _auto_discovery_attempted_dates,
    _candidate_preflight,
    _candidate_specs,
    _direction_bucket,
    _preliminary_gate,
    _prior_direction_radar,
    _run_auto_discovery_cycle,
    _score,
    _window_stability,
    list_factor_factory_archive,
    list_factor_factory_runs,
    observe_factor_factory,
    start_factor_factory,
)
from core.backtest.dataset import generate_dataset
from core.factor_dsl import FactorDefinition, evaluate_factor_ast
from core.llm import LLMResponse


class FakeAlphaLlm:
    _provider = "test-provider"

    def __init__(self, content: str, *, finish_reason: str | None = None) -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.calls = 0
        self.last_kwargs: dict = {}

    def estimate_tokens(self, _text: str) -> int:
        return 100

    def chat(self, *_args, **_kwargs) -> LLMResponse:
        self.calls += 1
        self.last_kwargs = _kwargs
        content = self.content
        if _args:
            messages = _args[0]
            if isinstance(messages, list) and messages:
                prompt = json.loads(messages[-1]["content"])
                seeds = prompt.get("screened_seed_candidates") or []
                if seeds:
                    payload = json.loads(content)
                else:
                    payload = {}
                if isinstance(payload.get("candidates"), list):
                    for candidate in payload["candidates"]:
                        if isinstance(candidate, dict) and not candidate.get("seed_candidate_id"):
                            candidate["seed_candidate_id"] = seeds[0]["candidate_id"]
                    content = json.dumps(payload)
        return LLMResponse(
            content=content,
            model="test-alpha-model",
            usage={"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
            finish_reason=self.finish_reason,
        )


class FactorFactoryAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db = store._DB
        self.temp_dir = Path(tempfile.mkdtemp(prefix="quanthub-factor-factory-"))
        database.dispose_engines()
        store._DB = self.temp_dir / "store.db"
        store._init()

    def tearDown(self) -> None:
        database.dispose_engines()
        store._DB = self.original_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def request() -> FactorFactoryStartRequest:
        return FactorFactoryStartRequest(
            source="synthetic",
            dataset="uptrend",
            n_bars=720,
            candidate_budget=9,
            candidate_mode="library",
            use_ai=False,
            observation_days=7,
            thresholds=FactorFactoryGateThresholds(
                minimum_validation_return=-1,
                minimum_confirmation_return=-1,
                minimum_incremental_return=-1,
                maximum_drawdown=1,
                minimum_validation_sharpe=-100,
                minimum_confirmation_sharpe=-100,
                minimum_trades=1,
                maximum_p_value=1,
                minimum_paper_return=-1,
                maximum_paper_drawdown=1,
                minimum_observations=3,
            ),
        )

    def test_search_locks_confirmation_and_starts_forward_paper_observation(self) -> None:
        response = start_factor_factory(self.request())

        self.assertEqual(response["run"]["status"], "paper_observing")
        self.assertEqual(len(response["candidates"]), 9)
        ranked_candidate = next(item for item in response["candidates"] if item["rank"] == 1)
        self.assertIsNotNone(ranked_candidate["definition"])
        self.assertTrue(ranked_candidate["definition"]["label"])
        self.assertTrue(ranked_candidate["definition"]["ast"])
        self.assertEqual(len(response["observations"]), 1)
        self.assertEqual(len(response["simulation_orders"]), 1)
        self.assertFalse(response["live_trading_enabled"])
        selected = response["run"]["selected_factor_key"]
        self.assertTrue(selected)

        opening = store.get_factor_confirmation_opening(response["run"]["research_plan_id"])
        self.assertIsNotNone(opening)
        definition = store.get_factor_definition(
            selected, response["run"]["selected_factor_version"]
        )
        lifecycle = store.get_latest_factor_lifecycle_event(definition["id"], "crypto")
        self.assertEqual(lifecycle["state"], "research_passed")
        self.assertTrue(lifecycle["evidence"]["locked_out_of_sample"])
        order = response["simulation_orders"][0]
        self.assertEqual(order["account_id"], f"factor-factory:{response['run']['id']}")
        self.assertEqual(order["audit"]["factor_key"], selected)
        self.assertEqual(order["executions"][0]["ledger_sync_status"], "isolated")
        self.assertFalse(response["run"]["result"]["paper"]["shared_ledger_mutated"])

        archive = list_factor_factory_archive(eligible_only=False, limit=100)
        record = next(item for item in archive["archives"] if item["definition"]["key"] == selected)
        self.assertFalse(record["verified"])
        self.assertFalse(record["eligible_for_archive"])
        self.assertIn("minimum_seven_real_days", record["archive_gate"]["violations"])
        self.assertEqual(record["lifecycle"]["current_state"], "research_passed")
        self.assertIn("simulation_observation_not_completed", record["remaining_risks"])
        self.assertIn("observation_period_incomplete", record["remaining_risks"])
        preregistered = record["preregistration"]["experiments"][0]
        post_study = record["post_study_evidence"]["experiments"][0]
        self.assertTrue(preregistered["hypothesis"])
        self.assertNotIn("events", preregistered)
        self.assertTrue(post_study["events"])
        self.assertEqual(post_study["status"], "succeeded")
        self.assertEqual(record["post_study_evidence"]["latest_run"]["status"], "paper_observing")
        self.assertEqual(record["evidence_chain"]["definition_hash"], definition["definition_hash"])
        self.assertIn(response["run"]["id"], record["evidence_chain"]["run_ids"])
        self.assertFalse(record["live_trading_enabled"])

    def test_duplicate_poll_does_not_create_observation_and_due_gate_uses_history(self) -> None:
        response = start_factor_factory(self.request())
        run_id = response["run"]["id"]

        duplicate = observe_factor_factory(run_id)
        self.assertEqual(len(duplicate["observations"]), 1)
        self.assertEqual(len(duplicate["simulation_orders"]), 1)
        self.assertFalse(duplicate["run"]["result"]["paper"]["last_poll_inserted"])

        first = duplicate["observations"][0]
        store.append_factor_factory_observation(
            run_id,
            market_time="2099-01-02T00:00:00+00:00",
            price=first["price"] * 1.01,
            signal=first["signal"],
            position_weight=first["position_weight"],
            gross_return=0.01 * first["position_weight"],
            cost=0,
            net_return=0.01 * first["position_weight"],
            equity=first["equity"] * 1.01,
            drawdown=0,
            fill_rate=1,
            payload={"kind": "test_forward_mark"},
        )
        store.append_factor_factory_observation(
            run_id,
            market_time="2099-01-03T00:00:00+00:00",
            price=first["price"] * 1.02,
            signal=first["signal"],
            position_weight=first["position_weight"],
            gross_return=0.01 * first["position_weight"],
            cost=0,
            net_return=0.01 * first["position_weight"],
            equity=first["equity"] * 1.02,
            drawdown=0,
            fill_rate=1,
            payload={"kind": "test_forward_mark"},
        )
        store.update_factor_factory_run(
            run_id,
            observation_started_at=time.time() - 8 * 86_400,
            observation_ends_at=0,
        )

        completed = observe_factor_factory(run_id)
        self.assertEqual(completed["run"]["status"], "trading_validated")
        self.assertEqual(len(completed["observations"]), 3)
        validation = completed["run"]["result"]["simulation_validation"]
        self.assertTrue(validation["eligible_for_trading_validated"])
        self.assertFalse(validation["live_trading_enabled"])
        archive = list_factor_factory_archive(limit=100)
        archived = next(
            item
            for item in archive["archives"]
            if item["definition"]["key"] == completed["run"]["selected_factor_key"]
        )
        self.assertTrue(archived["eligible_for_archive"])
        self.assertGreaterEqual(archived["archive_gate"]["observed_days"], 7)
        attribution = validation["research_simulation_gap_attribution"]
        self.assertEqual(
            attribution["methodology"]["scope"],
            "aggregate_research_confirmation_vs_forward_simulation",
        )
        self.assertAlmostEqual(attribution["unexplained_residual"], 0.0, places=7)

    def test_duplicate_start_reuses_research_fingerprint(self) -> None:
        first = start_factor_factory(self.request())
        replay = start_factor_factory(self.request())

        self.assertEqual(replay["run"]["id"], first["run"]["id"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(len(store.list_factor_factory_runs(limit=10)), 1)
        opening = store.get_factor_confirmation_opening(first["run"]["research_plan_id"])
        self.assertIsNotNone(opening)

    def test_run_list_filters_by_research_context(self) -> None:
        runs = [
            {
                "id": "btc-run",
                "config": {"market": "crypto", "symbol": "BTC-USDT-SWAP", "interval": "4h"},
            },
            {
                "id": "avgo-run",
                "config": {"market": "crypto", "symbol": "AVGO-USDT-SWAP", "interval": "4h"},
            },
        ]
        with (
            patch(
                "apps.api.domains.factor_factory.service.store.list_factor_factory_runs",
                return_value=runs,
            ),
            patch(
                "apps.api.domains.factor_factory.service.store.list_factor_factory_candidates",
                return_value=[],
            ),
            patch(
                "apps.api.domains.factor_factory.service.store.list_factor_factory_observations",
                return_value=[],
            ),
        ):
            response = list_factor_factory_runs(
                market="crypto",
                symbol="avgo-usdt-swap",
                interval="4h",
                limit=1,
            )

        self.assertEqual(response["count"], 1)
        self.assertEqual(response["runs"][0]["id"], "avgo-run")

    def test_archive_gate_does_not_combine_duration_from_different_runs(self) -> None:
        gate = _archive_admission_gate(
            [
                {
                    "run_id": "long-failed",
                    "status": "paper_rejected",
                    "simulation_validation": {
                        "eligible_for_trading_validated": False,
                        "observed_seconds": 8 * 86_400,
                        "observation_period_completed": True,
                    },
                },
                {
                    "run_id": "short-validated",
                    "status": "trading_validated",
                    "simulation_validation": {
                        "eligible_for_trading_validated": True,
                        "observed_seconds": 2 * 86_400,
                        "observation_period_completed": True,
                    },
                },
            ],
            [{"state": "trading_validated"}],
        )

        self.assertFalse(gate["eligible"])
        self.assertIsNone(gate["qualifying_run_id"])
        self.assertIn("qualifying_run_recorded", gate["violations"])

    def test_confirmation_candidate_keeps_its_validation_rank(self) -> None:
        gates = [
            {"passed": False, "checks": {"forced": False}},
            {"passed": True, "checks": {"forced": True}},
            *[{"passed": False, "checks": {"forced": False}} for _ in range(7)],
        ]
        with (
            patch(
                "apps.api.domains.factor_factory.service._preliminary_gate",
                side_effect=gates,
            ),
            patch(
                "apps.api.domains.factor_factory.service._score",
                side_effect=[100 - index for index in range(9)],
            ),
        ):
            response = start_factor_factory(self.request())

        selected = response["run"]["selected_factor_key"]
        selected_candidate = next(
            item for item in response["candidates"] if item["factor_key"] == selected
        )
        ranks = [item["rank"] for item in response["candidates"]]
        self.assertEqual(selected_candidate["rank"], 2)
        self.assertEqual(len(ranks), len(set(ranks)))

    def test_full_budget_contains_unique_executable_symbolic_candidates(self) -> None:
        specs = _candidate_specs("a" * 32, 30)
        frame = generate_dataset(n_bars=720, interval="1h")
        definitions = [
            FactorDefinition(
                key=spec.key,
                label=spec.label,
                market="crypto",
                ast=spec.ast,
                family=spec.family,
            )
            for spec in specs
        ]

        self.assertEqual(len(specs), 30)
        self.assertEqual(len({spec.key for spec in specs}), 30)
        self.assertEqual(len({definition.formula_hash for definition in definitions}), 30)
        self.assertIn("symbolic_regression", {spec.source for spec in specs})
        family_counts = Counter(spec.family for spec in specs)
        self.assertTrue(all(count >= 2 for count in family_counts.values()))
        for spec in specs:
            signal = evaluate_factor_ast(spec.ast, frame)
            self.assertEqual(len(signal), len(frame))
            self.assertGreater(signal.notna().sum(), 300)

    def test_brain_grammar_batch_is_unique_and_executable(self) -> None:
        proposals, audit = generate_alpha_batch(
            run_seed="stable-market-request-fingerprint",
            budget=30,
            interval="1h",
            brief="Find robust causal price-volume alpha expressions.",
            use_ai=False,
            ai_candidate_count=0,
        )
        frame = generate_dataset(n_bars=720, interval="1h")
        definitions = [
            FactorDefinition(
                key=proposal.candidate_id,
                label=proposal.label,
                market="crypto",
                ast=proposal.ast,
                family=proposal.family,
            )
            for proposal in proposals
        ]

        self.assertEqual(len(proposals), 30)
        self.assertEqual(len({item.formula_hash for item in definitions}), 30)
        self.assertFalse(audit["dynamic_code_execution"])
        self.assertFalse(audit["confirmation_labels_exposed"])
        for proposal in proposals:
            self.assertGreater(evaluate_factor_ast(proposal.ast, frame).notna().sum(), 240)

    def test_direction_radar_protects_small_samples(self) -> None:
        rows = [
            {
                "sharpe": -0.5,
                "return": -0.02,
                "passed": False,
                "operator_families": ["time_series", "arithmetic", "ranking", "conditional"],
            }
            for _ in range(6)
        ]

        bucket = _direction_bucket(rows, name="small-sample")

        self.assertEqual(bucket["light"], "YELLOW")
        self.assertTrue(bucket["protections"]["small_sample"])

    def test_direction_radar_marks_diverse_weak_direction_dead(self) -> None:
        rows = [
            {
                "sharpe": 0.1 + index * 0.01,
                "return": -0.01,
                "passed": False,
                "operator_families": [
                    "time_series",
                    "normalization",
                    "arithmetic",
                    "ranking",
                    "conditional",
                    "lag_change",
                ],
            }
            for index in range(12)
        ]

        bucket = _direction_bucket(rows, name="weak-diverse")

        self.assertEqual(bucket["light"], "DEAD")
        self.assertGreaterEqual(bucket["operator_family_count"], 4)

    def test_direction_radar_high_ceiling_prevents_dead_decision(self) -> None:
        rows = [
            {
                "sharpe": 1.8 if index == 0 else -0.4,
                "return": 0.02 if index == 0 else -0.01,
                "passed": index == 0,
                "operator_families": ["time_series", "normalization", "arithmetic", "ranking"],
            }
            for index in range(12)
        ]

        bucket = _direction_bucket(rows, name="high-ceiling")

        self.assertIn(bucket["light"], {"GREEN", "YELLOW"})
        self.assertTrue(bucket["protections"]["high_ceiling"])

    def test_ai_prompt_receives_only_direction_radar_feedback(self) -> None:
        radar = {
            "run_id": "prior-run",
            "overall": {"light": "RED", "action": "change structure"},
            "families": [{"name": "trend", "light": "YELLOW"}],
            "confirmation_labels_accessed": False,
        }

        messages = _ai_messages(
            brief="Find robust alpha expressions.",
            interval="4h",
            count=2,
            market="crypto",
            prior_direction_radar=radar,
        )
        payload = json.loads(messages[-1]["content"])

        self.assertEqual(payload["prior_direction_radar"], radar)
        self.assertFalse(payload["confirmation_labels_exposed"])
        self.assertNotIn("locked_confirmation", json.dumps(payload))

    def test_prior_direction_radar_is_scoped_and_compressed(self) -> None:
        request = self.request()
        runs = [
            {
                "id": "prior-other-symbol",
                "config": {"market": "crypto", "symbol": "ETH-USDT-SWAP", "interval": "4h"},
                "result": {"direction_radar": {"overall": {"light": "DEAD"}, "families": []}},
            },
            {
                "id": "prior-matching-run",
                "config": {
                    "market": request.market,
                    "symbol": request.symbol,
                    "interval": request.interval,
                },
                "result": {
                    "direction_radar": {
                        "overall": {"light": "YELLOW", "action": "continue", "dsi": 0.48},
                        "families": [
                            {
                                "name": "brain_return_trend",
                                "light": "GREEN",
                                "action": "deepen",
                                "sample_count": 12,
                                "dsi": 0.67,
                                "maximum_sharpe": 1.8,
                                "operator_families": ["time_series", "lag_change"],
                                "locked_confirmation": {"sharpe": 9.9},
                            }
                        ],
                    }
                },
            },
        ]

        with patch.object(store, "list_factor_factory_runs", return_value=runs):
            radar = _prior_direction_radar(request)

        self.assertEqual(radar["run_id"], "prior-matching-run")
        self.assertEqual(radar["families"][0]["light"], "GREEN")
        self.assertNotIn("locked_confirmation", json.dumps(radar))
        self.assertFalse(radar["confirmation_labels_accessed"])

    def test_invalid_ai_output_falls_back_to_grammar(self) -> None:
        client = FakeAlphaLlm("not-json")
        proposals, audit = generate_alpha_batch(
            run_seed="invalid-ai-fallback",
            budget=6,
            interval="4h",
            brief="Find causal alpha expressions with low drawdown.",
            use_ai=True,
            ai_candidate_count=2,
            maximum_ai_tokens=2_000,
            client=client,
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(len(proposals), 6)
        self.assertEqual(audit["ai"]["status"], "invalid_output")
        self.assertEqual(audit["ai"]["output_raw"], "not-json")
        self.assertFalse(audit["ai"]["output_truncated"])
        self.assertNotIn("ai", audit["source_counts"])
        self.assertNotIn("request_timeout", client.last_kwargs)
        self.assertNotIn("transport_max_retries", client.last_kwargs)

    def test_truncated_ai_output_keeps_complete_candidates(self) -> None:
        first = {
            "candidate_id": "complete_alpha_one",
            "formula_ast": {
                "op": "rolling_zscore",
                "value": {"op": "field", "name": "close"},
                "window": 20,
            },
        }
        second = {
            "candidate_id": "complete_alpha_two",
            "formula_ast": {
                "op": "neg",
                "value": {
                    "op": "rolling_zscore",
                    "value": {"op": "field", "name": "volume"},
                    "window": 24,
                },
            },
        }
        content = (
            '{"candidates":['
            + json.dumps(first)
            + ","
            + json.dumps(second)
            + ',{"candidate_id":"incomplete","formula_ast":{"op":"rolling_mean"'
        )
        proposals, audit = generate_ai_proposals(
            brief="Find robust alpha expressions.",
            interval="4h",
            count=3,
            maximum_tokens=4_000,
            client=FakeAlphaLlm(content, finish_reason="length"),
        )

        self.assertEqual(
            [item.candidate_id for item in proposals], ["complete_alpha_one", "complete_alpha_two"]
        )
        self.assertEqual(audit["status"], "generated_partial")
        self.assertEqual(audit["candidate_count"], 2)
        self.assertEqual(audit["recovered_complete_candidates"], 2)
        self.assertEqual(audit["finish_reason"], "length")
        self.assertTrue(audit["output_truncated"])

    def test_ai_args_ast_is_normalized_before_safe_dsl_validation(self) -> None:
        content = json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "args_style_alpha",
                        "formula_ast": {
                            "op": "mul",
                            "args": [
                                {
                                    "op": "neg",
                                    "args": [
                                        {
                                            "op": "rolling_zscore",
                                            "args": [
                                                {
                                                    "op": "pct_change",
                                                    "args": [
                                                        {"op": "field", "args": ["close"]},
                                                        3,
                                                    ],
                                                },
                                                19,
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "op": "rank",
                                    "args": [{"op": "field", "name": "volume"}, 20],
                                },
                            ],
                        },
                    }
                ]
            }
        )
        proposals, audit = generate_alpha_batch(
            run_seed="args-style-ai",
            budget=1,
            interval="4h",
            brief="Find a causal price-volume alpha with low drawdown.",
            use_ai=True,
            ai_candidate_count=1,
            maximum_ai_tokens=2_000,
            client=FakeAlphaLlm(content),
        )

        self.assertEqual(audit["ai"]["status"], "generated")
        self.assertEqual(audit["source_counts"], {"ai": 1})
        self.assertEqual(audit["ai"]["output_raw"], content)
        self.assertEqual(proposals[0].ast["left"]["value"]["window"], 19)
        self.assertEqual(proposals[0].ast["right"]["window"], 20)
        self.assertNotIn("args", json.dumps(proposals[0].ast))

    def test_manual_expression_enters_same_backtest_pipeline(self) -> None:
        payload = self.request().model_dump()
        payload.update(
            candidate_mode="manual",
            candidate_budget=1,
            manual_candidates=[
                {
                    "candidate_id": "manual_pressure",
                    "label": "手工量价压力",
                    "expression": "mul(rolling_zscore(pct_change(close, 3), 19), rank(volume, 20))",
                    "hypothesis": "量价同步压力可能在成本后保留方向信息。",
                }
            ],
        )
        request = FactorFactoryStartRequest(**payload)
        response = start_factor_factory(request)

        self.assertEqual(response["run"]["config"]["candidate_mode"], "manual")
        self.assertEqual(
            response["run"]["config"]["candidate_generation"]["source_counts"], {"human": 1}
        )
        self.assertEqual(response["candidates"][0]["source"], "human")
        definition = store.get_factor_definition(
            response["candidates"][0]["factor_key"], response["candidates"][0]["factor_version"]
        )
        self.assertEqual(definition["ast"]["op"], "mul")

    def test_a_share_manual_batch_uses_target_market_lineage(self) -> None:
        frame = generate_dataset(n_bars=720, interval="1d")
        frame["symbol"] = "600519"
        frame["market"] = "a_shares"
        frame["interval"] = "1d"
        payload = self.request().model_dump()
        payload.update(
            market="a_shares",
            source="akshare_live",
            symbol="600519",
            interval="1d",
            candidate_mode="manual",
            candidate_budget=1,
            manual_candidates=[
                {
                    "candidate_id": "manual_a_share",
                    "expression": "rolling_zscore(pct_change(close, 5), 20)",
                }
            ],
            paper_target="simulation_orders",
        )
        request = FactorFactoryStartRequest(**payload)
        source = Mock()
        source.get_kline.return_value = frame
        with patch(
            "core.data_feed.akshare_source.AkshareSource",
            return_value=source,
        ):
            response = start_factor_factory(request)

        candidate = response["candidates"][0]
        definition = store.get_factor_definition(
            candidate["factor_key"], candidate["factor_version"]
        )
        experiment = store.get_factor_experiment(candidate["experiment_id"])
        self.assertEqual(definition["market"], "a_shares")
        self.assertEqual(experiment["target_market"], "a_shares")
        self.assertEqual(response["run"]["config"]["market"], "a_shares")

    def test_manual_expression_parser_rejects_code_and_future_lag(self) -> None:
        with self.assertRaises(ValueError):
            parse_alpha_expression("__import__('os').system('whoami')")
        with self.assertRaises(ValueError):
            parse_alpha_expression("lag(close, -1)")

    def test_replay_skips_ai_and_ai_provenance_is_saved(self) -> None:
        client = FakeAlphaLlm(
            json.dumps(
                {
                    "candidates": [
                        {
                            "candidate_id": "volume_pressure_ai",
                            "label": "AI volume pressure",
                            "family": "ai_volume_pressure",
                            "hypothesis": "Volume-supported returns may persist after costs.",
                            "invalidation": "The effect fails rolling validation or cost stress.",
                            "falsification_tests": [
                                "rolling_validation_stability",
                                "double_cost_stress",
                            ],
                            "formula_ast": {
                                "op": "mul",
                                "left": {
                                    "op": "rolling_zscore",
                                    "value": {"op": "field", "name": "volume"},
                                    "window": 17,
                                },
                                "right": {
                                    "op": "rolling_zscore",
                                    "value": {
                                        "op": "pct_change",
                                        "value": {"op": "field", "name": "close"},
                                        "periods": 3,
                                    },
                                    "window": 19,
                                },
                            },
                        }
                    ]
                }
            )
        )
        payload = self.request().model_dump()
        payload.update(
            candidate_mode="brain",
            use_ai=True,
            ai_provider="custom",
            ai_candidate_count=1,
            candidate_budget=3,
            maximum_ai_tokens=2_000,
        )
        request = FactorFactoryStartRequest(**payload)
        with patch(
            "apps.api.domains.factor_factory.alpha_mining.get_llm",
            return_value=client,
        ) as get_llm_mock:
            first = start_factor_factory(request)
            replay = start_factor_factory(request)

        self.assertEqual(client.calls, 1)
        get_llm_mock.assert_called_once_with("custom")
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(replay["run"]["id"], first["run"]["id"])
        self.assertEqual(first["run"]["config"]["ai_provider"], "custom")
        self.assertEqual(
            first["run"]["config"]["candidate_generation"]["ai"]["requested_provider"],
            "custom",
        )
        generation = first["run"]["config"]["candidate_generation"]
        self.assertEqual(generation["mode"], "grammar_screen_then_ai_refine")
        self.assertGreater(
            generation["stages"]["grammar_generation"]["candidate_count"],
            request.candidate_budget,
        )
        self.assertFalse(generation["stages"]["discovery_backtest"]["confirmation_labels_accessed"])
        plan = store.get_factor_research_plan(first["run"]["research_plan_id"])
        self.assertEqual(
            plan["budget"]["maximum_candidates"],
            request.candidate_budget + request.ai_candidate_count + 1,
        )
        experiments = store.list_factor_experiments(
            research_plan_id=first["run"]["research_plan_id"],
            limit=100,
        )
        ai_experiment = next(item for item in experiments if item["source"] == "ai")
        detail = store.get_factor_experiment(ai_experiment["id"])
        self.assertEqual(detail["model"]["provider"], "test-provider")
        self.assertEqual(detail["prompt"]["version"], "brain-alpha-refinement-json-v4")
        self.assertTrue(detail["prompt"]["seed_candidate_id"])
        self.assertEqual(detail["proposal"]["ai_trace"]["token_usage"]["total_tokens"], 200)
        self.assertTrue(detail["proposal"]["ai_trace"]["output_raw"])

    def test_one_hour_candidate_mix_replaces_repeated_weak_variants(self) -> None:
        one_hour = _candidate_specs("1" * 32, 30, interval="1h")
        four_hour = _candidate_specs("4" * 32, 30, interval="4h")
        one_hour_keys = {item.key for item in one_hour}
        four_hour_keys = {item.key for item in four_hour}

        for family in (
            "efficiency_ratio_trend",
            "volatility_gated_reversal",
            "close_location_volume_pressure",
        ):
            self.assertIn(f"ff_{'1' * 8}_{family}_12", one_hour_keys)
            self.assertIn(f"ff_{'1' * 8}_{family}_24", one_hour_keys)
            self.assertFalse(any(family in key for key in four_hour_keys))
        for family in (
            "volatility_adjusted_momentum",
            "volume_confirmed_breakout",
            "donchian_breakout",
        ):
            self.assertNotIn(f"ff_{'1' * 8}_{family}_10", one_hour_keys)
            self.assertNotIn(f"ff_{'1' * 8}_{family}_40", one_hour_keys)
            self.assertIn(f"ff_{'4' * 8}_{family}_10", four_hour_keys)
            self.assertIn(f"ff_{'4' * 8}_{family}_40", four_hour_keys)

        frame = generate_dataset(n_bars=720, interval="1h")
        definitions = [
            FactorDefinition(
                key=spec.key,
                label=spec.label,
                market="crypto",
                ast=spec.ast,
                family=spec.family,
            )
            for spec in one_hour
        ]
        self.assertEqual(len(one_hour), 30)
        self.assertEqual(len({item.formula_hash for item in definitions}), 30)
        for spec in one_hour:
            signal = evaluate_factor_ast(spec.ast, frame)
            self.assertGreater(signal.notna().sum(), 300)

    def test_validation_window_stability_requires_a_positive_majority(self) -> None:
        stable = _window_stability([0.01] * 9)
        unstable = _window_stability([-0.02] * 3 + [0.05] * 3 + [-0.02] * 3)

        self.assertTrue(stable["passed"])
        self.assertEqual(stable["positive_windows"], 3)
        self.assertFalse(unstable["passed"])
        self.assertEqual(unstable["positive_windows"], 1)

    def test_preliminary_gate_rejects_aggregate_gain_with_unstable_windows(self) -> None:
        metrics = {
            "discovery": {"summary": {"total_return": 0.01}},
            "rolling_validation": {
                "summary": {
                    "total_return": 0.03,
                    "max_drawdown": -0.02,
                    "n_trades": 10,
                    "metrics": {"sharpe": 1.0},
                    "raw_p_value": 0.05,
                    "rank_ic": 0.1,
                    "window_stability": {
                        "passed": False,
                        "positive_window_ratio": 1 / 3,
                        "return_dispersion": 0.04,
                    },
                }
            },
        }

        request = self.request()
        request.thresholds.minimum_validation_return = -0.01
        request.thresholds.minimum_validation_sharpe = 0.0
        gate = _preliminary_gate(metrics, request)

        self.assertFalse(gate["passed"])
        self.assertFalse(gate["checks"]["validation_window_majority"])

    def test_score_rewards_window_stability_without_overriding_core_metrics(self) -> None:
        base_summary = {
            "total_return": 0.03,
            "max_drawdown": -0.02,
            "metrics": {"sharpe": 1.0},
        }
        stable = {
            "rolling_validation": {
                "summary": {
                    **base_summary,
                    "window_stability": {
                        "positive_window_ratio": 1.0,
                        "return_dispersion": 0.005,
                    },
                }
            }
        }
        unstable = {
            "rolling_validation": {
                "summary": {
                    **base_summary,
                    "window_stability": {
                        "positive_window_ratio": 1 / 3,
                        "return_dispersion": 0.04,
                    },
                }
            }
        }

        self.assertGreater(_score(stable), _score(unstable))

    def test_preliminary_gate_rejects_candidate_that_fails_cost_stress(self) -> None:
        base_summary = {
            "total_return": 0.03,
            "max_drawdown": -0.02,
            "n_trades": 10,
            "metrics": {"sharpe": 1.0},
            "raw_p_value": 0.05,
            "rank_ic": 0.1,
            "window_stability": {
                "passed": True,
                "positive_window_ratio": 1.0,
                "return_dispersion": 0.005,
            },
        }
        metrics = {
            "discovery": {"summary": {"total_return": 0.01}},
            "rolling_validation": {"summary": base_summary},
            "rolling_validation_cost_stress": {
                "summary": {
                    **base_summary,
                    "total_return": -0.02,
                    "metrics": {"sharpe": -0.5},
                }
            },
        }

        request = self.request()
        request.thresholds.minimum_validation_return = -0.01
        request.thresholds.minimum_validation_sharpe = 0.0
        gate = _preliminary_gate(metrics, request)

        self.assertFalse(gate["passed"])
        self.assertFalse(gate["checks"]["cost_stress_return"])
        self.assertFalse(gate["checks"]["cost_stress_sharpe"])

    def test_preliminary_gate_rejects_weak_validation_statistics(self) -> None:
        summary = {
            "total_return": 0.03,
            "max_drawdown": -0.02,
            "n_trades": 10,
            "metrics": {"sharpe": 1.0},
            "raw_p_value": 0.3,
            "rank_ic": -0.05,
            "window_stability": {
                "passed": True,
                "positive_window_ratio": 1.0,
                "return_dispersion": 0.005,
            },
        }
        metrics = {
            "discovery": {"summary": {"total_return": 0.01}},
            "rolling_validation": {"summary": summary},
            "rolling_validation_cost_stress": {
                "summary": {
                    **summary,
                    "raw_p_value": 0.05,
                    "rank_ic": 0.05,
                }
            },
        }
        request = self.request()
        request.thresholds.minimum_validation_return = -0.01
        request.thresholds.minimum_validation_sharpe = 0.0
        request.thresholds.maximum_p_value = 0.2

        gate = _preliminary_gate(metrics, request)

        self.assertFalse(gate["passed"])
        self.assertFalse(gate["checks"]["validation_p_value"])
        self.assertFalse(gate["checks"]["validation_rank_ic_direction"])

    def test_score_rewards_cost_robust_candidate(self) -> None:
        base_summary = {
            "total_return": 0.03,
            "max_drawdown": -0.02,
            "metrics": {"sharpe": 1.0},
            "window_stability": {
                "positive_window_ratio": 1.0,
                "return_dispersion": 0.005,
            },
        }
        robust = {
            "rolling_validation": {"summary": base_summary},
            "rolling_validation_cost_stress": {
                "summary": {
                    **base_summary,
                    "total_return": 0.025,
                    "metrics": {"sharpe": 0.8},
                }
            },
        }
        fragile = {
            "rolling_validation": {"summary": base_summary},
            "rolling_validation_cost_stress": {
                "summary": {
                    **base_summary,
                    "total_return": 0.0,
                    "max_drawdown": -0.03,
                    "metrics": {"sharpe": 0.0},
                }
            },
        }

        self.assertGreater(_score(robust), _score(fragile))

    def test_candidate_preflight_rejects_duplicates_and_cross_family_equivalents(self) -> None:
        first, second = _candidate_specs("b" * 32, 2)
        duplicate = replace(first, key=f"{first.key}_duplicate")
        scaled = replace(
            second,
            key=f"{second.key}_scaled",
            family="factor_factory_cross_family",
            ast={
                "op": "mul",
                "left": second.ast,
                "right": {"op": "const", "value": 2.0},
            },
        )
        frame = generate_dataset(n_bars=720, interval="1h")

        accepted, rejected, audit = _candidate_preflight(
            [first, duplicate, second, scaled],
            frame.iloc[:360],
            budget=4,
        )

        self.assertEqual([item.key for item in accepted], [first.key, second.key])
        self.assertEqual(rejected[duplicate.key]["reason"], "formula_duplicate")
        self.assertEqual(rejected[scaled.key]["reason"], "correlation_cluster")
        self.assertEqual(rejected[scaled.key]["relation"], "constant_multiple")
        self.assertTrue(audit["within_budget"])
        self.assertTrue(audit["discovery_only"])
        self.assertFalse(audit["confirmation_labels_accessed"])

    def test_full_budget_runs_preflight_and_persists_all_candidates(self) -> None:
        request = self.request().model_copy(update={"candidate_budget": 30})

        response = start_factor_factory(request)

        preflight = response["run"]["result"]["candidate_preflight"]
        self.assertEqual(len(response["candidates"]), 30)
        self.assertEqual(preflight["generated_candidates"], 30)
        self.assertEqual(
            preflight["accepted_candidates"] + preflight["rejected_candidates"],
            30,
        )
        self.assertEqual(
            len([item for item in response["candidates"] if item["experiment_id"]]),
            preflight["accepted_candidates"],
        )
        self.assertFalse(any(item["status"] == "invalid" for item in response["candidates"]))
        self.assertIn("symbolic_regression", {item["source"] for item in response["candidates"]})

    def test_auto_discovery_runs_each_interval_once_per_day(self) -> None:
        _auto_discovery_attempted_dates.clear()
        created: list[str] = []

        def fake_start(request: FactorFactoryStartRequest) -> dict:
            created.append(request.interval)
            return {
                "run": {
                    "id": f"run-{request.interval}",
                    "status": "no_qualified_factor",
                    "config": {
                        **request.model_dump(mode="json"),
                        "data_provenance": {"requested_end": "2026-08-11T00:00:00+00:00"},
                    },
                }
            }

        with (
            patch.dict(
                os.environ,
                {
                    "QUANTHUB_FACTOR_AUTO_DISCOVERY": "1",
                    "QH_RUNNER_ENVIRONMENT": "demo",
                },
                clear=False,
            ),
            patch(
                "apps.api.domains.factor_factory.service.store.list_factor_factory_runs",
                return_value=[],
            ),
            patch(
                "apps.api.domains.factor_factory.service.start_factor_factory",
                side_effect=fake_start,
            ),
        ):
            now = datetime(2026, 8, 11, 10, 5, tzinfo=UTC)
            first = _run_auto_discovery_cycle(now)
            second = _run_auto_discovery_cycle(now)

        self.assertEqual(created, ["1h", "4h"])
        self.assertEqual(len(first), 2)
        self.assertEqual(second, [])

    def test_auto_discovery_pauses_while_factor_is_observing(self) -> None:
        _auto_discovery_attempted_dates.clear()
        observing = {"id": "active-run", "status": "paper_observing", "config": {}}
        with (
            patch.dict(
                os.environ,
                {
                    "QUANTHUB_FACTOR_AUTO_DISCOVERY": "1",
                    "QH_RUNNER_ENVIRONMENT": "demo",
                },
                clear=False,
            ),
            patch(
                "apps.api.domains.factor_factory.service.store.list_factor_factory_runs",
                return_value=[observing],
            ),
            patch("apps.api.domains.factor_factory.service.start_factor_factory") as start,
        ):
            outcomes = _run_auto_discovery_cycle(datetime(2026, 8, 11, 10, 5, tzinfo=UTC))

        self.assertEqual(outcomes, [])
        start.assert_not_called()

    def test_auto_discovery_skips_same_market_boundary_after_version_change(self) -> None:
        _auto_discovery_attempted_dates.clear()
        previous = {
            "id": "previous-run",
            "status": "no_research_passed_factor",
            "started_at": datetime(2026, 8, 10, 10, 5, tzinfo=UTC).timestamp(),
            "config": {
                "source": "okx_live",
                "symbol": "BTC-USDT-SWAP",
                "interval": "1h",
                "paper_target": "okx_demo",
                "data_provenance": {"requested_end": "2026-08-11T10:00:00+00:00"},
            },
        }

        def list_runs(*, status=None, limit=200):
            return [] if status == "paper_observing" else [previous]

        with (
            patch.dict(
                os.environ,
                {
                    "QUANTHUB_FACTOR_AUTO_DISCOVERY": "1",
                    "QH_RUNNER_ENVIRONMENT": "demo",
                },
                clear=False,
            ),
            patch(
                "apps.api.domains.factor_factory.service.store.list_factor_factory_runs",
                side_effect=list_runs,
            ),
            patch("apps.api.domains.factor_factory.service.start_factor_factory") as start,
        ):
            outcomes = _run_auto_discovery_cycle(datetime(2026, 8, 11, 10, 30, tzinfo=UTC))

        self.assertEqual(outcomes[0]["reason"], "same_market_boundary")
        self.assertEqual(outcomes[0]["interval"], "1h")
        start.assert_called_once()


if __name__ == "__main__":
    unittest.main()

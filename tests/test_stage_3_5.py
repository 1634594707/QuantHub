import shutil
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from apps.api import database, store
from apps.api.domains.alerts import service as alert_service
from apps.api.domains.alerts.schemas import AlertRuleCreate
from apps.api.domains.automation import repository as automation_repository
from apps.api.domains.automation import service as automation_service
from apps.api.domains.automation.schemas import FactorResearchJobCreate
from apps.api.domains.factor_research.schemas import FactorResearchRequest
from core.trading_costs import (
    TradingCostComponent,
    TradingCostProfile,
    TradingExecutionBar,
    TradingExecutionConstraint,
    TradingExecutionSimulation,
    execution_profile_gaps,
    simulate_execution,
)


class StageThreeCostTests(unittest.TestCase):
    def test_cost_profile_requires_source_and_produces_exact_total(self) -> None:
        profile = TradingCostProfile(
            market="us_stocks",
            components=[
                TradingCostComponent(
                    key="sec_fee",
                    label="SEC regulatory fee",
                    value=1.0,
                    unit="source_native",
                    normalized_bps=2.5,
                    source_url="https://www.sec.gov/rules-regulations/fee-rate-advisories",
                    source_captured_at=datetime(2026, 7, 31, tzinfo=UTC),
                    effective_from=datetime(2026, 7, 31, tzinfo=UTC).date(),
                    market="us_stocks",
                ),
                TradingCostComponent(
                    key="broker_commission",
                    label="Broker commission",
                    value=0.5,
                    unit="source_native",
                    normalized_bps=4.0,
                    source_url="https://broker.example/fees",
                    source_captured_at=datetime(2026, 7, 31, tzinfo=UTC),
                    effective_from=datetime(2026, 7, 31, tzinfo=UTC).date(),
                    market="us_stocks",
                    account_scope="account-1",
                ),
            ],
        )
        request = FactorResearchRequest(
            symbol="AAPL", market="us_stocks", transaction_cost_profile=profile
        )
        self.assertEqual(request.transaction_cost_bps, 6.5)

        with self.assertRaisesRegex(ValueError, "缺少 normalized_bps"):
            profile_without_normalization = TradingCostProfile(
                market="us_stocks",
                components=[
                    TradingCostComponent(
                        key="spread",
                        label="Bid ask spread",
                        value=1.0,
                        unit="price_points",
                        source_url="https://broker.example/spread",
                        source_captured_at=datetime(2026, 7, 31, tzinfo=UTC),
                        effective_from=datetime(2026, 7, 31, tzinfo=UTC).date(),
                        market="us_stocks",
                    )
                ],
            )
            _ = profile_without_normalization.total_transaction_cost_bps

    def test_market_execution_constraints_limit_fills_and_equity(self) -> None:
        captured = datetime(2026, 7, 31, tzinfo=UTC)
        profile = TradingCostProfile(
            market="a_shares",
            participation_rate=0.2,
            components=[
                TradingCostComponent(
                    key=key,
                    label=key,
                    value=1,
                    unit="source_native",
                    normalized_bps=1,
                    source_url="https://www.chinaclear.cn/zdjs/fbzx/fee.shtml",
                    source_captured_at=captured,
                    effective_from=captured.date(),
                    market="a_shares",
                )
                for key in ("commission", "stamp_tax", "transfer_fee")
            ],
            execution_constraints=[
                TradingExecutionConstraint(
                    key=key,
                    label=key,
                    value=value,
                    unit="boolean" if isinstance(value, bool) else "shares",
                    source_url="https://www.sse.com.cn/assortment/stock/trading/",
                    source_captured_at=captured,
                    effective_from=captured.date(),
                )
                for key, value in (
                    ("limit_up", True),
                    ("limit_down", True),
                    ("suspended", False),
                    ("lot_size", 100),
                )
            ],
        )
        result = simulate_execution(
            profile,
            TradingExecutionSimulation(
                initial_cash=100_000,
                bars=[
                    TradingExecutionBar(
                        timestamp="2026-07-30",
                        close=10,
                        volume=1_000,
                        at_limit_up=True,
                    ),
                    TradingExecutionBar(timestamp="2026-07-31", close=11, volume=1_000),
                    TradingExecutionBar(
                        timestamp="2026-08-01",
                        close=10,
                        volume=1_000,
                        at_limit_down=True,
                    ),
                ],
                desired_quantities=[100, 100, 0],
            ),
        )
        self.assertEqual(result["fills"][0]["block_reason"], "limit_up")
        self.assertEqual(result["fills"][1]["filled_quantity"], 100)
        self.assertEqual(result["fills"][2]["block_reason"], "limit_down")
        self.assertEqual(result["metrics"]["ending_quantity"], 100)
        self.assertLess(result["metrics"]["ending_equity"], 100_000)
        self.assertEqual(execution_profile_gaps(profile), {"components": [], "constraints": []})

    def test_execution_profile_rejects_missing_market_components(self) -> None:
        profile = TradingCostProfile(
            market="crypto",
            components=[
                TradingCostComponent(
                    key="spread",
                    label="spread",
                    value=1,
                    unit="bp",
                    normalized_bps=1,
                    source_url="https://www.okx.com/docs-v5/en/",
                    source_captured_at=datetime(2026, 7, 31, tzinfo=UTC),
                    effective_from=datetime(2026, 7, 31, tzinfo=UTC).date(),
                    market="crypto",
                )
            ],
        )
        gaps = execution_profile_gaps(profile)
        self.assertEqual(gaps["components"], ["fee_tier", "funding_rate", "slippage"])
        with self.assertRaisesRegex(ValueError, "执行档案不完整"):
            simulate_execution(
                profile,
                TradingExecutionSimulation(
                    initial_cash=100,
                    bars=[TradingExecutionBar(timestamp="t", close=1, volume=1)],
                    desired_quantities=[1],
                ),
            )


class StageFiveAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db = store._DB
        self.temp_dir = Path(tempfile.mkdtemp(prefix="quanthub-stage-five-"))
        database.dispose_engines()
        store._DB = self.temp_dir / "store.db"
        store._init()

    def tearDown(self) -> None:
        database.dispose_engines()
        store._DB = self.original_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_factor_job_cron_and_scheduler_entry_are_persisted(self) -> None:
        universe = store.create_factor_universe("US test", "us_stocks", "")
        payload = FactorResearchJobCreate(
            name="每周美股复验",
            frequency="weekly",
            hour=9,
            minute=15,
            day_of_week=1,
            request={"universe_id": universe["id"], "factor_key": "trend_strength"},
        )
        self.assertEqual(payload.cron(), "15 9 * * 1")
        job = automation_service.create_factor_research_job(payload)
        self.assertEqual(job["cron"], "15 9 * * 1")
        self.assertEqual(job["request"]["universe_id"], universe["id"])

        from apps.scheduler.jobs import _build_jobs

        dynamic = next(
            item for item in _build_jobs() if item["name"] == f"factor_research_{job['id']}"
        )
        self.assertEqual(dynamic["func_name"], f"__run_factor_research__:{job['id']}")
        self.assertEqual(dynamic["cron"], "15 9 * * 1")
        automation_repository.save_override(
            dynamic["name"], enabled=False, cron="30 10 * * 2", actor="test"
        )
        overridden = next(item for item in _build_jobs() if item["name"] == dynamic["name"])
        self.assertFalse(overridden["enabled"])
        self.assertEqual(overridden["cron"], "30 10 * * 2")

    def test_factor_job_execution_returns_research_run_reference(self) -> None:
        universe = store.create_factor_universe("US test", "us_stocks", "")
        job = automation_repository.create_factor_research_job(
            name="测试作业",
            universe_id=universe["id"],
            cron="0 18 * * *",
            enabled=True,
            request={"universe_id": universe["id"], "factor_key": "trend_strength"},
            actor="test",
        )
        with patch(
            "apps.api.domains.factor_research.service.run_cross_sectional_research",
            return_value={"ok": True, "run_id": "research-123"},
        ):
            result = automation_service._execute_job(f"__run_factor_research__:{job['id']}")
        self.assertEqual(
            result, {"research_run_id": "research-123", "factor_research_job_id": job["id"]}
        )

    def test_factor_status_alert_links_to_the_changed_research_run(self) -> None:
        run = store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={},
        )
        store.update_research_run(run["id"], {"status": "succeeded"})
        store.add_research_evidence(
            run_id=run["id"],
            kind="factor_research_result",
            source="test",
            title="factor",
            uri=None,
            payload={
                "factors": [{"key": "trend_strength", "status": "usable", "test_ic": 0.08}],
                "current_signal": {"strategy_drawdown": -0.03},
            },
        )
        payload = AlertRuleCreate(
            name="趋势因子状态",
            rule_type="factor_status_changed",
            symbol="AAPL",
            market="us_stocks",
            context={"factor_key": "trend_strength", "research_run_id": run["id"]},
        )
        rule = alert_service.create_rule("local-user", payload.model_dump())
        self.assertFalse(alert_service.check_rule(rule, force=True)["triggered"])

        store.add_research_evidence(
            run_id=run["id"],
            kind="factor_research_result",
            source="test",
            title="factor changed",
            uri=None,
            payload={
                "factors": [{"key": "trend_strength", "status": "reject", "test_ic": -0.02}],
                "current_signal": {"strategy_drawdown": -0.12},
            },
        )
        with patch("core.alert.get_notifier") as get_notifier:
            get_notifier.return_value.send.return_value = {}
            changed = alert_service.check_rule(rule, force=True)
        self.assertTrue(changed["triggered"])
        self.assertEqual(changed["event"]["related_type"], "research_run")
        self.assertEqual(changed["event"]["related_id"], run["id"])

    def test_factor_ic_drawdown_and_staleness_rules_use_saved_factor_evidence(self) -> None:
        run = store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={},
        )
        store.update_research_run(run["id"], {"status": "succeeded"})
        store.add_research_evidence(
            run_id=run["id"],
            kind="factor_research_result",
            source="test",
            title="factor",
            uri=None,
            payload={
                "factors": [{"key": "trend_strength", "status": "watch", "test_ic": 0.01}],
                "current_signal": {"strategy_drawdown": -0.12},
            },
        )
        rules = [
            AlertRuleCreate(
                name="IC 衰减",
                rule_type="factor_ic_decay",
                symbol="AAPL",
                market="us_stocks",
                threshold=0.05,
                context={"factor_key": "trend_strength", "baseline_test_ic": 0.08},
            ),
            AlertRuleCreate(
                name="回撤越界",
                rule_type="factor_drawdown_breach",
                symbol="AAPL",
                market="us_stocks",
                threshold=0.1,
                context={"factor_key": "trend_strength"},
            ),
        ]
        with patch("core.alert.get_notifier") as get_notifier:
            get_notifier.return_value.send.return_value = {}
            results = [
                alert_service.check_rule(
                    alert_service.create_rule("local-user", rule.model_dump()), force=True
                )
                for rule in rules
            ]
        self.assertTrue(all(result["triggered"] for result in results))
        self.assertEqual(results[0]["event"]["observed_value"], 0.01)
        self.assertEqual(results[1]["event"]["observed_value"], -0.12)

        with store._lock, store._conn() as connection:
            connection.execute(
                "UPDATE research_runs SET updated_at=? WHERE id=?",
                (time.time() - 7200, run["id"]),
            )
        stale_rule = alert_service.create_rule(
            "local-user",
            AlertRuleCreate(
                name="数据过期",
                rule_type="factor_data_stale",
                symbol="AAPL",
                market="us_stocks",
                threshold=1,
                context={"factor_key": "trend_strength"},
            ).model_dump(),
        )
        with patch("core.alert.get_notifier") as get_notifier:
            get_notifier.return_value.send.return_value = {}
            stale = alert_service.check_rule(stale_rule, force=True)
        self.assertTrue(stale["triggered"])
        self.assertGreaterEqual(stale["event"]["observed_value"], 2)

    def test_research_validation_failure_is_aggregated_in_incidents(self) -> None:
        run = store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={},
        )
        store.update_research_run(run["id"], {"status": "failed", "error": "样本不足"})
        from apps.api.domains.incidents import service as incident_service

        response = incident_service.list_incidents(limit=100)
        row = next(item for item in response["incidents"] if item["entity_id"] == run["id"])
        self.assertEqual(row["source"], "research_run")
        self.assertEqual(row["context"]["kind"], "statistical_validation")
        self.assertEqual(row["actions"][0]["research_run_id"], run["id"])

    def test_status_matrix_and_home_attention_expose_rules_and_evidence(self) -> None:
        run = store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={},
        )
        store.update_research_run(run["id"], {"status": "succeeded"})
        store.add_research_evidence(
            run_id=run["id"],
            kind="factor_research_result",
            source="test",
            title="factor",
            uri="/factor-research?run_id=" + run["id"],
            payload={
                "factors": [
                    {
                        "key": "trend_strength",
                        "status": "watch",
                        "multi_window_consistent": False,
                        "windows": [
                            {
                                "fold": 1,
                                "status": "pass",
                                "test_ic": 0.04,
                                "hit_rate": 0.6,
                            }
                        ],
                    },
                    {"key": "momentum_20", "status": "reject"},
                ]
            },
        )
        with store._lock, store._conn() as connection:
            connection.execute(
                "UPDATE research_runs SET updated_at=? WHERE id=?",
                (time.time() - 25 * 3600, run["id"]),
            )
        from apps.api.domains.factor_research.service import (
            factor_research_attention,
            factor_status_matrix,
        )

        matrix = factor_status_matrix("trend_strength")
        window = next(row for row in matrix["rows"] if row["dimension"] == "window")
        self.assertEqual(window["state"], "passed")
        self.assertEqual(window["run_id"], run["id"])
        self.assertIn("训练样本至少 40", window["rule"])

        attention = factor_research_attention(stale_hours=24)
        item = next(row for row in attention["items"] if row["run_id"] == run["id"])
        self.assertEqual(
            item["states"],
            ["needs_revalidation", "invalidated", "data_stale"],
        )
        self.assertEqual(item["evidence"]["rejected_factors"], ["momentum_20"])

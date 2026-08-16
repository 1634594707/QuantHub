from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.testclient import TestClient

from apps.api import database, store
from apps.api.domains.alerts import service as alert_service
from apps.api.domains.automation import repository as automation_repository
from apps.api.domains.automation import service as automation_service
from apps.api.domains.governance import repository as governance_repository
from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.ledger import repository as ledger_repository
from apps.api.domains.portfolio import service as portfolio_service
from apps.api.domains.search import service as search_service
from apps.api.domains.settings import service as settings_service
from apps.api.domains.signals import service as signal_service
from apps.api.domains.signals.schemas import PublishSignalRequest
from apps.api.domains.simulation import service as simulation_service
from apps.api.domains.simulation.schemas import SimulationFillCreate, SimulationOrderCreate
from apps.api.domains.tasks import service as task_service
from apps.api.domains.tasks.router import retry_task
from core import config as core_config
from core.research_decision import ModuleOpinion, decide_research


class TemporaryStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db = store._DB
        self.temp_dir = Path(tempfile.mkdtemp(prefix="quanthub-test-"))
        database.dispose_engines()
        store._DB = self.temp_dir / "store.db"
        store._init()

    def tearDown(self) -> None:
        database.dispose_engines()
        store._DB = self.original_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class CursorPaginationTests(TemporaryStoreTestCase):
    def test_research_cursor_has_no_overlap_and_reports_total(self) -> None:
        for index in range(5):
            store.create_research_run(
                symbol=f"60051{index}",
                market="a_shares",
                timeframe="1d",
                modules=[],
                input_data={},
            )

        first = store.list_research_runs_page(limit=2)
        second = store.list_research_runs_page(limit=2, cursor=first["next_cursor"])

        self.assertEqual(first["total"], 5)
        self.assertIsNotNone(first["next_cursor"])
        self.assertTrue(
            {item["id"] for item in first["items"]}.isdisjoint(
                item["id"] for item in second["items"]
            )
        )

    def test_invalid_cursor_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "分页游标无效"):
            store.list_simulation_orders_page(limit=2, cursor="not-a-cursor")

    def test_factor_research_search_result_uses_factor_reader(self) -> None:
        run = store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={},
        )

        result = search_service.search(run["id"])
        item = next(row for row in result["items"] if row["id"] == f"research:{run['id']}")

        self.assertEqual(item["path"], f"/factor-research?run_id={run['id']}")

    def test_analysis_task_cursor_has_no_overlap_and_reports_total(self) -> None:
        for index in range(5):
            store.create_analysis_task(
                kind="pa",
                symbol=f"60051{index}",
                market="a_shares",
                timeframe="1d",
                fingerprint=f"task-{index}",
                request={"timeout_seconds": 90},
            )
        first = store.list_analysis_tasks_page(limit=2)
        second = store.list_analysis_tasks_page(limit=2, cursor=first["next_cursor"])
        self.assertEqual(first["total"], 5)
        self.assertTrue(
            {item["id"] for item in first["items"]}.isdisjoint(
                item["id"] for item in second["items"]
            )
        )

    def test_analysis_cursor_remains_stable_when_a_new_record_is_inserted(self) -> None:
        original_ids = set()
        for index in range(5):
            task = store.create_analysis_task(
                kind="pa",
                symbol=f"60052{index}",
                market="a_shares",
                timeframe="1d",
                fingerprint=f"stable-{index}",
                request={"timeout_seconds": 90},
            )
            original_ids.add(task["id"])

        page = store.list_analysis_tasks_page(limit=2)
        seen = {item["id"] for item in page["items"]}
        inserted = store.create_analysis_task(
            kind="pa",
            symbol="600529",
            market="a_shares",
            timeframe="1d",
            fingerprint="inserted-after-first-page",
            request={"timeout_seconds": 90},
        )
        cursor = page["next_cursor"]
        while cursor:
            page = store.list_analysis_tasks_page(limit=2, cursor=cursor)
            page_ids = {item["id"] for item in page["items"]}
            self.assertTrue(seen.isdisjoint(page_ids))
            seen.update(page_ids)
            cursor = page["next_cursor"]

        self.assertEqual(seen, original_ids)
        self.assertNotIn(inserted["id"], seen)


class AutomationResultLinkTests(TemporaryStoreTestCase):
    def test_run_persists_structured_factor_result_reference(self) -> None:
        research = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["factor_research"],
            input_data={},
        )
        result_type, result_id = automation_service._result_reference(
            {"research_run_id": research["id"]}
        )
        run = automation_repository.create_run("test_job", trigger_type="manual")
        saved = automation_repository.update_run(
            run["id"], {"result_type": result_type, "result_id": result_id}
        )

        self.assertEqual(saved["result_type"], "factor_research")
        self.assertEqual(saved["result_id"], research["id"])


class UnifiedEvaluationTests(TemporaryStoreTestCase):
    def create_running_evaluation(self, fingerprint: str, modules: list[str]) -> dict:
        task = store.create_analysis_task(
            kind="evaluation",
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            fingerprint=fingerprint,
            request={"modules": modules, "timeout_seconds": 30},
        )
        updated = store.update_analysis_task(task["id"], {"status": "running"})
        assert updated is not None
        return updated

    def test_market_only_evaluation_succeeds(self) -> None:
        task = self.create_running_evaluation("evaluation-success", ["market"])
        candles = [{"t": "2026-07-28", "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 10.0}]
        with patch(
            "apps.api.domains.market.service.fetch_kline",
            return_value={"ok": True, "source": "test", "candles": candles},
        ):
            result = task_service._run_evaluation(task, {"modules": ["market"]})

        run = store.get_research_run(result["research_run_id"])
        self.assertTrue(result["ok"])
        self.assertFalse(result["partial"])
        self.assertEqual(result["steps"]["market"]["status"], "succeeded")
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["summary"]["market"]["latest_price"], 101.0)
        self.assertEqual(run["summary"]["market"]["quantitative"]["data_quality"], "不足")

    def test_market_evaluation_persists_selected_methods_and_strategy_lenses(self) -> None:
        task = self.create_running_evaluation("evaluation-quantitative", ["market"])
        candles = [
            {
                "t": f"2026-05-{index + 1:02d}",
                "o": 100.0 + index,
                "h": 102.0 + index,
                "l": 99.0 + index,
                "c": 101.0 + index,
                "v": 1000.0 + index * 10,
            }
            for index in range(30)
        ]
        request = {
            "modules": ["market"],
            "evaluation_profile": "quick",
            "market_methods": ["trend", "drawdown"],
            "strategy_lenses": ["risk_first"],
        }
        with patch(
            "apps.api.domains.market.service.fetch_kline",
            return_value={"ok": True, "source": "test", "candles": candles},
        ):
            result = task_service._run_evaluation(task, request)

        run = store.get_research_run(result["research_run_id"])
        quantitative = run["summary"]["market"]["quantitative"]
        self.assertEqual(run["input"]["evaluation_profile"], "quick")
        self.assertEqual(run["input"]["market_methods"], ["trend", "drawdown"])
        self.assertEqual(quantitative["methods"], ["trend", "drawdown"])
        self.assertEqual(quantitative["strategy_lenses"], ["risk_first"])
        self.assertTrue(any(item["kind"] == "quantitative_evaluation" for item in run["evidence"]))

    def test_evaluation_is_partial_when_news_fails_after_market_succeeds(self) -> None:
        task = self.create_running_evaluation("evaluation-partial", ["market", "news"])
        candles = [{"t": "2026-07-28", "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 10.0}]
        with (
            patch(
                "apps.api.domains.market.service.fetch_kline",
                return_value={"ok": True, "source": "test", "candles": candles},
            ),
            patch(
                "apps.api.domains.news.service.analyze",
                return_value={"ok": False, "error": "新闻测试失败"},
            ),
        ):
            result = task_service._run_evaluation(task, {"modules": ["market", "news"]})

        run = store.get_research_run(result["research_run_id"])
        self.assertTrue(result["ok"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["steps"]["market"]["status"], "succeeded")
        self.assertEqual(result["steps"]["news"]["status"], "failed")
        self.assertEqual(run["status"], "partial")
        self.assertIn("news: 新闻测试失败", run["error"])

    def test_a_share_evaluation_persists_fundamental_and_valuation_evidence(self) -> None:
        modules = ["market", "fundamentals", "valuation"]
        task = self.create_running_evaluation("evaluation-financials", modules)
        candles = [
            {
                "t": "2026-07-28T15:00:00+08:00",
                "o": 100.0,
                "h": 102.0,
                "l": 99.0,
                "c": 101.0,
                "v": 10.0,
            }
        ]
        fundamental = {
            "snapshot_id": "fundamental-1",
            "direction": "long",
            "confidence": 0.8,
            "reason": "盈利改善",
            "execution_eligible": True,
            "provenance": {"source": "fixture", "source_url": "https://example.test/fund"},
        }
        valuation = {
            "snapshot_id": "valuation-1",
            "valuation_range": "fair",
            "direction": "neutral",
            "confidence": 0.7,
            "reason": "估值中性",
            "execution_eligible": True,
            "provenance": {"source": "fixture", "source_url": "https://example.test/value"},
        }
        with (
            patch(
                "apps.api.domains.market.service.fetch_kline",
                return_value={"ok": True, "source": "test", "candles": candles},
            ),
            patch(
                "apps.api.domains.financials.service.evaluate_fundamentals",
                return_value=fundamental,
            ),
            patch(
                "apps.api.domains.financials.service.evaluate_valuation",
                return_value=valuation,
            ),
        ):
            result = task_service._run_evaluation(task, {"modules": modules})

        run = store.get_research_run(result["research_run_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(
            {module: step["status"] for module, step in result["steps"].items()},
            {"market": "succeeded", "fundamentals": "succeeded", "valuation": "succeeded"},
        )
        evidence_kinds = {item["kind"] for item in run["evidence"]}
        self.assertIn("fundamental_snapshot", evidence_kinds)
        self.assertIn("valuation_snapshot", evidence_kinds)
        self.assertIn("action_guidance", evidence_kinds)
        self.assertEqual(run["summary"]["action_guidance"]["holding_status"], "not_held")
        decision_modules = {
            item["module"] for item in run["summary"]["research_decision"]["module_opinions"]
        }
        self.assertIn("fundamentals", decision_modules)
        self.assertIn("valuation", decision_modules)

    def test_failed_step_is_persisted_on_research_run(self) -> None:
        task = store.create_analysis_task(
            kind="evaluation",
            symbol="BTC-USDT",
            market="crypto",
            timeframe="1d",
            fingerprint="evaluation-failure",
            request={"modules": ["market"], "timeout_seconds": 30},
        )
        task = store.update_analysis_task(task["id"], {"status": "running"})
        assert task is not None

        with patch.dict(os.environ, {"QUANTHUB_DISABLE_MARKET_FETCH": "1"}):
            result = task_service._run_evaluation(task, {"modules": ["market"]})

        run = store.get_research_run(result["research_run_id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["steps"]["market"]["status"], "failed")
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "failed")
        self.assertTrue(run["error"])

    def test_timeout_preserves_research_result_and_error(self) -> None:
        run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["market", "news"],
            input_data={"evaluation": True},
        )
        store.update_research_run(
            run["id"], {"status": "running", "summary": {"market": {"latest_price": 100.0}}}
        )
        task = store.create_analysis_task(
            kind="evaluation",
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            fingerprint="evaluation-timeout",
            request={"timeout_seconds": 10},
        )
        task = store.update_analysis_task(
            task["id"],
            {
                "status": "running",
                "started_at": time.time() - 20,
                "result": {
                    "research_run_id": run["id"],
                    "steps": {
                        "market": {"status": "succeeded", "error": None},
                        "news": {"status": "running", "error": None},
                    },
                },
            },
        )
        assert task is not None

        timed_out = task_service.refresh_timeout(task)
        saved_run = store.get_research_run(run["id"])

        self.assertEqual(timed_out["status"], "timeout")
        self.assertIn("任务超过 10 秒", timed_out["error"])
        self.assertIsNotNone(saved_run)
        self.assertEqual(saved_run["status"], "timeout")
        self.assertEqual(saved_run["summary"]["market"]["latest_price"], 100.0)
        self.assertEqual(saved_run["error"], timed_out["error"])

    def test_cancel_preserves_research_summary_and_marks_run_cancelled(self) -> None:
        run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["market", "news"],
            input_data={},
        )
        store.update_research_run(
            run["id"], {"status": "running", "summary": {"market": {"latest_price": 101.0}}}
        )
        task = self.create_running_evaluation("evaluation-cancel", ["market", "news"])
        task = store.update_analysis_task(
            task["id"],
            {
                "result": {
                    "research_run_id": run["id"],
                    "steps": {
                        "market": {"status": "succeeded", "error": None},
                        "news": {"status": "running", "error": None},
                    },
                }
            },
        )

        cancelled = task_service.cancel_task(task)
        saved_run = store.get_research_run(run["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["error"], "用户取消")
        self.assertEqual(saved_run["status"], "cancelled")
        self.assertEqual(saved_run["summary"]["market"]["latest_price"], 101.0)

    def test_retry_uses_failed_modules_and_existing_research_run(self) -> None:
        run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["market", "news"],
            input_data={},
        )
        task = self.create_running_evaluation("evaluation-retry", ["market", "news"])
        task = store.update_analysis_task(
            task["id"],
            {
                "status": "failed",
                "result": {
                    "research_run_id": run["id"],
                    "steps": {
                        "market": {"status": "failed", "error": "行情失败"},
                        "news": {"status": "succeeded", "error": None},
                    },
                },
                "error": "market: 行情失败",
            },
        )
        retried = {**task, "id": "RETRY-1", "attempt": 2, "status": "queued"}
        request = Request({"type": "http", "headers": []})
        request.state.principal = {"id": "local-user"}
        with patch.object(task_service, "submit_task", return_value=(retried, False)) as submit:
            response = retry_task(task["id"], request)

        self.assertEqual(response["task"]["id"], "RETRY-1")
        payload = submit.call_args.kwargs["payload"]
        self.assertEqual(payload["modules"], ["market"])
        self.assertEqual(payload["research_run_id"], run["id"])

    def test_retry_accepts_partial_success_and_runs_only_failed_modules(self) -> None:
        run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["market", "news"],
            input_data={},
        )
        task = self.create_running_evaluation("evaluation-partial-retry", ["market", "news"])
        task = store.update_analysis_task(
            task["id"],
            {
                "status": "succeeded",
                "result": {
                    "partial": True,
                    "research_run_id": run["id"],
                    "steps": {
                        "market": {"status": "succeeded", "error": None},
                        "news": {"status": "failed", "error": "新闻失败"},
                    },
                },
            },
        )
        retried = {**task, "id": "RETRY-PARTIAL", "attempt": 2, "status": "queued"}
        request = Request({"type": "http", "headers": []})
        request.state.principal = {"id": "local-user"}
        with patch.object(task_service, "submit_task", return_value=(retried, False)) as submit:
            response = retry_task(task["id"], request)

        self.assertEqual(response["task"]["id"], "RETRY-PARTIAL")
        self.assertEqual(submit.call_args.kwargs["payload"]["modules"], ["news"])
        self.assertEqual(submit.call_args.kwargs["payload"]["research_run_id"], run["id"])


class MultiMarketInstrumentSearchTests(TemporaryStoreTestCase):
    def test_exact_us_symbol_is_resolved_and_filtered_by_market(self) -> None:
        with patch(
            "apps.api.domains.portfolio.service.tencent_quote_detail",
            return_value=("NVIDIA", 120.0, 118.0),
        ):
            results = instrument_service.search("nvda", market="us_stocks")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].instrument_id, "us_stocks:NVDA")
        self.assertEqual(results[0].name, "NVIDIA")
        self.assertEqual(instrument_service.search("NVDA", market="a_shares"), [])

    def test_exact_crypto_pair_is_registered_without_remote_lookup(self) -> None:
        results = instrument_service.search("btc-usdt", market="crypto")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].instrument_id, "crypto:BTC-USDT")
        self.assertEqual(results[0].asset_class, "crypto")


class SignalSimulationLedgerTests(TemporaryStoreTestCase):
    def test_accepted_signal_converts_to_order_and_syncs_fill_to_ledger(self) -> None:
        signal = signal_service.publish(
            PublishSignalRequest(
                symbol="600519",
                market="a_shares",
                direction="buy",
                score=0.8,
                confidence=0.7,
                source="workflow_test",
                timeframe="1d",
            )
        )
        accepted = signal_service.review(signal["id"], target="accepted", note="测试通过")
        self.assertEqual(accepted["status"], "accepted")

        with patch.object(portfolio_service, "latest_close", return_value=100.0):
            order = simulation_service.create_order(
                SimulationOrderCreate(
                    signal_id=signal["id"],
                    quantity=100,
                )
            )
        converted = store.get_signal(signal["id"])
        self.assertEqual(converted["status"], "converted")
        self.assertEqual(converted["order_id"], order["id"])

        filled = simulation_service.fill_order(
            order["id"], SimulationFillCreate(price=100.0, fee_rate=0.001)
        )
        execution = filled["executions"][0]
        self.assertEqual(filled["status"], "filled")
        self.assertEqual(execution["ledger_sync_status"], "synced")
        self.assertEqual(execution["ledger_trade_id"], f"simulation:{execution['id']}")
        trade = ledger_repository.get_trade(execution["ledger_trade_id"])
        self.assertIsNotNone(trade)
        self.assertEqual(trade.code, "600519")
        self.assertEqual(trade.quantity, 100)

    def test_paper_order_persists_research_audit_and_side_aware_slippage(self) -> None:
        research_run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["market", "factor"],
            input_data={},
        )
        decision = decide_research(
            [
                ModuleOpinion(module="market", direction="short", evidence_at=datetime.now(UTC)),
                ModuleOpinion(module="factor", direction="short", evidence_at=datetime.now(UTC)),
            ]
        )
        store.update_research_run(
            research_run["id"],
            {"summary": {"research_decision": decision.model_dump(mode="json")}},
        )
        with patch.object(portfolio_service, "latest_close", return_value=100.0):
            order = simulation_service.create_order(
                SimulationOrderCreate(
                    symbol="600519",
                    market="a_shares",
                    side="sell",
                    quantity=100,
                    factor_key="mean_reversion",
                    factor_version="1.0.0",
                    research_run_id=research_run["id"],
                    rebalance_cycle_id="cycle-001",
                    capacity_used=0.08,
                )
            )

        self.assertFalse(order["audit"]["live_trading_enabled"])
        self.assertEqual(order["audit"]["factor_key"], "mean_reversion")
        self.assertEqual(order["audit"]["theoretical_price"], 100.0)
        self.assertEqual(order["audit"]["capacity_used"], 0.08)
        self.assertTrue(order["audit"]["signal_time"])
        self.assertTrue(order["audit"]["tradable_time"])

        filled = simulation_service.fill_order(
            order["id"], SimulationFillCreate(price=99.5, fee_rate=0.001)
        )
        execution = filled["executions"][0]
        self.assertEqual(execution["theoretical_price"], 100.0)
        self.assertEqual(execution["simulated_price"], 99.5)
        self.assertEqual(execution["slippage_bps"], 50.0)
        self.assertEqual(execution["capacity_used"], 0.08)
        self.assertFalse(execution["live_trading_enabled"])

    def test_cancelled_paper_order_records_rejection_reason(self) -> None:
        with patch.object(portfolio_service, "latest_close", return_value=100.0):
            order = simulation_service.create_order(
                SimulationOrderCreate(
                    symbol="600519",
                    market="a_shares",
                    side="buy",
                    quantity=100,
                )
            )

        cancelled = store.cancel_simulation_order(
            order["id"], rejection_reason="capacity_gate_failed"
        )

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["audit"]["rejection_reason"], "capacity_gate_failed")
        self.assertFalse(cancelled["audit"]["live_trading_enabled"])


class AlertCenterTests(TemporaryStoreTestCase):
    def create_price_rule(self, **overrides):
        payload = {
            "name": "贵州茅台价格提醒",
            "rule_type": "price_above",
            "symbol": "600519",
            "market": "a_shares",
            "threshold": 1500.0,
            "enabled": True,
            "frequency_minutes": 15,
            "quiet_start": None,
            "quiet_end": None,
            "expires_at": None,
            "context": {},
        }
        payload.update(overrides)
        return alert_service.create_rule("local-user", payload)

    def test_price_rule_triggers_and_event_can_be_acknowledged(self) -> None:
        rule = self.create_price_rule()
        with (
            patch.object(alert_service, "_quote_observation", return_value=(1600.0, 1.2)),
            patch("core.alert.get_notifier") as get_notifier,
        ):
            get_notifier.return_value.send.return_value = {"webhook": True}
            result = alert_service.check_rule(rule, force=True)

        self.assertTrue(result["triggered"])
        self.assertEqual(result["event"]["observed_value"], 1600.0)
        self.assertEqual(result["event"]["related_type"], "instrument")
        self.assertEqual(result["event"]["related_id"], "600519")
        self.assertEqual(result["event"]["rule_name"], "贵州茅台价格提醒")
        self.assertEqual(result["event"]["symbol"], "600519")
        self.assertEqual(result["event"]["market"], "a_shares")
        acknowledged = alert_service.acknowledge_event(result["event"]["id"], "local-user")
        self.assertIsNotNone(acknowledged)
        self.assertEqual(acknowledged["status"], "acknowledged")
        self.assertIsNotNone(acknowledged["acknowledged_at"])

    def test_disabled_expired_and_quiet_rules_do_not_create_events(self) -> None:
        disabled = alert_service.update_rule(
            self.create_price_rule()["id"], "local-user", {"enabled": False}
        )
        self.assertIsNotNone(disabled)
        self.assertFalse(alert_service.check_rule(disabled, force=True)["checked"])

        expired = self.create_price_rule(expires_at=time.time() - 1)
        self.assertFalse(alert_service.check_rule(expired, force=True)["checked"])

        quiet = self.create_price_rule(quiet_start="09:00", quiet_end="11:00")
        shanghai_time = datetime(2026, 7, 28, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        self.assertTrue(alert_service._in_quiet_period(quiet, shanghai_time))
        with (
            patch.object(alert_service, "_quote_observation", return_value=(1600.0, 1.2)),
            patch.object(alert_service.time, "time", return_value=shanghai_time),
        ):
            result = alert_service.check_rule(quiet, force=True)
        self.assertFalse(result["triggered"])
        self.assertTrue(result["quiet"])
        self.assertEqual(alert_service.list_events("local-user")["count"], 0)

    def test_evaluation_change_uses_first_result_as_baseline(self) -> None:
        first_run = store.create_research_run(
            symbol="600519", market="a_shares", timeframe="1d", modules=["ensemble"], input_data={}
        )
        store.update_research_run(
            first_run["id"],
            {
                "status": "succeeded",
                "summary": {"ensemble": {"consensus": {"direction": "bullish"}}},
            },
        )
        rule = alert_service.create_rule(
            "local-user",
            {
                "name": "贵州茅台评估变化",
                "rule_type": "evaluation_changed",
                "symbol": "600519",
                "market": "a_shares",
                "threshold": None,
                "enabled": True,
                "frequency_minutes": 15,
                "quiet_start": None,
                "quiet_end": None,
                "expires_at": None,
                "context": {},
            },
        )

        baseline = alert_service.check_rule(rule, force=True)
        self.assertFalse(baseline["triggered"])
        saved_rule = alert_service.get_rule(rule["id"], "local-user")
        self.assertEqual(saved_rule["context"]["last_direction"], "bullish")

        second_run = store.create_research_run(
            symbol="600519", market="a_shares", timeframe="1d", modules=["ensemble"], input_data={}
        )
        store.update_research_run(
            second_run["id"],
            {
                "status": "partial",
                "summary": {"ensemble": {"consensus": {"direction": "bearish"}}},
            },
        )
        with patch("core.alert.get_notifier") as get_notifier:
            get_notifier.return_value.send.return_value = {}
            changed = alert_service.check_rule(
                alert_service.get_rule(rule["id"], "local-user"), force=True
            )
        self.assertTrue(changed["triggered"])
        self.assertEqual(changed["event"]["related_type"], "research_run")
        self.assertEqual(changed["event"]["related_id"], second_run["id"])
        self.assertEqual(changed["event"]["related_modules"], ["ensemble"])

    def test_evaluation_change_reads_only_the_rule_owner_runs(self) -> None:
        alice = governance_repository.create_user("alert_alice", "Alert Alice", ["reviewer"])
        bob = governance_repository.create_user("alert_bob", "Alert Bob", ["reviewer"])
        alice_run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["ensemble"],
            input_data={},
            owner_id=alice["id"],
        )
        store.update_research_run(
            alice_run["id"],
            {
                "status": "succeeded",
                "summary": {"research_decision": {"direction": "long"}},
            },
        )
        bob_run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["ensemble"],
            input_data={},
            owner_id=bob["id"],
        )
        store.update_research_run(
            bob_run["id"],
            {
                "status": "succeeded",
                "summary": {"research_decision": {"direction": "short"}},
            },
        )
        rule = alert_service.create_rule(
            alice["id"],
            {
                "name": "Alice 研究结论变化",
                "rule_type": "evaluation_changed",
                "symbol": "600519",
                "market": "a_shares",
                "threshold": None,
                "enabled": True,
                "frequency_minutes": 15,
                "quiet_start": None,
                "quiet_end": None,
                "expires_at": None,
                "context": {},
            },
        )

        baseline = alert_service.check_rule(rule, force=True)

        self.assertFalse(baseline["triggered"])
        saved = alert_service.get_rule(rule["id"], alice["id"])
        self.assertEqual(saved["context"]["last_direction"], "long")

    def test_research_event_alert_types_route_to_domain_observations(self) -> None:
        cases = {
            "earnings_released": "_earnings_release",
            "valuation_band_crossed": "_valuation_band",
            "major_company_event": "_major_company_event",
            "macro_calendar": "_macro_calendar",
        }
        for rule_type, helper_name in cases.items():
            with self.subTest(rule_type=rule_type):
                rule = self.create_price_rule(
                    name=f"{rule_type} fixture",
                    rule_type=rule_type,
                    threshold=0.5 if rule_type == "valuation_band_crossed" else None,
                    context={"metric": "pe_ttm"} if rule_type == "valuation_band_crossed" else {},
                )
                with (
                    patch.object(
                        alert_service,
                        helper_name,
                        return_value=(True, 0.75, "research_fixture", "fixture-id"),
                    ),
                    patch("core.alert.get_notifier") as get_notifier,
                ):
                    get_notifier.return_value.send.return_value = {}
                    result = alert_service.check_rule(rule, force=True)
                self.assertTrue(result["triggered"])
                self.assertEqual(result["event"]["related_type"], "research_fixture")
                self.assertEqual(result["event"]["related_id"], "fixture-id")


class GovernanceTests(TemporaryStoreTestCase):
    def test_research_runs_tasks_and_preferences_are_isolated_by_user(self) -> None:
        from apps.api.main import app

        alice = governance_repository.create_user("alice_research", "Alice", ["reviewer"])
        bob = governance_repository.create_user("bob_research", "Bob", ["reviewer"])
        alice_token = governance_repository.create_token(alice["id"], "alice", None)["token"]
        bob_token = governance_repository.create_token(bob["id"], "bob", None)["token"]
        alice_run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=[],
            input_data={},
            owner_id=alice["id"],
        )
        bob_run = store.create_research_run(
            symbol="000333",
            market="a_shares",
            timeframe="1d",
            modules=[],
            input_data={},
            owner_id=bob["id"],
        )
        alice_task = store.create_analysis_task(
            kind="evaluation",
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            fingerprint="alice-task",
            request={},
            owner_id=alice["id"],
        )
        store.create_analysis_task(
            kind="evaluation",
            symbol="000333",
            market="a_shares",
            timeframe="1d",
            fingerprint="bob-task",
            request={},
            owner_id=bob["id"],
        )
        env = {
            "QUANTHUB_DEPLOYMENT_MODE": "lan",
            "QUANTHUB_AUTH_REQUIRED": "1",
            "QUANTHUB_BOOTSTRAP_ADMIN_TOKEN": "",
        }
        with patch.dict(os.environ, env):
            client = TestClient(app)
            alice_headers = {"Authorization": f"Bearer {alice_token}"}
            bob_headers = {"Authorization": f"Bearer {bob_token}"}
            alice_preference = client.put(
                "/research/preferences/me",
                headers=alice_headers,
                json={"default_mode": "quick", "terminology_level": "plain"},
            )
            bob_preference = client.put(
                "/research/preferences/me",
                headers=bob_headers,
                json={"default_mode": "professional", "terminology_level": "technical"},
            )
            alice_runs = client.get("/research/runs", headers=alice_headers).json()["runs"]
            bob_runs = client.get("/research/runs", headers=bob_headers).json()["runs"]
            alice_tasks = client.get("/analysis/tasks", headers=alice_headers).json()["tasks"]
            cross_run = client.get(f"/research/runs/{bob_run['id']}", headers=alice_headers)
            cross_task = client.get(f"/analysis/tasks/{alice_task['id']}", headers=bob_headers)

        self.assertEqual(alice_preference.status_code, 200)
        self.assertEqual(alice_preference.json()["preference"]["default_mode"], "quick")
        self.assertEqual(bob_preference.json()["preference"]["default_mode"], "professional")
        self.assertEqual([item["id"] for item in alice_runs], [alice_run["id"]])
        self.assertEqual([item["id"] for item in bob_runs], [bob_run["id"]])
        self.assertEqual([item["id"] for item in alice_tasks], [alice_task["id"]])
        self.assertEqual(cross_run.status_code, 404)
        self.assertEqual(cross_task.status_code, 404)

    def test_relationship_and_transmission_queries_are_isolated_by_user(self) -> None:
        from apps.api.main import app

        alice = governance_repository.create_user("alice_macro", "Alice Macro", ["reviewer"])
        bob = governance_repository.create_user("bob_macro", "Bob Macro", ["reviewer"])
        alice_token = governance_repository.create_token(alice["id"], "alice macro", None)["token"]
        bob_token = governance_repository.create_token(bob["id"], "bob macro", None)["token"]
        relationship = {
            "relationship_id": "shared-relationship-id",
            "instrument_id": "a_shares:600519",
            "target_type": "rate",
            "target_key": "PBOC_POLICY_RATE",
            "relation_source": "user",
            "direction": "negative",
            "strength": 0.8,
            "valid_from": "2026-01-01T00:00:00Z",
            "method_version": "relationship-test-v1",
            "provenance": {
                "source": "fixture",
                "published_at": "2026-01-01T00:00:00Z",
                "available_at": "2026-01-01T00:00:00Z",
                "fetched_at": "2026-01-01T00:00:01Z",
                "revision": "1",
                "content_hash": "a" * 64,
            },
        }
        transmission = {
            "transmission_id": "shared-transmission-id",
            "event_id": "macro-event-fixture",
            "instrument_id": "a_shares:600519",
            "relationship_id": "shared-relationship-id",
            "channel": "rates",
            "order": "direct",
            "direction": "negative",
            "horizon": "medium",
            "strength": 0.7,
            "evidence_level": "medium",
            "counterexamples": [],
            "method_version": "macro-transmission-v1",
        }
        env = {
            "QUANTHUB_DEPLOYMENT_MODE": "lan",
            "QUANTHUB_AUTH_REQUIRED": "1",
            "QUANTHUB_BOOTSTRAP_ADMIN_TOKEN": "",
        }
        with patch.dict(os.environ, env):
            client = TestClient(app)
            alice_headers = {"Authorization": f"Bearer {alice_token}"}
            bob_headers = {"Authorization": f"Bearer {bob_token}"}
            self.assertEqual(
                client.post(
                    "/research-data/relationships", headers=alice_headers, json=relationship
                ).status_code,
                201,
            )
            bob_relationship = {**relationship, "target_key": "USER_CONFIGURED_RATE"}
            self.assertEqual(
                client.post(
                    "/research-data/relationships", headers=bob_headers, json=bob_relationship
                ).status_code,
                201,
            )
            store.save_macro_transmission(transmission, owner_id=alice["id"])
            store.save_macro_transmission(
                {**transmission, "direction": "positive"}, owner_id=bob["id"]
            )
            alice_relationships = client.get(
                "/research-data/relationships?instrument_id=a_shares%3A600519",
                headers=alice_headers,
            ).json()["items"]
            bob_relationships = client.get(
                "/research-data/relationships?instrument_id=a_shares%3A600519",
                headers=bob_headers,
            ).json()["items"]
            alice_transmissions = client.get(
                "/research-data/transmissions?instrument_id=a_shares%3A600519",
                headers=alice_headers,
            ).json()["items"]
            bob_transmissions = client.get(
                "/research-data/transmissions?instrument_id=a_shares%3A600519",
                headers=bob_headers,
            ).json()["items"]

        self.assertEqual([item["target_key"] for item in alice_relationships], ["PBOC_POLICY_RATE"])
        self.assertEqual(
            [item["target_key"] for item in bob_relationships], ["USER_CONFIGURED_RATE"]
        )
        self.assertEqual([item["direction"] for item in alice_transmissions], ["negative"])
        self.assertEqual([item["direction"] for item in bob_transmissions], ["positive"])

    def test_watchlist_is_owner_scoped_and_includes_latest_research_state(self) -> None:
        from apps.api.main import app

        alice = governance_repository.create_user("alice_watch", "Alice Watch", ["admin"])
        bob = governance_repository.create_user("bob_watch", "Bob Watch", ["admin"])
        alice_token = governance_repository.create_token(alice["id"], "alice watch", None)["token"]
        bob_token = governance_repository.create_token(bob["id"], "bob watch", None)["token"]
        alice_watch = store.add_watchlist(
            "600519", "贵州茅台", "a_shares", "a_shares:600519", owner_id=alice["id"]
        )
        store.add_watchlist("AAPL", "Apple", "us_stocks", "us_stocks:AAPL", owner_id=bob["id"])
        run = store.create_research_run(
            symbol="600519",
            market="a_shares",
            timeframe="1d",
            modules=["market"],
            input_data={},
            owner_id=alice["id"],
        )
        store.update_research_run(
            run["id"],
            {
                "status": "succeeded",
                "summary": {
                    "research_decision": {
                        "direction": "long",
                        "execution_eligible": True,
                    }
                },
            },
        )
        env = {
            "QUANTHUB_DEPLOYMENT_MODE": "lan",
            "QUANTHUB_AUTH_REQUIRED": "1",
            "QUANTHUB_BOOTSTRAP_ADMIN_TOKEN": "",
        }
        with (
            patch.dict(os.environ, env),
            patch.object(
                portfolio_service,
                "quote_item",
                side_effect=lambda symbol, market, name="": {
                    "sym": symbol,
                    "name": name,
                    "market": market,
                    "price": 100.0,
                    "chgPct": 1.0,
                    "available": True,
                },
            ),
        ):
            client = TestClient(app)
            alice_headers = {"Authorization": f"Bearer {alice_token}"}
            bob_headers = {"Authorization": f"Bearer {bob_token}"}
            alice_items = client.get("/market/watchlist", headers=alice_headers).json()["items"]
            bob_items = client.get("/market/watchlist", headers=bob_headers).json()["items"]
            cross_delete = client.delete(
                f"/market/watchlist/{alice_watch['id']}", headers=bob_headers
            )

        self.assertEqual([item["sym"] for item in alice_items], ["600519"])
        self.assertEqual([item["sym"] for item in bob_items], ["AAPL"])
        self.assertEqual(alice_items[0]["research_direction"], "long")
        self.assertEqual(alice_items[0]["latest_research_run_id"], run["id"])
        self.assertEqual(cross_delete.status_code, 404)

    def test_deactivating_user_revokes_tokens_and_reactivation_keeps_them_revoked(self) -> None:
        user = governance_repository.create_user("api_test", "API Test", ["viewer"])
        token = governance_repository.create_token(user["id"], "test token", None)
        self.assertIsNotNone(governance_repository.principal_by_token(token["token"]))

        inactive = governance_repository.set_user_active(user["id"], False)
        self.assertFalse(inactive["active"])
        self.assertIsNone(governance_repository.principal_by_token(token["token"]))

        active = governance_repository.set_user_active(user["id"], True)
        self.assertTrue(active["active"])
        self.assertIsNone(governance_repository.principal_by_token(token["token"]))
        saved_token = next(
            item for item in governance_repository.list_tokens() if item["id"] == token["id"]
        )
        self.assertIsNotNone(saved_token["revoked_at"])

    def test_remote_auth_returns_401_and_403(self) -> None:
        from apps.api.main import app

        viewer = governance_repository.create_user("remote_viewer", "Remote Viewer", ["viewer"])
        token = governance_repository.create_token(viewer["id"], "remote", None)
        with patch.dict(
            os.environ,
            {
                "QUANTHUB_DEPLOYMENT_MODE": "lan",
                "QUANTHUB_AUTH_REQUIRED": "1",
                "QUANTHUB_BOOTSTRAP_ADMIN_TOKEN": "",
            },
        ):
            client = TestClient(app)
            unauthorized = client.get("/auth/session")
            forbidden = client.post(
                "/alerts/check", headers={"Authorization": f"Bearer {token['token']}"}
            )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.json()["detail"], "需要有效的 Bearer token")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["detail"], "缺少权限: research.write")


class NotificationSettingsTests(unittest.TestCase):
    def test_notification_status_masks_every_configured_value(self) -> None:
        secrets = {
            "WECOM_WEBHOOK_URL": "https://wecom.example/secret-key",
            "WECOM_MENTIONED_MOBILE": "13800138000",
            "ALERT_WEBHOOK_URL": "https://alerts.example/private",
            "TG_BOT_TOKEN": "123456789:telegram-secret",
            "TG_CHAT_ID": "-1001234567890",
        }
        with (
            patch.object(
                settings_service,
                "get_config",
                return_value={
                    "alert": {"enabled": True, "channels": ["wecom", "webhook", "telegram"]}
                },
            ),
            patch.object(
                settings_service.repository,
                "read_runtime_secret",
                side_effect=lambda env_name: secrets.get(env_name),
            ),
        ):
            status = settings_service.notification_status()

        rendered = repr(status)
        for secret in secrets.values():
            self.assertNotIn(secret, rendered)
        self.assertTrue(status["enabled"])
        self.assertTrue(all(item["configured"] for item in status["channels"]))
        self.assertEqual(
            next(item for item in status["channels"] if item["channel"] == "wecom")["fields"][
                "webhook_url"
            ],
            "http...-key",
        )


class LLMSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            "llm": {
                "provider": "deepseek",
                "deepseek": {
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "timeout": 60,
                    "max_retries": 3,
                },
                "openai": {"api_key_env": "OPENAI_API_KEY"},
                "custom": {
                    "api_key_env": "QUANTHUB_CUSTOM_LLM_API_KEY",
                    "base_url": "https://custom.example/v1",
                    "model": "custom-model",
                    "timeout": 120,
                    "max_retries": 2,
                },
            }
        }

    def test_credential_status_exposes_settings_without_secret(self) -> None:
        secrets = {"DEEPSEEK_API_KEY": "fixture-secret-value", "OPENAI_API_KEY": None}
        with (
            patch.object(settings_service, "get_config", return_value=self.config),
            patch.object(
                settings_service.repository,
                "read_runtime_secret",
                side_effect=lambda env_name: secrets.get(env_name),
            ),
        ):
            status = settings_service.credential_status()

        self.assertTrue(status["configured"])
        self.assertEqual(status["masked"], "fixt...alue")
        self.assertEqual(status["models_endpoint"], "https://api.deepseek.com/models")
        self.assertNotIn("fixture-secret-value", repr(status))
        self.assertEqual(
            [item["id"] for item in status["providers"]], ["deepseek", "openai", "custom"]
        )
        custom = next(item for item in status["providers"] if item["id"] == "custom")
        self.assertEqual(custom["base_url"], "https://custom.example/v1")
        self.assertEqual(custom["model"], "custom-model")
        self.assertEqual(custom["timeout"], 120)

    def test_update_llm_settings_persists_runtime_overrides(self) -> None:
        secrets: dict[str, str] = {}
        with (
            patch.object(settings_service, "get_config", return_value=self.config) as get_config,
            patch.object(settings_service.repository, "write_secret") as write_secret,
            patch.object(
                settings_service.repository,
                "read_runtime_secret",
                side_effect=lambda env_name: secrets.get(env_name),
            ),
            patch.object(
                settings_service.repository,
                "set_runtime_secret",
                side_effect=lambda env_name, value: secrets.__setitem__(env_name, value),
            ),
            patch.object(settings_service, "reset_clients") as reset_clients,
        ):
            payload = {
                "provider": "deepseek",
                "base_url": "https://gateway.example/v1",
                "model": "deepseek-chat",
                "timeout": 90,
                "max_retries": 4,
            }
            payload["api_key"] = "fixture-new-secret"
            result = settings_service.update_llm_settings(payload)

        self.assertTrue(result["configured"])
        self.assertEqual(secrets["DEEPSEEK_API_KEY"], "fixture-new-secret")
        write_secret.assert_any_call("QUANTHUB_LLM_BASE_URL", "https://gateway.example/v1")
        write_secret.assert_any_call("QUANTHUB_LLM_DEEPSEEK_BASE_URL", "https://gateway.example/v1")
        write_secret.assert_any_call("QUANTHUB_LLM_TIMEOUT", "90")
        get_config.cache_clear.assert_called_once()
        reset_clients.assert_called_once()

    def test_config_loader_applies_llm_runtime_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QUANTHUB_LLM_PROVIDER": "custom",
                "QUANTHUB_LLM_BASE_URL": "http://localhost:9000/v1",
                "QUANTHUB_LLM_MODEL": "local-test-model",
                "QUANTHUB_LLM_TIMEOUT": "45",
                "QUANTHUB_LLM_MAX_RETRIES": "1",
            },
        ):
            core_config.get_config.cache_clear()
            config = core_config.get_config()
        core_config.get_config.cache_clear()

        self.assertEqual(config["llm"]["provider"], "custom")
        self.assertEqual(config["llm"]["custom"]["base_url"], "http://localhost:9000/v1")
        self.assertEqual(config["llm"]["custom"]["model"], "local-test-model")
        self.assertEqual(config["llm"]["custom"]["timeout"], 45)

    def test_config_loader_resolves_all_provider_keys_and_saved_settings(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QUANTHUB_LLM_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "must-not-leak",
                "QUANTHUB_CUSTOM_LLM_API_KEY": "must-not-leak",
                "QUANTHUB_LLM_CUSTOM_BASE_URL": "https://custom.example/v1",
                "QUANTHUB_LLM_CUSTOM_MODEL": "custom-model",
                "QUANTHUB_LLM_CUSTOM_TIMEOUT": "180",
                "QUANTHUB_LLM_CUSTOM_MAX_RETRIES": "4",
            },
            clear=False,
        ):
            core_config.get_config.cache_clear()
            config = core_config.get_config()
        core_config.get_config.cache_clear()

        self.assertEqual(config["llm"]["provider"], "deepseek")
        self.assertEqual(config["llm"]["custom"]["api_key"], "must-not-leak")
        self.assertEqual(config["llm"]["custom"]["base_url"], "https://custom.example/v1")
        self.assertEqual(config["llm"]["custom"]["model"], "custom-model")
        self.assertEqual(config["llm"]["custom"]["timeout"], 180)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

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
        with patch.object(task_service, "submit_task", return_value=(retried, False)) as submit:
            response = retry_task(task["id"])

        self.assertEqual(response["task"]["id"], "RETRY-1")
        payload = submit.call_args.kwargs["payload"]
        self.assertEqual(payload["modules"], ["market"])
        self.assertEqual(payload["research_run_id"], run["id"])


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

        order = simulation_service.create_order(
            SimulationOrderCreate(
                signal_id=signal["id"],
                quantity=10,
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
        self.assertEqual(trade.quantity, 10)

    def test_paper_order_persists_research_audit_and_side_aware_slippage(self) -> None:
        with patch.object(portfolio_service, "latest_close", return_value=100.0):
            order = simulation_service.create_order(
                SimulationOrderCreate(
                    symbol="600519",
                    market="a_shares",
                    side="sell",
                    quantity=20,
                    factor_key="mean_reversion",
                    factor_version="1.0.0",
                    research_run_id="research-001",
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
                    quantity=10,
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


class GovernanceTests(TemporaryStoreTestCase):
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


if __name__ == "__main__":
    unittest.main()

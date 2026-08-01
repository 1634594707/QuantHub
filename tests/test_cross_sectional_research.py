from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from apps.api import database, store
from apps.api.domains.factor_research import service
from apps.api.domains.factor_research.schemas import (
    CrossSectionResearchRequest,
    FactorUniverseCreate,
    FactorUniverseMemberUpsert,
)
from apps.api.domains.instrument.domain import Instrument
from core.cross_sectional_research import (
    CrossSectionConfig,
    analyze_cross_sectional_factors,
    analyze_cross_sectional_panel,
)


def member(symbol: str, index: int, **overrides) -> dict:
    result = {
        "symbol": symbol,
        "effective_from": "2024-01-01",
        "effective_to": None,
        "status": "active",
        "industry": "科技" if index % 2 else "金融",
        "market_cap": float(1_000_000_000 + index * 100_000_000),
        "beta": 0.8 + index * 0.03,
        "is_st": False,
        "listed_at": "2020-01-01",
        "delisted_at": None,
    }
    result.update(overrides)
    return result


class CrossSectionEngineTests(unittest.TestCase):
    def test_residual_multi_horizon_and_group_stability_reports_are_complete(self) -> None:
        members = [member(f"S{index:02d}", index) for index in range(12)]
        frames = {}
        periods = 120
        time_index = np.arange(periods)
        for index, item in enumerate(members):
            close = (
                80
                + index * 3
                + time_index * (0.04 + index * 0.004)
                + np.sin(time_index / 6 + index * 0.4) * (1 + index * 0.05)
            )
            frames[item["symbol"]] = pd.DataFrame(
                {
                    "datetime": pd.date_range("2024-10-01", periods=periods, freq="D"),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000 + index * 50_000 + time_index * 1_000,
                }
            )

        result = analyze_cross_sectional_factors(
            frames,
            members,
            CrossSectionConfig(
                factor_key="momentum_20",
                min_assets=8,
                minimum_effective_dates=20,
                minimum_valid_assets=8,
                neutralize_industry=False,
                neutralize_market_cap=False,
                neutralize_beta=False,
            ),
        )

        self.assertEqual(
            result["summary"]["primary_label"],
            "market_industry_neutral_residual_return",
        )
        self.assertIn("raw_return_rank_ic_mean", result["summary"])
        label_segments = {item["segment"] for item in result["stability"]["labels"]}
        for horizon in (1, 3, 5, 10, 20):
            self.assertIn(f"residual_forward_return_{horizon}", label_segments)
            self.assertIn(f"residual_risk_adjusted_return_{horizon}", label_segments)
        time_segments = {item["segment"].split(":", 1)[0] for item in result["stability"]["time"]}
        self.assertEqual(
            time_segments,
            {"year", "market", "trend", "volatility", "liquidity"},
        )
        self.assertTrue(result["stability"]["cross_section"]["industry"])
        self.assertTrue(result["stability"]["cross_section"]["market_cap"])
        self.assertTrue(result["stability"]["cross_section"]["liquidity"])
        self.assertTrue(result["stability"]["cross_section"]["listing_age"])

    def test_rank_ic_quantiles_neutralization_and_capacity_are_computed(self) -> None:
        members = [member(f"S{index:02d}", index) for index in range(12)]
        rows = []
        for day in pd.date_range("2025-01-01", periods=30, freq="D"):
            for index, item in enumerate(members):
                signal = ((index * 5 + day.day) % 12) - 5.5
                industry_effect = 2.0 if item["industry"] == "科技" else -1.0
                factor = (
                    signal + industry_effect + np.log(item["market_cap"]) * 0.2 + item["beta"] * 3
                )
                rows.append(
                    {
                        "datetime": day,
                        "symbol": item["symbol"],
                        "factor": factor,
                        "forward_return": signal * 0.002,
                        "next_return": signal * 0.0004,
                        "dollar_volume": 10_000_000 + index * 1_000_000,
                    }
                )
        result = analyze_cross_sectional_panel(
            pd.DataFrame(rows),
            members,
            CrossSectionConfig(
                factor_key="trend_strength",
                min_assets=8,
                minimum_effective_dates=20,
                minimum_valid_assets=8,
                transaction_cost_bps=5,
            ),
        )

        self.assertEqual(result["factor"]["status"], "usable")
        self.assertGreater(result["summary"]["rank_ic_mean"], 0.9)
        self.assertLessEqual(result["summary"]["rank_ic_p_value"], 0.05)
        self.assertEqual(result["summary"]["portfolio_mode"], "cohort")
        self.assertGreater(result["summary"]["icir"], 0)
        self.assertEqual(len(result["quantile_returns"]), 5)
        self.assertGreater(result["summary"]["long_short_total_return"], 0)
        self.assertEqual(result["summary"]["primary_portfolio_key"], "long_only_excess")
        self.assertFalse(
            result["summary"]["portfolio_variants"]["theoretical_long_short"]["executable"]
        )
        self.assertFalse(result["summary"]["portfolio_variants"]["index_hedged"]["available"])
        self.assertEqual(result["summary"]["coverage"], 1.0)
        self.assertGreater(result["summary"]["median_capacity"], 0)
        self.assertGreater(result["summary"]["median_crowding_hhi"], 0)

    def test_point_in_time_membership_excludes_st_suspended_and_delisted_rows(self) -> None:
        members = [
            member("A", 0),
            member("B", 1),
            member("C", 2),
            member("D", 3, is_st=True),
            member("E", 4, status="suspended"),
            member("F", 5, delisted_at="2025-01-02"),
        ]
        rows = []
        for day in pd.date_range("2025-01-01", periods=4, freq="D"):
            for index, item in enumerate(members):
                rows.append(
                    {
                        "datetime": day,
                        "symbol": item["symbol"],
                        "factor": float(index),
                        "forward_return": float(index) / 100,
                        "next_return": float(index) / 400,
                        "dollar_volume": 1_000_000.0,
                    }
                )
        result = analyze_cross_sectional_panel(
            pd.DataFrame(rows),
            members,
            CrossSectionConfig(
                factor_key="momentum_20",
                min_assets=3,
                quantiles=3,
                neutralize_industry=False,
                neutralize_market_cap=False,
                neutralize_beta=False,
            ),
        )

        self.assertEqual(result["series"][0]["eligible_assets"], 4)
        self.assertEqual(result["series"][-1]["eligible_assets"], 3)
        self.assertNotIn("D", result["series"][0]["long_symbols"])
        self.assertNotIn("E", result["series"][0]["long_symbols"])

    def test_non_overlapping_portfolio_does_not_compound_overlapping_labels(self) -> None:
        members = [member(f"S{index}", index) for index in range(6)]
        rows = []
        for day in pd.date_range("2025-01-01", periods=10, freq="D"):
            for index, item in enumerate(members):
                rows.append(
                    {
                        "datetime": day,
                        "symbol": item["symbol"],
                        "factor": float(index),
                        "forward_return": float(index) * 0.01,
                        "dollar_volume": 1_000_000.0,
                    }
                )

        result = analyze_cross_sectional_panel(
            pd.DataFrame(rows),
            members,
            CrossSectionConfig(
                market="us_stocks",
                factor_key="momentum_20",
                horizon=5,
                quantiles=3,
                min_assets=6,
                transaction_cost_bps=0,
                portfolio_mode="non_overlapping",
                neutralize_industry=False,
                neutralize_market_cap=False,
                neutralize_beta=False,
            ),
        )

        spread = 0.04
        self.assertEqual(result["summary"]["portfolio_observations"], 2)
        self.assertEqual(result["summary"]["primary_portfolio_key"], "theoretical_long_short")
        self.assertTrue(
            result["summary"]["portfolio_variants"]["theoretical_long_short"]["executable"]
        )
        self.assertAlmostEqual(
            result["summary"]["long_short_total_return"],
            (1 + spread) ** 2 - 1,
            places=6,
        )
        self.assertNotAlmostEqual(
            result["summary"]["long_short_total_return"],
            (1 + spread) ** 10 - 1,
            places=4,
        )

    def test_horizon_one_non_overlapping_matches_single_cohort_portfolio(self) -> None:
        members = [member(f"S{index}", index) for index in range(6)]
        rows = []
        for day in pd.date_range("2025-01-01", periods=10, freq="D"):
            for index, item in enumerate(members):
                rows.append(
                    {
                        "datetime": day,
                        "symbol": item["symbol"],
                        "factor": float(index),
                        "forward_return": float(index) * 0.01,
                        "next_return": float(index) * 0.01,
                        "dollar_volume": 1_000_000.0,
                    }
                )
        frame = pd.DataFrame(rows)
        common = {
            "market": "us_stocks",
            "factor_key": "momentum_20",
            "horizon": 1,
            "quantiles": 3,
            "min_assets": 6,
            "transaction_cost_bps": 0,
            "neutralize_industry": False,
            "neutralize_market_cap": False,
            "neutralize_beta": False,
        }

        non_overlapping = analyze_cross_sectional_panel(
            frame,
            members,
            CrossSectionConfig(**common, portfolio_mode="non_overlapping"),
        )
        cohort = analyze_cross_sectional_panel(
            frame,
            members,
            CrossSectionConfig(**common, portfolio_mode="cohort"),
        )

        self.assertEqual(non_overlapping["summary"]["portfolio_observations"], 10)
        self.assertEqual(cohort["summary"]["portfolio_observations"], 10)
        self.assertAlmostEqual(
            non_overlapping["summary"]["long_short_total_return"],
            cohort["summary"]["long_short_total_return"],
            places=12,
        )

    def test_cohort_portfolio_compounds_only_next_period_returns(self) -> None:
        members = [member(f"S{index}", index) for index in range(6)]
        rows = []
        for day in pd.date_range("2025-01-01", periods=10, freq="D"):
            for index, item in enumerate(members):
                rows.append(
                    {
                        "datetime": day,
                        "symbol": item["symbol"],
                        "factor": float(index),
                        "forward_return": float(index) * 0.05,
                        "next_return": float(index) * 0.01,
                        "dollar_volume": 1_000_000.0,
                    }
                )

        result = analyze_cross_sectional_panel(
            pd.DataFrame(rows),
            members,
            CrossSectionConfig(
                factor_key="momentum_20",
                horizon=5,
                quantiles=3,
                min_assets=6,
                transaction_cost_bps=0,
                portfolio_mode="cohort",
                neutralize_industry=False,
                neutralize_market_cap=False,
                neutralize_beta=False,
            ),
        )

        one_period_spread = 0.04
        self.assertEqual(result["summary"]["portfolio_observations"], 10)
        self.assertAlmostEqual(
            result["summary"]["long_short_total_return"],
            (1 + one_period_spread) ** 10 - 1,
            places=6,
        )
        self.assertEqual(result["series"][4]["portfolio_active_cohorts"], 5)

    def test_non_overlapping_cost_is_charged_only_on_rebalance_dates(self) -> None:
        members = [member(f"S{index}", index) for index in range(6)]
        rows = []
        for offset, day in enumerate(pd.date_range("2025-01-01", periods=10, freq="D")):
            for index, item in enumerate(members):
                signal = index if offset < 5 else 5 - index
                rows.append(
                    {
                        "datetime": day,
                        "symbol": item["symbol"],
                        "factor": float(signal),
                        "forward_return": float(signal) * 0.01,
                        "dollar_volume": 1_000_000.0,
                    }
                )

        result = analyze_cross_sectional_panel(
            pd.DataFrame(rows),
            members,
            CrossSectionConfig(
                factor_key="momentum_20",
                horizon=5,
                quantiles=3,
                min_assets=6,
                transaction_cost_bps=100,
                portfolio_mode="non_overlapping",
                neutralize_industry=False,
                neutralize_market_cap=False,
                neutralize_beta=False,
            ),
        )

        charged_rows = [row for row in result["series"] if row["portfolio_net_return"] is not None]
        self.assertEqual([row["turnover"] for row in charged_rows], [1.0, 1.0])
        self.assertAlmostEqual(
            result["summary"]["long_short_total_return"],
            (1 + 0.04 - 0.01) ** 2 - 1,
            places=6,
        )


class CrossSectionPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db = store._DB
        self.temp_dir = Path(tempfile.mkdtemp(prefix="quanthub-cross-section-"))
        database.dispose_engines()
        store._DB = self.temp_dir / "store.db"
        store._init()

    def tearDown(self) -> None:
        database.dispose_engines()
        store._DB = self.original_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def save_cross_section_run(
        self,
        market: str,
        *,
        run_status: str = "succeeded",
        factor_status: str = "usable",
        dates: int = 120,
        minimum_valid_assets: int = 30,
    ) -> dict:
        run = store.create_research_run(
            symbol=f"UNIVERSE:{market}",
            market=market,
            timeframe="1d",
            modules=[service.CROSS_SECTION_MODULE],
            input_data={service.CROSS_SECTION_MODULE: {"factor_key": "trend_strength"}},
            instrument_id=f"universe:{market}",
        )
        return store.update_research_run(
            run["id"],
            {
                "status": run_status,
                "summary": {
                    service.CROSS_SECTION_MODULE: {
                        "factor_key": "trend_strength",
                        "factor_status": factor_status,
                        "dates": dates,
                        "effective_dates": dates,
                        "minimum_valid_assets": minimum_valid_assets,
                        "validation_thresholds": {
                            "minimum_effective_dates": 120,
                            "minimum_valid_assets": 30
                            if market in {"a_shares", "us_stocks"}
                            else 20,
                        },
                        "rank_ic_mean": 0.08,
                        "coverage": 0.95,
                    }
                },
            },
        )

    def test_target_market_status_does_not_require_every_market(self) -> None:
        self.save_cross_section_run("a_shares")

        result = service.cross_market_factor_status("trend_strength", "a_shares")

        self.assertTrue(result["trading_validation_passed"])
        self.assertEqual(result["trading_validation_status"], "passed")
        self.assertEqual(result["required_markets"], ["a_shares"])
        self.assertEqual(
            [row["state"] for row in result["rows"]],
            ["passed", "missing", "missing", "missing"],
        )

    def test_cross_market_status_rejects_non_usable_market(self) -> None:
        for market in ("a_shares", "us_stocks", "mt5"):
            self.save_cross_section_run(market)
        self.save_cross_section_run("crypto", factor_status="watch")

        result = service.cross_market_factor_status("trend_strength", "crypto")
        crypto = next(row for row in result["rows"] if row["market"] == "crypto")

        self.assertFalse(result["trading_validation_passed"])
        self.assertEqual(crypto["state"], "failed")
        self.assertEqual(crypto["factor_status"], "watch")

    def test_target_market_status_passes_without_portability_evidence(self) -> None:
        for market in ("a_shares", "us_stocks", "crypto", "mt5"):
            self.save_cross_section_run(market)

        result = service.cross_market_factor_status("trend_strength", "us_stocks")

        self.assertTrue(result["trading_validation_passed"])
        self.assertEqual(result["trading_validation_status"], "passed")
        self.assertTrue(all(row["state"] == "passed" for row in result["rows"]))

    def test_cross_market_status_uses_latest_factor_run_per_market(self) -> None:
        for market in ("a_shares", "us_stocks", "crypto", "mt5"):
            self.save_cross_section_run(market)
        latest = self.save_cross_section_run("us_stocks", run_status="failed")

        result = service.cross_market_factor_status("trend_strength", "us_stocks")
        us_stocks = next(row for row in result["rows"] if row["market"] == "us_stocks")

        self.assertFalse(result["trading_validation_passed"])
        self.assertEqual(us_stocks["run_id"], latest["id"])
        self.assertEqual(us_stocks["run_status"], "failed")
        self.assertEqual(us_stocks["state"], "failed")

    def test_cross_market_status_requires_explicit_target_market(self) -> None:
        self.save_cross_section_run("a_shares")

        result = service.cross_market_factor_status("trend_strength")

        self.assertFalse(result["trading_validation_passed"])
        self.assertEqual(result["trading_validation_status"], "target_market_required")
        self.assertEqual(result["required_markets"], [])

    def test_universe_members_preserve_effective_dates_and_metadata(self) -> None:
        universe = service.create_factor_universe(
            FactorUniverseCreate(name="美股历史池", market="us_stocks")
        )["universe"]
        instrument = Instrument(code="AAPL", market="us_stocks")
        with patch.object(service.instrument_service, "resolve_strict", return_value=instrument):
            response = service.upsert_factor_universe_member(
                universe["id"],
                FactorUniverseMemberUpsert(
                    symbol="aapl",
                    effective_from=date(2024, 1, 1),
                    effective_to=date(2025, 6, 30),
                    industry="科技",
                    market_cap=3_000_000_000_000,
                    beta=1.2,
                    listed_at=date(1980, 12, 12),
                ),
            )

        saved = response["member"]
        self.assertEqual(saved["symbol"], "AAPL")
        self.assertEqual(saved["effective_from"], "2024-01-01")
        self.assertEqual(saved["effective_to"], "2025-06-30")
        self.assertEqual(saved["industry"], "科技")
        self.assertEqual(saved["market_cap"], 3_000_000_000_000)
        self.assertEqual(saved["beta"], 1.2)
        self.assertEqual(
            service.list_factor_universe_members(universe["id"], as_of=date(2025, 1, 1))["count"],
            1,
        )
        self.assertEqual(
            service.list_factor_universe_members(universe["id"], as_of=date(2025, 7, 1))["count"],
            0,
        )
        with patch.object(service.instrument_service, "resolve_strict", return_value=instrument):
            overlap = service.upsert_factor_universe_member(
                universe["id"],
                FactorUniverseMemberUpsert(
                    symbol="AAPL",
                    effective_from=date(2025, 1, 1),
                    effective_to=date(2025, 12, 31),
                ),
            )
        self.assertFalse(overlap["ok"])
        self.assertEqual(overlap["error"], "成分生效区间与已有记录重叠")

    def test_batch_retries_failures_and_point_in_time_evidence_are_saved(self) -> None:
        universe = store.create_factor_universe("批量验证池", "us_stocks", "")
        for index in range(6):
            store.upsert_factor_universe_member(
                universe_id=universe["id"],
                instrument_id=f"us_stocks:S{index}",
                symbol=f"S{index}",
                effective_from="2024-01-01",
                effective_to=None,
                status="active",
                industry="科技",
                market_cap=1_000_000_000 + index,
                beta=1.0,
                is_st=False,
                listed_at="2020-01-01",
                delisted_at=None,
            )
        close = np.linspace(100, 130, 150)
        frame = pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=150, freq="D"),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": np.full(150, 100_000),
            }
        )
        frame.attrs["_source"] = "batch_test_feed"
        source = Mock()

        def get_kline(symbol, interval, *, start, end, limit):
            if symbol == "S5":
                raise RuntimeError("行情不可用")
            return frame.copy()

        source.get_kline.side_effect = get_kline
        engine_result = {
            "engine_version": "1.0.0",
            "factor": {"key": "trend_strength", "status": "watch"},
            "summary": {"rank_ic_mean": 0.05, "data_fingerprint": "x" * 64},
            "quantile_returns": [],
            "series": [],
            "methodology": {},
        }
        with (
            patch.object(service, "get_data_source", return_value=source),
            patch.object(
                service,
                "analyze_cross_sectional_factors",
                return_value=engine_result,
            ),
        ):
            response = service.run_cross_sectional_research(
                CrossSectionResearchRequest(
                    universe_id=universe["id"],
                    retry_attempts=2,
                )
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["loaded_symbols"], 5)
        self.assertEqual(response["failed_symbols"], 1)
        self.assertEqual(response["failures"][0]["attempts"], 2)
        run = store.get_research_run(response["run_id"])
        self.assertEqual(run["status"], "partial")
        kinds = [item["kind"] for item in run["evidence"]]
        self.assertEqual(kinds.count("market_snapshot"), 5)
        self.assertIn("universe_snapshot", kinds)
        self.assertIn("cross_sectional_factor_result", kinds)
        universe_snapshot = next(
            item for item in run["evidence"] if item["kind"] == "universe_snapshot"
        )
        self.assertEqual(
            universe_snapshot["payload"]["members"],
            store.list_factor_universe_members(universe["id"]),
        )
        detail = service.get_cross_sectional_research_run(response["run_id"])
        self.assertEqual(detail["result"]["run_id"], response["run_id"])
        self.assertEqual(
            detail["universe_snapshot"]["sha256"], universe_snapshot["payload"]["sha256"]
        )
        self.assertEqual(len(detail["market_snapshots"]), 5)
        source.reset_mock()
        source.get_kline.side_effect = lambda symbol, interval, *, start, end, limit: frame.copy()
        with (
            patch.object(service, "get_data_source", return_value=source),
            patch.object(
                service,
                "analyze_cross_sectional_factors",
                return_value=engine_result,
            ),
        ):
            resumed = service.run_cross_sectional_research(
                CrossSectionResearchRequest(
                    run_id=response["run_id"],
                    universe_id=universe["id"],
                    retry_attempts=2,
                )
            )
        self.assertTrue(resumed["ok"])
        self.assertEqual(resumed["run_id"], response["run_id"])
        self.assertEqual(resumed["failed_symbols"], 0)
        self.assertEqual(source.get_kline.call_count, 1)
        self.assertEqual(source.get_kline.call_args.args[0], "S5")


if __name__ == "__main__":
    unittest.main()

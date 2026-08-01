import unittest

import pandas as pd

from core.point_in_time_universe import (
    TARGET_MARKET_UNIVERSE_PROFILES,
    a_share_tradability_reasons,
    assess_universe_frame_quality,
    build_snapshot_fingerprints,
    restore_members_on_session,
    validate_point_in_time_fields,
)


class PointInTimeUniverseTests(unittest.TestCase):
    def test_field_contract_blocks_future_information(self) -> None:
        report = validate_point_in_time_fields(
            [
                {
                    "field": "market_cap",
                    "event_time": 100,
                    "available_time": 99,
                    "source": "vendor",
                    "captured_at": 110,
                    "adjustment": "none",
                    "revision": "v1",
                }
            ]
        )
        self.assertFalse(report["passed"])
        self.assertTrue(report["future_information_blocked"])

    def test_quality_and_tradability_cover_a_share_constraints(self) -> None:
        frame = pd.DataFrame(
            {
                "time": [1, 2, 3],
                "open": [10.0, 10.0, 11.0],
                "high": [10.2, 11.0, 11.1],
                "low": [9.8, 10.0, 10.8],
                "close": [10.0, 11.0, 11.0],
                "tick_volume": [100, 100, 0],
            }
        )
        quality = assess_universe_frame_quality(frame)
        reasons = a_share_tradability_reasons(frame)
        self.assertTrue(quality["passed"])
        self.assertIn("price_limit", reasons.iloc[1])
        self.assertIn("suspended_or_no_volume", reasons.iloc[2])
        self.assertEqual(TARGET_MARKET_UNIVERSE_PROFILES["a_shares"]["lot_size"], 100)
        self.assertEqual(TARGET_MARKET_UNIVERSE_PROFILES["a_shares"]["settlement"], "T+1")
        self.assertEqual(
            len({profile["membership"] for profile in TARGET_MARKET_UNIVERSE_PROFILES.values()}),
            4,
        )

    def test_membership_is_restorable_and_snapshots_are_separate(self) -> None:
        members = [
            {
                "symbol": "A",
                "effective_from_session": 10,
                "effective_to_session": 20,
                "status": "active",
            },
            {
                "symbol": "B",
                "effective_from_session": 15,
                "effective_to_session": None,
                "status": "active",
            },
        ]
        self.assertEqual(
            [item["symbol"] for item in restore_members_on_session(members, 12)], ["A"]
        )
        hashes = build_snapshot_fingerprints(
            universe_members=members,
            market_files=[{"symbol": "A", "sha256": "a" * 64}],
            exposures=[{"symbol": "A", "available_time": 10}],
        )
        self.assertEqual(len(set(hashes.values())), 4)
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))


if __name__ == "__main__":
    unittest.main()

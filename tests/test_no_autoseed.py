"""M3-02: empty installations never receive production demo holdings or watchlist rows."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient


def _simulate_fresh_install() -> None:
    from apps.api import store

    with store._lock, store._conn() as conn:
        conn.execute("DELETE FROM holdings")
        conn.execute("DELETE FROM watchlist")


class NoAutoSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        from apps.api.domains.portfolio import repository
        from apps.api.domains.portfolio import service as portfolio_service

        self.repository = repository
        self.service = portfolio_service
        _simulate_fresh_install()

    def test_portfolio_snapshot_does_not_autoseed(self) -> None:
        result = self.service.portfolio_snapshot()

        self.assertIs(result["ok"], True)
        self.assertEqual(result["holdings"], [])
        self.assertEqual(result["summary"]["cash"], 0.0)
        self.assertEqual(self.repository.list_holdings(), [])

    def test_watchlist_snapshot_does_not_autoseed(self) -> None:
        result = self.service.watchlist_snapshot()

        self.assertIs(result["ok"], True)
        self.assertEqual(result["items"], [])
        self.assertEqual(self.repository.list_watchlist(), [])

    def test_http_first_open_keeps_database_empty(self) -> None:
        from apps.api.main import app

        with TestClient(app) as client:
            portfolio = client.get("/portfolio")
            watchlist = client.get("/market/watchlist")

        self.assertEqual(portfolio.status_code, 200)
        self.assertEqual(watchlist.status_code, 200)
        self.assertEqual(portfolio.json().get("holdings"), [])
        self.assertEqual(portfolio.json().get("summary", {}).get("cash"), 0.0)
        self.assertEqual(watchlist.json().get("items"), [])
        self.assertEqual(self.repository.list_holdings(), [])
        self.assertEqual(self.repository.list_watchlist(), [])

    def test_demo_reset_endpoints_are_not_exposed(self) -> None:
        from apps.api.main import app

        paths = app.openapi()["paths"]
        self.assertNotIn("/portfolio/holdings/reset", paths)
        self.assertNotIn("/market/watchlist/reset", paths)

    def test_seed_and_reset_implementation_chain_is_removed(self) -> None:
        from apps.api import store

        for module in (store, self.repository):
            for name in (
                "seed_holdings_if_empty",
                "reset_holdings",
                "seed_watchlist_if_empty",
                "reset_watchlist",
                "seed_holdings",
                "seed_watchlist",
            ):
                self.assertFalse(
                    hasattr(module, name), f"obsolete production helper remains: {name}"
                )
        self.assertNotIn("holdings", self.service.CONFIG)
        self.assertNotIn("watchlist", self.service.CONFIG)
        self.assertNotIn("cash", self.service.CONFIG)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

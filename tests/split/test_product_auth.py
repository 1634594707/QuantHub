from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.product_auth import install_bearer_auth


class ProductAuthTests(unittest.TestCase):
    def test_api_is_protected_but_health_and_frontend_are_public(self) -> None:
        app = FastAPI()
        install_bearer_auth(app, "product-specific-secret")

        @app.get("/health")
        def health():
            return {"status": "ok"}

        @app.get("/api/records")
        def records():
            return []

        client = TestClient(app)
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.get("/api/records").status_code, 401)
        self.assertEqual(
            client.get(
                "/api/records", headers={"Authorization": "Bearer product-specific-secret"}
            ).status_code,
            200,
        )


if __name__ == "__main__":
    unittest.main()

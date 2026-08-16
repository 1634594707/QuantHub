from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from apps.api.domains.settings import service
from apps.api.domains.settings.schemas import OkxDemoCredentialsUpdate
from packages.credential_vault import (
    OkxCredentials,
    delete_okx_demo_credentials,
    inspect_okx_demo_credentials,
    load_okx_demo_credentials,
    okx_demo_credential_status,
    save_okx_demo_credentials,
)


class OkxCredentialVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temporary.name) / "okx-demo.bin"
        self.previous = os.environ.get("QH_OKX_VAULT_PATH")
        os.environ["QH_OKX_VAULT_PATH"] = str(self.vault_path)

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop("QH_OKX_VAULT_PATH", None)
        else:
            os.environ["QH_OKX_VAULT_PATH"] = self.previous
        self.temporary.cleanup()

    def test_dpapi_round_trip_never_writes_plaintext(self) -> None:
        marker = "SYNTHETIC-OKX-SECRET-DO-NOT-LEAK"
        credentials = OkxCredentials("synthetic-api-key", marker, "synthetic-passphrase")
        if sys.platform != "win32":
            with self.assertRaisesRegex(RuntimeError, "requires Windows DPAPI"):
                save_okx_demo_credentials(credentials)
            self.assertFalse(self.vault_path.exists())
            return

        status = save_okx_demo_credentials(credentials)

        self.assertTrue(status["configured"])
        self.assertNotIn(marker.encode(), self.vault_path.read_bytes())
        self.assertEqual(load_okx_demo_credentials().secret_key, marker)
        rendered_status = repr(okx_demo_credential_status())
        self.assertNotIn("synthetic-api-key", rendered_status)
        self.assertNotIn(marker, rendered_status)
        self.assertNotIn("synthetic-passphrase", rendered_status)

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is required")
    def test_delete_removes_the_encrypted_file(self) -> None:
        save_okx_demo_credentials(OkxCredentials("key", "secret", "passphrase"))
        result = delete_okx_demo_credentials()
        self.assertFalse(result["configured"])
        self.assertFalse(self.vault_path.exists())

    def test_request_model_repr_masks_every_secret(self) -> None:
        request = OkxDemoCredentialsUpdate(
            api_key="api-marker", secret_key="secret-marker", passphrase="pass-marker"
        )
        rendered = repr(request)
        self.assertNotIn("api-marker", rendered)
        self.assertNotIn("secret-marker", rendered)
        self.assertNotIn("pass-marker", rendered)

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is required")
    def test_corrupt_vault_reports_recovery_and_can_be_rebuilt(self) -> None:
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_bytes(b"not-a-dpapi-payload")

        unavailable = inspect_okx_demo_credentials()

        self.assertFalse(unavailable["ok"])
        self.assertFalse(unavailable["available"])
        self.assertTrue(unavailable["configured"])
        self.assertEqual(unavailable["error_code"], "credential_vault_unavailable")
        rebuilt = save_okx_demo_credentials(OkxCredentials("new-key", "new-secret", "new-pass"))
        self.assertTrue(rebuilt["available"])
        self.assertEqual(load_okx_demo_credentials().api_key, "new-key")


class OkxConnectionTestTests(unittest.TestCase):
    STATUS: ClassVar[dict[str, object]] = {
        "ok": True,
        "configured": True,
        "environment": "demo",
        "source": "local_vault",
        "fingerprint": "0123456789ab",
        "updated_at": "2026-08-10T00:00:00+00:00",
        "validated_at": None,
    }

    def test_success_is_demo_and_read_only(self) -> None:
        calls: list[str] = []

        class Exchange:
            class Session:
                trust_env = False

            session = Session()

            def set_sandbox_mode(self, enabled: bool) -> None:
                calls.append(f"sandbox:{enabled}")

            def fetch_balance(self) -> dict:
                calls.append("fetch_balance")
                return {"total": {"USDT": 10, "BTC": 0}}

        fake_ccxt = types.SimpleNamespace(okx=lambda config: Exchange())
        with (
            patch.object(service, "okx_demo_credential_status", return_value=self.STATUS),
            patch.object(
                service,
                "load_okx_demo_credentials",
                return_value=OkxCredentials("api", "secret", "passphrase"),
            ),
            patch.object(service, "update_okx_demo_validation"),
            patch.dict(sys.modules, {"ccxt": fake_ccxt}),
        ):
            result = service.test_okx_demo_connection()

        self.assertTrue(result["ok"])
        self.assertTrue(fake_ccxt.okx({}).session.trust_env)
        self.assertEqual(calls, ["sandbox:True", "fetch_balance"])
        self.assertEqual(result["permission"], "read_only_test")
        self.assertEqual(result["currency_count"], 2)
        self.assertEqual(result["nonzero_currency_count"], 1)

    def test_failure_is_sanitized(self) -> None:
        secret_marker = "SYNTHETIC-RAW-SECRET"

        class AuthenticationError(Exception):
            pass

        class Exchange:
            class Session:
                trust_env = False

            session = Session()

            def set_sandbox_mode(self, enabled: bool) -> None:
                pass

            def fetch_balance(self) -> dict:
                raise AuthenticationError(f"request header exposed {secret_marker}")

        fake_ccxt = types.SimpleNamespace(okx=lambda config: Exchange())
        with (
            patch.object(service, "okx_demo_credential_status", return_value=self.STATUS),
            patch.object(
                service,
                "load_okx_demo_credentials",
                return_value=OkxCredentials("api", secret_marker, "passphrase"),
            ),
            patch.dict(sys.modules, {"ccxt": fake_ccxt}),
        ):
            result = service.test_okx_demo_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "authentication_failed")
        self.assertNotIn(secret_marker, repr(result))

    def test_vault_failure_has_a_specific_sanitized_action(self) -> None:
        with (
            patch.object(service, "okx_demo_credential_status", return_value=self.STATUS),
            patch.object(
                service,
                "load_okx_demo_credentials",
                side_effect=RuntimeError("raw local failure"),
            ),
        ):
            result = service.test_okx_demo_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "credential_vault_unavailable")
        self.assertNotIn("raw local failure", repr(result))

    def test_okx_environment_mismatch_has_a_specific_action(self) -> None:
        error = type("AuthenticationError", (Exception,), {})('OKX {"code":"50101"}')
        code, message = service._okx_error(error, "account_read")
        self.assertEqual(code, "environment_mismatch")
        self.assertIn("Demo", message)

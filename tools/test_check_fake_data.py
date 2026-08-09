"""Regression test for check_fake_data exemption granularity (work package M3-01).

Verifies that the scanner routes every hit through ``_exemption_for`` so a
per-match allowance (``quantity: 100``) is honored **only in the allowlisted file**
while a non-listed hardcoded value (``price: 999``) in the same file is still
flagged. This guards against the prior bug where the whole file was exempted,
hiding future hardcoded prices.

Run standalone:
    python tools/test_check_fake_data.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import check_fake_data as cfd  # noqa: E402


class TestExemptionFor(unittest.TestCase):
    def test_string_exemption_returns_reason(self):
        self.assertIsInstance(cfd._exemption_for("whole file ok", "anything"), str)

    def test_dict_match_returns_reason(self):
        ex = {"reason": "r", "matches": ["quantity: 100"]}
        self.assertEqual(cfd._exemption_for(ex, "quantity: 100"), "r")

    def test_dict_mismatch_returns_none(self):
        ex = {"reason": "r", "matches": ["quantity: 100"]}
        self.assertIsNone(cfd._exemption_for(ex, "price: 999"))


# allowlisted file: quantity:100 exempted per-match, price:999 must still fail.
ALLOWLISTED_FIXTURE = """\
// regression fixture for check_fake_data exemption logic
const defaults = { quantity: 100 };
const leaked = { price: 999 };
"""

# NOT in the allowlist: a hardcoded quantity here must be flagged (proves the
# exemption is file-scoped, not global).
UNLISTED_FIXTURE = """\
// regression fixture (unlisted file)
const q = { quantity: 100 };
"""


class TestScanExemptionGranularity(unittest.TestCase):
    def setUp(self):
        # Point the scanner at an isolated temp tree so the real repo is never touched,
        # but keep relative paths identical to the real allowlist keys.
        self.orig_root = cfd.ROOT
        self.tmp = tempfile.TemporaryDirectory()
        cfd.ROOT = Path(self.tmp.name)
        page_dir = cfd.ROOT / "web" / "src" / "pages"
        page_dir.mkdir(parents=True)
        self.allowlisted = page_dir / "LedgerPage.tsx"
        self.allowlisted.write_text(ALLOWLISTED_FIXTURE, encoding="utf-8")
        self.unlisted = page_dir / "OtherPage.tsx"
        self.unlisted.write_text(UNLISTED_FIXTURE, encoding="utf-8")

    def tearDown(self):
        cfd.ROOT = self.orig_root
        self.tmp.cleanup()

    def _by_path(self, report):
        rel = self.allowlisted.relative_to(cfd.ROOT).as_posix()
        allowed = [a for a in report["allowlisted"] if a["path"] == rel]
        findings = [f for f in report["findings"] if f["path"] == rel]
        other_rel = self.unlisted.relative_to(cfd.ROOT).as_posix()
        other_findings = [f for f in report["findings"] if f["path"] == other_rel]
        return allowed, findings, other_findings

    def test_allowlisted_file_quantity_exempt_price_flagged(self):
        allowed, findings, _ = self._by_path(cfd.scan())
        self.assertTrue(
            any(a["match"] == "quantity: 100" for a in allowed),
            "quantity: 100 should be exempted via per-match allowlist in LedgerPage.tsx",
        )
        self.assertTrue(
            any(f["match"] == "price: 999" for f in findings),
            "price: 999 must be flagged even in an otherwise allowlisted file",
        )

    def test_exemption_is_file_scoped_not_global(self):
        _, _, other_findings = self._by_path(cfd.scan())
        self.assertTrue(
            any(f["match"] == "quantity: 100" for f in other_findings),
            "quantity: 100 in a non-allowlisted file must still be flagged",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

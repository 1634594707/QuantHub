"""Scan one product source boundary for high-confidence committed secrets."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PRODUCT_PATHS = {
    "okx-runner": (Path("apps/okx_runner"), Path("packages")),
}
PATTERNS = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
}
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".py", ".sql", ".toml", ".txt"}


def scan(product: str) -> dict:
    findings = []
    scanned = 0
    for root in PRODUCT_PATHS[product]:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name, pattern in PATTERNS.items():
                if pattern.search(text):
                    findings.append({"kind": name, "path": path.as_posix()})
    return {
        "product": product,
        "passed": not findings,
        "files_scanned": scanned,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True, choices=sorted(PRODUCT_PATHS))
    args = parser.parse_args()
    report = scan(args.product)
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

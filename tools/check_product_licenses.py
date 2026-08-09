"""Fail a product build when an installed distribution has no license metadata."""

from __future__ import annotations

import argparse
import json
from importlib import metadata


def license_label(distribution: metadata.Distribution) -> str | None:
    declared = distribution.metadata.get("License-Expression")
    if declared:
        return declared.strip()

    classifiers = distribution.metadata.get_all("Classifier") or []
    osi = [item.rsplit(" :: ", 1)[-1] for item in classifiers if "License :: OSI Approved" in item]
    if osi:
        return " OR ".join(sorted(set(osi)))

    legacy = (distribution.metadata.get("License") or "").strip()
    if legacy and legacy.upper() not in {"UNKNOWN", "NONE"}:
        return legacy.splitlines()[0][:160]
    return None


def scan(product: str) -> dict:
    packages = []
    missing = []
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name") or "unknown"
        label = license_label(distribution)
        packages.append({"name": name, "version": distribution.version, "license": label})
        if label is None:
            missing.append(name)
    packages.sort(key=lambda item: item["name"].lower())
    return {
        "product": product,
        "passed": not missing,
        "package_count": len(packages),
        "missing_license_metadata": sorted(missing),
        "packages": packages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True)
    args = parser.parse_args()
    report = scan(args.product)
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

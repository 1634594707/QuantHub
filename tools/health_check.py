"""P0-04 健康检查门禁（轻量，无需启动服务器）。

通过 ``fastapi.testclient.TestClient`` 直接命中 ``/health``，
复用 ``tests`` 包的数据库隔离，避免污染仓库主库。

用法::

    uv run --frozen python tools/health_check.py
    uv run --frozen python tools/health_check.py --json docs/Plan/evidence/P0-04-health.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 关键：先导入 tests 包完成隔离，再导入 apps.*。
from fastapi.testclient import TestClient  # noqa: E402

import tests as tests_package  # noqa: E402
from apps.api.main import app  # noqa: E402

PRODUCTION_STORE = tests_package.PRODUCTION_STORE_PATH


def sha256_of(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantHub 健康检查门禁")
    parser.add_argument("--json", dest="json_path", type=Path, help="写入 JSON 证据到指定路径")
    args = parser.parse_args()

    digest_before = sha256_of(PRODUCTION_STORE)
    client = TestClient(app)
    started = time.perf_counter()
    response = client.get("/health")
    elapsed = time.perf_counter() - started
    digest_after = sha256_of(PRODUCTION_STORE)

    status = response.status_code
    body = None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = response.text[:200]

    ok = status == 200 and digest_before == digest_after
    print(f"/health 状态码 : {status}")
    print(
        f"响应体前 200 字符: {json.dumps(body, ensure_ascii=False)[:200] if not isinstance(body, str) else body}"
    )
    print(f"耗时          : {elapsed * 1000:.1f} ms")
    print(f"主库校验和前  : {digest_before}")
    print(f"主库校验和后  : {digest_after}")
    print(
        "主库状态      : " + ("未改动（隔离生效）" if digest_before == digest_after else "已被改动")
    )

    report = {
        "task": "P0-04-health",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "endpoint": "/health",
        "status_code": status,
        "body": body,
        "duration_ms": round(elapsed * 1000, 1),
        "isolated_store_path": str(tests_package.STORE_PATH),
        "production_store_path": str(PRODUCTION_STORE),
        "production_sha256_before": digest_before,
        "production_sha256_after": digest_after,
        "production_untouched": digest_before == digest_after,
        "passed": ok,
    }
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"证据已写入: {args.json_path}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

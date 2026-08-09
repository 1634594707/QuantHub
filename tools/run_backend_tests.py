"""后端测试门禁入口（工作包 P0-04 / Q0-02）。

相对裸 ``python -m unittest discover`` 的三点强化：

1. **隔离**：导入 ``tests`` 包即把 ``QUANTHUB_STORE_PATH`` 重定向到一次性目录，
   业务用例不再写入仓库主库 ``apps/api/store.db``。
2. **自证**：运行前后各算一次主库 SHA-256，只要发生变化就判定门禁失败——
   门禁自己证明自己没有副作用，而不是靠人相信。
3. **全量**：显式发现 ``tests/`` 与 ``tests/split/``。后者此前因缺 ``__init__.py``
   而被 Python 3.11+ 的发现机制静默跳过。

用法::

    uv run --frozen python tools/run_backend_tests.py
    uv run --frozen python tools/run_backend_tests.py --json docs/Plan/evidence/Q0-02-backend-gate.json
    uv run --frozen python tools/run_backend_tests.py -k trading   # 只跑匹配的用例

退出码：0 = 全部通过且主库未被改动；1 = 用例失败；2 = 主库被改动（隔离失效）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 关键：先导入 tests 包完成隔离，再导入任何 apps.* 模块。
import tests as tests_package  # noqa: E402

PRODUCTION_STORE = tests_package.PRODUCTION_STORE_PATH

#: 只发现一次根包，子包由 unittest 递归进入（避免重复计数）。
DISCOVERY_ROOT = "tests"

#: 必须出现在发现结果里的子包前缀。``tests/split`` 曾因缺 ``__init__.py``
#: 被 Python 3.11+ 静默跳过，这里把「它必须在门禁里」变成断言而不是口头约定。
REQUIRED_MODULE_PREFIXES = ("tests.split.",)


def sha256_of(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_test_ids(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_test_ids(item)
        else:
            yield item.id()


def build_suite(keyword: str | None) -> tuple[unittest.TestSuite, list[str], list[str]]:
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(REPO_ROOT / DISCOVERY_ROOT),
        pattern="test_*.py",
        top_level_dir=str(REPO_ROOT),
    )
    if keyword:
        suite = filter_suite(suite, keyword)
    return suite, list(loader.errors), list(iter_test_ids(suite))


def filter_suite(suite: unittest.TestSuite, keyword: str) -> unittest.TestSuite:
    filtered = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            child = filter_suite(item, keyword)
            if child.countTestCases():
                filtered.addTest(child)
        elif keyword in item.id():
            filtered.addTest(item)
    return filtered


def count_tests(suite: unittest.TestSuite) -> int:
    total = 0
    for item in suite:
        total += count_tests(item) if isinstance(item, unittest.TestSuite) else 1
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantHub 后端测试门禁")
    parser.add_argument("-k", dest="keyword", help="只运行 id 中包含该关键字的用例")
    parser.add_argument("-v", "--verbose", action="store_true", help="逐条打印用例")
    parser.add_argument("--json", dest="json_path", type=Path, help="写入 JSON 证据到指定路径")
    args = parser.parse_args()

    digest_before = sha256_of(PRODUCTION_STORE)
    print(f"隔离库    : {tests_package.STORE_PATH}")
    print(f"仓库主库  : {PRODUCTION_STORE}")
    print(f"运行前校验和: {digest_before}")

    if tests_package.DROPPED_ENV_VARS:
        print(
            f"已丢弃超长环境变量: {', '.join(tests_package.DROPPED_ENV_VARS)}（>32767 字符，无法回写）"
        )

    suite, load_errors, test_ids = build_suite(args.keyword)
    if load_errors:
        print(f"发现 {len(load_errors)} 个模块导入失败：")
        for message in load_errors:
            print(message)
        return 1

    planned = len(test_ids)
    if not args.keyword:
        for prefix in REQUIRED_MODULE_PREFIXES:
            if not any(test_id.startswith(prefix) for test_id in test_ids):
                print(
                    f"门禁失败：子包 {prefix.rstrip('.')} 未被发现。"
                    f"检查是否缺少 {prefix.rstrip('.').replace('.', '/')}/__init__.py。"
                )
                return 1

    split_count = sum(1 for test_id in test_ids if test_id.startswith("tests.split."))
    print(f"计划运行  : {planned} 个用例（其中 tests.split 子包 {split_count} 个）\n")
    started = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    result = runner.run(suite)
    elapsed = time.perf_counter() - started

    digest_after = sha256_of(PRODUCTION_STORE)
    untouched = digest_before == digest_after
    print(f"\n运行后校验和: {digest_after}")
    print("主库状态  : " + ("未改动（隔离生效）" if untouched else "已被改动（隔离失效）"))

    report = {
        "task": "Q0-02",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "discovery_root": DISCOVERY_ROOT,
        "split_subpackage_tests": split_count,
        "dropped_oversized_env_vars": list(tests_package.DROPPED_ENV_VARS),
        "isolated_store_path": str(tests_package.STORE_PATH),
        "production_store_path": str(PRODUCTION_STORE),
        "production_sha256_before": digest_before,
        "production_sha256_after": digest_after,
        "production_untouched": untouched,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "duration_seconds": round(elapsed, 3),
        "passed": result.wasSuccessful() and untouched,
    }
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"证据已写入: {args.json_path}")

    if not result.wasSuccessful():
        return 1
    if not untouched:
        print("门禁失败：测试改动了仓库主库，隔离未生效。")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

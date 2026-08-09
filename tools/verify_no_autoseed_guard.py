"""M3-02 守卫自证：证明空库读取守卫能捕获生产自动写入。

「加了个测试，它通过了」什么也证明不了——测试可能因为断言写错、条件没构造到位
而恒真。本工具做**反向验证**：

1. 记录 ``apps/api/domains/portfolio/service.py`` 的 SHA-256；
2. 临时向两个快照函数注入演示写入，跑守卫用例，**期望三个读取用例失败**；
3. 从备份精确还原源文件，比对 SHA-256 必须与步骤 1 一致（证明没有把仓库改脏）；
4. 再跑一次守卫用例，**期望通过**；
5. 把两次结果写进证据 JSON，可单文件复核。

任何一步不符合预期即退出码非 0，且源文件一定会被还原（``finally``）。

用法::

    uv run --frozen python tools/verify_no_autoseed_guard.py
    uv run --frozen python tools/verify_no_autoseed_guard.py --json docs/Plan/evidence/M3-02-autoseed-guard.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE = REPO_ROOT / "apps/api/domains/portfolio/service.py"
GATE = REPO_ROOT / "tools/run_backend_tests.py"

#: 临时注入的生产写入：(锚点函数签名, 要注入的那一行)
REVERT_PATCHES = (
    (
        "def portfolio_snapshot() -> dict:",
        '    repository.add_holding("M3-GUARD", "guard", 1, 1, "a_shares")',
    ),
    (
        "def watchlist_snapshot() -> dict:",
        '    repository.add_watchlist("M3-GUARD", "guard", "a_shares")',
    ),
)

EXPECTED_FAILURES = {
    "test_portfolio_snapshot_does_not_autoseed",
    "test_watchlist_snapshot_does_not_autoseed",
    "test_http_first_open_keeps_database_empty",
}

RAN_RE = re.compile(r"^Ran (\d+) tests?", re.MULTILINE)
FAIL_RE = re.compile(r"^(FAIL|ERROR): (\S+)", re.MULTILINE)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_revert(text: str) -> str:
    """在每个快照函数首行临时注入生产写入。"""
    lines = text.splitlines(keepends=True)
    for anchor, injected in REVERT_PATCHES:
        for index, line in enumerate(lines):
            if line.rstrip("\r\n") == anchor:
                lines.insert(index + 1, injected + "\n")
                break
        else:
            raise SystemExit(f"锚点未找到，源文件结构已变：{anchor!r}")
    return "".join(lines)


def run_guard() -> dict:
    proc = subprocess.run(
        [sys.executable, str(GATE), "-k", "no_autoseed"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    blob = (proc.stdout or "") + (proc.stderr or "")
    ran = RAN_RE.search(blob)
    return {
        "exit_code": proc.returncode,
        "tests_run": int(ran.group(1)) if ran else 0,
        "passed": bool(re.search(r"^OK\b", blob, re.MULTILINE)),
        "failed_tests": sorted({name for _, name in FAIL_RE.findall(blob)}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()

    original_bytes = SERVICE.read_bytes()
    sha_before = sha256_of(SERVICE)

    try:
        SERVICE.write_text(
            apply_revert(original_bytes.decode("utf-8")), encoding="utf-8", newline=""
        )
        with_bug = run_guard()
    finally:
        SERVICE.write_bytes(original_bytes)

    sha_restored = sha256_of(SERVICE)
    with_fix = run_guard()

    evidence = {
        "task": "M3-02",
        "purpose": "反向验证空库读取守卫（注入生产演示写入必失败，修复后必通过）",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "subject_file": str(SERVICE.relative_to(REPO_ROOT)).replace("\\", "/"),
        "subject_sha256_before": sha_before,
        "subject_sha256_after_restore": sha_restored,
        "source_restored_byte_identical": sha_before == sha_restored,
        "injected_lines": [line.strip() for _, line in REVERT_PATCHES],
        "run_with_bug_reintroduced": with_bug,
        "run_with_fix_in_place": with_fix,
    }
    evidence["guard_is_effective"] = bool(
        evidence["source_restored_byte_identical"]
        and not with_bug["passed"]
        and with_bug["tests_run"] > 0
        and set(with_bug["failed_tests"]) == EXPECTED_FAILURES
        and with_fix["passed"]
        and with_fix["tests_run"] == with_bug["tests_run"]
    )

    if args.json_path:
        out = Path(args.json_path)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"证据已写入: {out}")

    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["guard_is_effective"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

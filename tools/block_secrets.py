"""跨平台拦截暂存区中的敏感文件与密钥材料。"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys

SENSITIVE_PATHS = {
    "apps/pa_agent/config/settings.json",
    "apps/pa_agent/config/settings.local.json",
    "apps/pa_agent/config/exception_state.json",
    "apps/pa_agent/config/secret.key",
}
SENSITIVE_GLOBS = (
    "records/pending/*.json",
    "records/pending/*.jsonl",
    "apps/pa_agent/records/pending/*.json",
    "apps/pa_agent/records/pending/*.jsonl",
)
SECRET_PATTERN = re.compile(
    r'api_key_encrypted["\s]*:\s*"[A-Za-z0-9+/=]{20,}"'
    r'|"api_key"\s*:\s*"[^*]{8,}"'
    r"|sk-[A-Za-z0-9]{12,}"
)


def run_git(*args: str) -> bytes:
    """运行 Git 命令并返回原始输出，失败时保留 Git 的错误信息。"""
    completed = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        sys.stderr.buffer.write(completed.stderr)
        raise SystemExit(completed.returncode)
    return completed.stdout


def staged_paths() -> list[str]:
    output = run_git("diff", "--cached", "--name-only", "--diff-filter=ACM", "-z")
    return [path.decode("utf-8", errors="surrogateescape") for path in output.split(b"\0") if path]


def blocked_path_reason(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    if normalized in SENSITIVE_PATHS:
        return "sensitive file"
    if normalized == ".env" or normalized.startswith(".env."):
        return "environment file"
    if normalized.startswith(("logs/", ".cache/")):
        return "log/cache file"
    if any(fnmatch.fnmatchcase(normalized, pattern) for pattern in SENSITIVE_GLOBS):
        return "analysis record"
    return None


def added_lines() -> list[str]:
    diff = run_git("diff", "--cached", "-U0", "--no-color").decode("utf-8", errors="replace")
    return [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def main() -> int:
    paths = staged_paths()
    if not paths:
        return 0

    for path in paths:
        reason = blocked_path_reason(path)
        if reason:
            print(f"pre-commit: blocked {reason}: {path}", file=sys.stderr)
            return 1

    if any(SECRET_PATTERN.search(line) for line in added_lines()):
        print(
            "pre-commit: staged diff may contain API key material "
            "(api_key / api_key_encrypted / sk-...)",
            file=sys.stderr,
        )
        print(
            "Unstage those changes and keep secrets in ignored local config files.", file=sys.stderr
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""导出 QuantHub 运行基线与「页面 -> API -> 服务 -> 数据表」依赖矩阵。

对应工作包：
    P0-03 导出运行与依赖基线
    P0-04 固化构建和回滚基线（本脚本负责其中的可机器复核部分）

设计原则：
    - 只读。不修改任何源码、数据库或配置。
    - 全部结论来自真实文件解析或真实运行时反射，不写入任何人工假设值。
    - 输出为 JSON + Markdown 两份，JSON 供后续门禁脚本比对，Markdown 供人工验收。

用法::

    uv run python tools/export_runtime_baseline.py
    uv run python tools/export_runtime_baseline.py --output docs/Plan/evidence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"
MAIN_TSX = WEB_SRC / "main.tsx"
WORKSPACES_TSX = WEB_SRC / "navigation" / "workspaces.tsx"
CLIENT_TS = WEB_SRC / "api" / "client.ts"
STORE_DB = ROOT / "apps" / "api" / "store.db"
RUNNER_DB = ROOT / "data" / "okx_runner" / "runner-shadow.db"

# ---------------------------------------------------------------------------
# 前端路由
# ---------------------------------------------------------------------------

_ROUTE_RE = re.compile(
    r"\{\s*(?:path:\s*'(?P<path>[^']*)'|(?P<index>index:\s*true))"
    r"[^}]*?import\('(?P<module>[^']+)'\)",
    re.DOTALL,
)


@dataclass
class RouteRecord:
    path: str
    module: str
    page_file: str | None
    exists: bool


def extract_routes() -> list[RouteRecord]:
    source = MAIN_TSX.read_text(encoding="utf-8")
    records: list[RouteRecord] = []
    for match in _ROUTE_RE.finditer(source):
        raw_path = match.group("path")
        path = "/" if match.group("index") else f"/{raw_path}"
        module = match.group("module")
        resolved = (MAIN_TSX.parent / module).with_suffix(".tsx")
        records.append(
            RouteRecord(
                path=path,
                module=module,
                page_file=str(resolved.relative_to(ROOT)).replace("\\", "/")
                if resolved.exists()
                else None,
                exists=resolved.exists(),
            )
        )
    return records


# ---------------------------------------------------------------------------
# 前端导航
# ---------------------------------------------------------------------------

_NAV_ITEM_RE = re.compile(
    r"\{\s*key:\s*'(?P<key>[^']+)',\s*label:\s*'(?P<label>[^']+)',\s*to:\s*'(?P<to>[^']+)'"
)
_WORKSPACE_RE = re.compile(r"key:\s*'(?P<key>cockpit|research|strategy|execution|operations)'")


def extract_navigation() -> list[dict[str, str]]:
    source = WORKSPACES_TSX.read_text(encoding="utf-8")
    items: list[dict[str, str]] = []
    for match in _NAV_ITEM_RE.finditer(source):
        items.append(
            {"key": match.group("key"), "label": match.group("label"), "to": match.group("to")}
        )
    return items


def extract_route_presentations() -> list[dict[str, str]]:
    source = WORKSPACES_TSX.read_text(encoding="utf-8")
    block = source.split("ROUTE_PRESENTATIONS", 1)
    if len(block) < 2:
        return []
    entries: list[dict[str, str]] = []
    pattern = re.compile(
        r"\{\s*workspaceKey:\s*'(?P<ws>[^']+)',\s*board:\s*'(?P<board>[^']+)',"
        r"\s*label:\s*'(?P<label>[^']+)',\s*(?P<kind>exact|prefix):\s*'(?P<value>[^']+)'"
    )
    for match in pattern.finditer(block[1]):
        entries.append(
            {
                "workspace": match.group("ws"),
                "board": match.group("board"),
                "label": match.group("label"),
                "match_kind": match.group("kind"),
                "match_value": match.group("value"),
            }
        )
    return entries


# ---------------------------------------------------------------------------
# 前端 API 客户端方法 -> 后端路径
# ---------------------------------------------------------------------------

_API_METHOD_RE = re.compile(
    r"^\s{2}(?P<name>[A-Za-z0-9_]+):\s*(?:\([^)]*\)|async\s*\([^)]*\))\s*=>",
    re.MULTILINE,
)
_GETJSON_PATH_RE = re.compile(r"getJSON<[^>]*>\(\s*[`'\"](?P<path>[^`'\"]+)[`'\"]")
_HTTP_METHOD_RE = re.compile(r"method:\s*'(?P<method>[A-Z]+)'")


def extract_api_methods() -> dict[str, dict[str, Any]]:
    source = CLIENT_TS.read_text(encoding="utf-8")
    start = source.find("export const api = {")
    if start < 0:
        return {}
    body = source[start:]
    matches = list(_API_METHOD_RE.finditer(body))
    methods: dict[str, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[match.start() : end]
        path_match = _GETJSON_PATH_RE.search(chunk)
        if path_match is None:
            continue
        verb_match = _HTTP_METHOD_RE.search(chunk)
        methods[match.group("name")] = {
            "path": path_match.group("path"),
            "http_method": verb_match.group("method") if verb_match else "GET",
        }
    return methods


# ---------------------------------------------------------------------------
# 页面 -> 使用了哪些 api.xxx
# ---------------------------------------------------------------------------

_API_USAGE_RE = re.compile(r"\bapi\.(?P<name>[A-Za-z0-9_]+)\b")


def collect_frontend_sources() -> list[Path]:
    return sorted(
        p
        for p in WEB_SRC.rglob("*.ts*")
        if p.suffix in {".ts", ".tsx"} and not p.name.endswith(".d.ts")
    )


def build_page_api_usage(api_methods: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    usage: dict[str, list[str]] = {}
    for path in collect_frontend_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        names = sorted({m.group("name") for m in _API_USAGE_RE.finditer(text)} & set(api_methods))
        if names:
            usage[str(path.relative_to(ROOT)).replace("\\", "/")] = names
    return usage


# ---------------------------------------------------------------------------
# 前端引用图（用于孤立文件检测）
# ---------------------------------------------------------------------------

# 覆盖三种引用形式：
#   import X from './a'      /  export * from './a'
#   import('./a')            —— react-router lazy 动态导入
#   import './a.css'         —— 副作用导入
_IMPORT_RE = re.compile(r"""(?:from\s*|import\s*\(\s*|import\s+)['"](?P<spec>\.[^'"]+)['"]""")


def build_reachable_frontend_files() -> tuple[set[str], set[str]]:
    """从 main.tsx 出发做可达性遍历，返回 (可达文件集, 全部文件集)。"""
    all_files = {str(p.relative_to(ROOT)).replace("\\", "/") for p in collect_frontend_sources()}

    def resolve(base: Path, spec: str) -> Path | None:
        candidate = (base.parent / spec).resolve()
        for suffix in ("", ".ts", ".tsx"):
            probe = Path(str(candidate) + suffix)
            if probe.is_file():
                return probe
        for name in ("index.ts", "index.tsx"):
            probe = candidate / name
            if probe.is_file():
                return probe
        return None

    reachable: set[str] = set()
    queue = [MAIN_TSX]
    while queue:
        current = queue.pop()
        key = str(current.relative_to(ROOT)).replace("\\", "/")
        if key in reachable:
            continue
        reachable.add(key)
        text = current.read_text(encoding="utf-8", errors="replace")
        for match in _IMPORT_RE.finditer(text):
            target = resolve(current, match.group("spec"))
            if target is not None and target.is_relative_to(ROOT):
                queue.append(target)
    return reachable, all_files


# ---------------------------------------------------------------------------
# 后端路由（运行时反射）
# ---------------------------------------------------------------------------


def extract_backend_routes() -> list[dict[str, Any]]:
    """从 OpenAPI schema 读取已挂载路由。

    本仓库使用的 FastAPI 版本对 ``include_router`` 采用惰性 ``_IncludedRouter``
    包装，直接遍历 ``app.routes`` 只能拿到 4 条内置文档路由 + ``/health``。
    ``app.openapi()`` 会强制展开全部子路由，是唯一可靠的真实来源。
    """
    sys.path.insert(0, str(ROOT))
    from apps.api.main import app  # noqa: PLC0415

    schema = app.openapi()
    routes: list[dict[str, Any]] = []
    for path, operations in schema.get("paths", {}).items():
        methods = sorted(
            m.upper() for m in operations if m.lower() in {"get", "post", "put", "patch", "delete"}
        )
        tags: list[str] = []
        operation_ids: list[str] = []
        for verb, operation in operations.items():
            if verb.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            tags.extend(operation.get("tags", []))
            if operation.get("operationId"):
                operation_ids.append(operation["operationId"])
        routes.append(
            {
                "path": path,
                "methods": methods,
                "tags": sorted(set(tags)),
                "operation_ids": operation_ids,
            }
        )
    return sorted(routes, key=lambda item: item["path"])


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------


def describe_database(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"path": str(db_path.relative_to(ROOT)).replace("\\", "/"), "exists": False}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {}
        for table in tables:
            counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return {
        "path": str(db_path.relative_to(ROOT)).replace("\\", "/"),
        "exists": True,
        "sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "size_bytes": db_path.stat().st_size,
        "integrity_check": integrity,
        "table_count": len(tables),
        "row_total": sum(counts.values()),
        "tables": counts,
    }


# ---------------------------------------------------------------------------
# Git / 启动脚本
# ---------------------------------------------------------------------------


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def collect_startup_surface() -> dict[str, Any]:
    scripts: dict[str, Any] = {}
    package_json = ROOT / "web" / "package.json"
    if package_json.exists():
        scripts["web_npm_scripts"] = json.loads(package_json.read_text(encoding="utf-8")).get(
            "scripts", {}
        )
    scripts["shell_scripts"] = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.glob("scripts/*") if p.is_file()
    )
    scripts["dockerfiles"] = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in list(ROOT.glob("Dockerfile*")) + list(ROOT.glob("docker/**/*"))
        if p.is_file()
    )
    scripts["github_workflows"] = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in (ROOT / ".github" / "workflows").glob("*.yml")
    )
    return scripts


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------


@dataclass
class Baseline:
    generated_at: str
    git_branch: str
    git_head: str
    git_dirty_files: list[str]
    routes: list[dict[str, Any]] = field(default_factory=list)
    navigation: list[dict[str, str]] = field(default_factory=list)
    route_presentations: list[dict[str, str]] = field(default_factory=list)
    api_methods: dict[str, Any] = field(default_factory=dict)
    page_api_usage: dict[str, list[str]] = field(default_factory=dict)
    backend_routes: list[dict[str, Any]] = field(default_factory=list)
    orphan_frontend_files: list[str] = field(default_factory=list)
    databases: dict[str, Any] = field(default_factory=dict)
    startup: dict[str, Any] = field(default_factory=dict)


def build_baseline() -> Baseline:
    api_methods = extract_api_methods()
    reachable, all_files = build_reachable_frontend_files()
    orphans = sorted(
        f
        for f in all_files - reachable
        if not f.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    )
    return Baseline(
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        git_branch=git("rev-parse", "--abbrev-ref", "HEAD"),
        git_head=git("rev-parse", "HEAD"),
        git_dirty_files=[line for line in git("status", "--porcelain=v1").splitlines() if line],
        routes=[r.__dict__ for r in extract_routes()],
        navigation=extract_navigation(),
        route_presentations=extract_route_presentations(),
        api_methods=api_methods,
        page_api_usage=build_page_api_usage(api_methods),
        backend_routes=extract_backend_routes(),
        orphan_frontend_files=orphans,
        databases={
            "store": describe_database(STORE_DB),
            "okx_runner_shadow": describe_database(RUNNER_DB),
        },
        startup=collect_startup_surface(),
    )


def render_markdown(baseline: Baseline) -> str:
    lines: list[str] = []
    add = lines.append
    add("# QuantHub 运行与依赖基线")
    add("")
    add(f"- 生成时间：`{baseline.generated_at}`")
    add(f"- 分支：`{baseline.git_branch}`")
    add(f"- HEAD：`{baseline.git_head}`")
    add(f"- 工作区未提交条目数：`{len(baseline.git_dirty_files)}`")
    add("")
    add("> 本文件由 `tools/export_runtime_baseline.py` 生成，禁止手工编辑。")
    add("")

    add("## 1. 前端路由")
    add("")
    add("| 路由 | 页面文件 | 文件存在 |")
    add("| --- | --- | --- |")
    for route in baseline.routes:
        add(
            f"| `{route['path']}` | `{route['page_file'] or route['module']}` | {'是' if route['exists'] else '**否**'} |"
        )
    add("")

    add("## 2. 一级导航项")
    add("")
    add("| key | 标签 | 目标 |")
    add("| --- | --- | --- |")
    for item in baseline.navigation:
        add(f"| `{item['key']}` | {item['label']} | `{item['to']}` |")
    add("")

    add("## 3. 页面 -> API -> 后端路由 依赖矩阵")
    add("")
    add("| 前端文件 | 调用的 api 方法 | 实际请求路径 |")
    add("| --- | --- | --- |")
    for source, names in sorted(baseline.page_api_usage.items()):
        paths = sorted({baseline.api_methods[n]["path"].split("?")[0] for n in names})
        add(
            f"| `{source}` | {len(names)} 个 | {', '.join(f'`{p}`' for p in paths[:8])}{' …' if len(paths) > 8 else ''} |"
        )
    add("")

    add("## 4. 后端已挂载路由")
    add("")
    add(f"共 `{len(baseline.backend_routes)}` 条。")
    add("")
    add("| 路径 | 方法 | tags |")
    add("| --- | --- | --- |")
    for route in baseline.backend_routes:
        add(
            f"| `{route['path']}` | {', '.join(route['methods'])} | {', '.join(route['tags']) or '-'} |"
        )
    add("")

    add("## 5. 前端孤立文件（从 main.tsx 不可达，已排除测试文件）")
    add("")
    if baseline.orphan_frontend_files:
        for item in baseline.orphan_frontend_files:
            add(f"- `{item}`")
    else:
        add("- 无")
    add("")

    add("## 6. 数据库")
    add("")
    for name, info in baseline.databases.items():
        add(f"### `{name}`")
        add("")
        if not info.get("exists"):
            add(f"- 路径 `{info['path']}` 不存在")
            add("")
            continue
        add(f"- 路径：`{info['path']}`")
        add(f"- SHA-256：`{info['sha256']}`")
        add(f"- 大小：`{info['size_bytes']}` 字节")
        add(f"- `integrity_check`：`{info['integrity_check']}`")
        add(f"- 表数：`{info['table_count']}`，总行数：`{info['row_total']}`")
        add("")

    add("## 7. 启动面")
    add("")
    add("```json")
    add(json.dumps(baseline.startup, indent=2, ensure_ascii=False))
    add("```")
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/Plan/evidence", help="输出目录")
    args = parser.parse_args()

    out_dir = (ROOT / args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = build_baseline()
    json_path = out_dir / "P0-03-runtime-baseline.json"
    md_path = out_dir / "P0-03-runtime-baseline.md"
    json_path.write_text(
        json.dumps(baseline.__dict__, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    md_path.write_text(render_markdown(baseline), encoding="utf-8")

    print(f"routes                = {len(baseline.routes)}")
    print(f"nav items             = {len(baseline.navigation)}")
    print(f"api client methods    = {len(baseline.api_methods)}")
    print(f"backend routes        = {len(baseline.backend_routes)}")
    print(f"orphan frontend files = {len(baseline.orphan_frontend_files)}")
    print(f"store tables          = {baseline.databases['store'].get('table_count')}")
    print(f"written               = {json_path.relative_to(ROOT)}")
    print(f"written               = {md_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

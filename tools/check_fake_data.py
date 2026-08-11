"""生产假数据扫描门禁（工作包 M3-01）。

目标（路线图 阶段 3）：
    - 生产代码禁止出现 ``mock`` / ``fake`` / ``sample`` / ``demoData`` 等假数据构造，
      禁止硬编码行情、随机收益曲线，禁止「后端失败后前端降级到 mock」。
    - 测试目录、fixture、演示脚本允许使用上述词汇。

用法::

    python tools/check_fake_data.py                 # 扫描默认生产范围
    python tools/check_fake_data.py --json          # 机器可读报告
    python tools/check_fake_data.py --baseline docs/Plan/evidence/M3-01-fake-data-baseline.json

退出码：0 表示无新增违规；1 表示存在违规（CI 应据此阻断）。

设计约束：
    - 只做**确定性**匹配，不猜测。命中即报出文件、行号与原文，便于人工核验。
    - 允许清单（``ALLOWLIST``）必须写明理由，禁止无理由豁免。
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 生产扫描范围：真正会进入生产构建 / 生产运行时的目录。
#
# 2026-08-09 复核补充：原范围漏掉了 packages / strategies / configs 三块生产代码与
# 配置。策略与数据包同样会进入生产运行时，配置文件同样会决定生产行为，必须纳入。
PRODUCTION_ROOTS = (
    Path("web/src"),
    Path("apps/api"),
    Path("apps/okx_runner"),
    Path("core"),
    Path("packages"),
    Path("strategies"),
    Path("configs"),
)

# 明确豁免：测试、fixture、演示与工具链本身。
EXCLUDED_PARTS = (
    "__pycache__",
    "node_modules",
    ".venv",
    "dist",
    "build",
    "tests",
    "test",
    "__tests__",
    "_demo",
    "fixtures",
)
EXCLUDED_SUFFIX_MARKERS = (
    ".test.ts",
    ".test.tsx",
    ".spec.ts",
    ".spec.tsx",
    "_test.py",
    ".example",
    ".env.example",
)
# 除源码外，配置与随源码分发的 JSON/YAML 数据同样能把假数据带进生产。
SCAN_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".py", ".json", ".yaml", ".yml"}

# 注释行不参与执行，不构成生产假数据。按语言的行注释前缀确定性跳过。
COMMENT_PREFIXES = ("#", "//", "*", "<!--")


@dataclass(frozen=True)
class Rule:
    code: str
    pattern: re.Pattern[str]
    description: str
    #: 不为 None 时，命中文本尾部的数值需达到该量级（或含两位以上小数）才算违规，
    #: 用于把 `price: 0` / `qty = 1` 这类默认值与真实行情数值区分开。
    numeric_threshold: float | None = None


RULES: tuple[Rule, ...] = (
    Rule(
        code="FAKE_IDENTIFIER",
        pattern=re.compile(
            r"\b(?:mock|fake|dummy|stub)(?:ed|ing)?[A-Z_]\w*|\b(?:MOCK|FAKE|DUMMY)_\w+"
        ),
        description="生产代码出现 mock/fake/dummy/stub 命名的标识符",
    ),
    Rule(
        code="DEMO_DATA",
        pattern=re.compile(
            r"\bdemoData\b|\bsampleData\b|\bSAMPLE_DATA\b|\bseedDemo\w*|\bdemo_seed\w*"
        ),
        description="生产代码出现演示 / 样例数据构造",
    ),
    Rule(
        code="FAKE_FALLBACK",
        pattern=re.compile(
            r"降级到\s*mock|回退到\s*mock|fallback\s+to\s+mock|mock\s*兜底|假数据兜底"
        ),
        description="存在「失败后降级到 mock」的逻辑或文案",
    ),
    Rule(
        code="RANDOM_SERIES",
        pattern=re.compile(r"Math\.random\s*\(\s*\)|\brandom\.uniform\s*\(|\bnp\.random\."),
        description="生产代码使用随机数生成展示数据（随机收益 / 随机行情）",
    ),
    Rule(
        code="HARDCODED_MARKET_VALUE",
        pattern=re.compile(
            r"(?<![\w.])(?:price|close|open|high|low|last|bid|ask|markPrice|mark_price"
            r"|nav|equity|balance|marketValue|market_value|avgCost|avg_cost"
            r"|unrealizedPnl|unrealized_pnl|pnl|holding|holdings"
            r"|position_size|positionSize|quantity|qty)"
            r"\s*[:=]\s*-?\d+(?:\.\d+)?",
            re.IGNORECASE,
        ),
        description="生产代码把行情 / 持仓 / 资产数值写死为字面量",
        numeric_threshold=100.0,
    ),
    Rule(
        code="HARDCODED_SERIES",
        pattern=re.compile(
            r"(?<![\w.])(?:candles?|klines?|ohlc|series|prices|values|returns"
            r"|equityCurve|equity_curve|navCurve|nav_curve)"
            r"\s*[:=]\s*\[\s*-?\d+(?:\.\d+)?\s*,(?:\s*-?\d+(?:\.\d+)?\s*,){2,}",
            re.IGNORECASE,
        ),
        description="生产代码内联写死行情 / 净值序列（≥4 个数值的字面量数组）",
    ),
)

# 允许清单：key = "相对路径:规则码"。禁止无理由条目。
#
# value 有两种写法：
#   - ``str``：整文件对该规则豁免（粗粒度，仅用于全文件性质一致的情况）。
#   - ``dict``：``{"reason": ..., "matches": [...]}``，只豁免列出的**具体命中文本**。
#     推荐用后者——否则一条豁免会连带掩盖同一文件里后来新增的真违规。
#
# 豁免原则（人工核验过才可加入）：
#   1) 随机数只用于生成 id / 幂等键，不进入任何展示数值；或
#   2) 随机数是统计方法本身的一部分（bootstrap 置信区间、置换检验），
#      其输入是**真实样本**，输出是统计量而非伪造的行情/收益；或
#   3) 数值是表单输入框的默认值 / 业务常量（如 A 股一手 = 100 股），
#      不是被当作行情或持仓展示给用户的数据。
#   4) 合成数据是用户显式选择、确定性可复现并在响应中明确标注“无真实市场数据”的
#      压力测试源；它不得作为真实数据失败后的兜底，也不得写入生产信号账本。
ALLOWLIST: dict[str, str | dict] = {
    "web/src/pages/TradingWorkspacePage.tsx:RANDOM_SERIES": "crypto.randomUUID 不可用时生成幂等键 intent_id，非展示数据。",
    "web/src/lib/uid.ts:RANDOM_SERIES": "生成前端本地唯一 key，非展示数据。",
    "core/factor_research.py:RANDOM_SERIES": "np.random.default_rng(seed) 用于 IC 的 bootstrap 置信区间估计，"
    "输入为真实因子/收益样本，输出为统计量，不构造行情数据。",
    "core/factor_robustness.py:RANDOM_SERIES": "np.random.default_rng(seed) 用于置换检验（permutation test）打乱真实样本标签，"
    "用于显著性判定，不构造行情数据。",
    "core/backtest/dataset.py:RANDOM_SERIES": {
        "reason": "用户必须显式选择 synthetic 数据源；默认源为 okx_local。生成结果按 seed 确定性复现，"
        "API provenance 明确标注‘确定性合成行情（无真实市场数据）’，真实数据失败不会回退到该源。",
        "matches": ["np.random."],
    },
    "web/src/pages/LedgerPage.tsx:HARDCODED_MARKET_VALUE": {
        "reason": "手工补录交易的表单默认数量（A 股一手 = 100 股），是 useState 输入框初值；"
        "同一表单的 price / fee 默认为 0，不存在写死行情。",
        "matches": ["quantity: 100"],
    },
    "web/src/pages/SimulationOrdersPage.tsx:HARDCODED_MARKET_VALUE": {
        "reason": "模拟下单表单的默认数量（A 股一手 = 100 股），useState 初值，非行情/持仓展示值。",
        "matches": ["quantity: 100"],
    },
}


def _exemption_for(exemption: str | dict, matched_text: str) -> str | None:
    """返回豁免理由；若该豁免限定了具体命中文本而本次不匹配，则返回 None。"""
    if isinstance(exemption, str):
        return exemption
    allowed_matches = exemption.get("matches")
    if allowed_matches and matched_text not in allowed_matches:
        return None
    return exemption["reason"]


_TRAILING_NUMBER = re.compile(r"-?\d+(?:\.\d+)?$")


def _is_market_like_number(matched: str, threshold: float) -> bool:
    """判断命中文本尾部的数值是否像真实行情，而不是 0/1 这类默认值。"""
    found = _TRAILING_NUMBER.search(matched.strip())
    if not found:
        return False
    raw = found.group(0)
    value = abs(float(raw))
    if value >= threshold:
        return True
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    return decimals >= 2 and value > 0


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(prefix) for prefix in COMMENT_PREFIXES)


def _is_excluded(path: Path) -> bool:
    posix = path.as_posix()
    if any(f"/{part}/" in f"/{posix}/" for part in EXCLUDED_PARTS):
        return True
    return any(posix.endswith(marker) for marker in EXCLUDED_SUFFIX_MARKERS)


def iter_production_files() -> list[Path]:
    files: list[Path] = []
    for root in PRODUCTION_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            relative = path.relative_to(ROOT)
            if _is_excluded(relative):
                continue
            files.append(path)
    return files


def scan() -> dict:
    findings: list[dict] = []
    allowed: list[dict] = []
    files = iter_production_files()

    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if _is_comment(line):
                continue
            for rule in RULES:
                match = rule.pattern.search(line)
                if not match:
                    continue
                if rule.numeric_threshold is not None and not _is_market_like_number(
                    match.group(0), rule.numeric_threshold
                ):
                    continue
                record = {
                    "code": rule.code,
                    "description": rule.description,
                    "path": relative,
                    "line": index,
                    "match": match.group(0),
                    "text": line.strip()[:200],
                }
                key = f"{relative}:{rule.code}"
                if key in ALLOWLIST:
                    reason = _exemption_for(ALLOWLIST[key], match.group(0))
                    if reason is not None:
                        allowed.append(record | {"reason": reason})
                        continue
                findings.append(record)

    return {
        "task": "M3-01",
        "files_scanned": len(files),
        "roots": [root.as_posix() for root in PRODUCTION_ROOTS],
        "rules": [asdict(rule) | {"pattern": rule.pattern.pattern} for rule in RULES],
        "allowlisted": allowed,
        "findings": findings,
        "passed": not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生产假数据扫描门禁（M3-01）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    parser.add_argument("--baseline", type=Path, help="写入 JSON 报告到指定路径")
    args = parser.parse_args()

    report = scan()
    if args.baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"扫描生产文件 {report['files_scanned']} 个，豁免命中 {len(report['allowlisted'])} 处。"
        )
        if report["findings"]:
            print(f"发现 {len(report['findings'])} 处生产假数据违规：")
            for item in report["findings"]:
                print(f"  [{item['code']}] {item['path']}:{item['line']}  {item['match']}")
                print(f"      {item['text']}")
        else:
            print("通过：生产范围内未发现假数据构造。")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""QuantHub 策略脚手架 —— 资深开发者定的"团队规范即代码"。

按 docs/CODE_QUALITY.md 的契约，一键生成一个**合规**的策略包：
    strategies/<market>/<name>/
        strategy.py     # StrategyBase + @register_strategy，produce/backtest/live_tick 全对齐契约
        __init__.py    # 导出类 + run_* 便捷入口
        pyproject.toml  # workspace 成员（仅依赖 strategies-base/quanthub-core）
并自动登记到：
    strategies/__init__.py   (_STRATEGY_MODULES)
    configs/<market>.yaml     (modules.<name>)
    pyproject.toml           ([tool.uv.workspace] members)

用法：
    uv run python tools/scaffold_strategy.py --name myalpha --market a_shares --desc "示例Alpha"
    uv run python tools/scaffold_strategy.py --name myalpha --market a_shares --dry-run   # 只打印，不落盘

安全：
    - 目标包已存在则拒绝（不覆盖）。
    - 登记步骤幂等（已存在则跳过）。
    - --dry-run 完全不写盘，只打印将要做什么。
"""
from __future__ import annotations

import argparse
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent
_VALID_MARKETS = ("a_shares", "crypto", "mt5", "ai_analysis")

_STRATEGY_TPL = '''# -*- coding: utf-8 -*-
"""{desc}

按 docs/CODE_QUALITY.md 契约生成的策略插件（脚手架产出，勿手搓）。
- produce(): 产出 Signal 列表（务必支持离线/无 key 降级，禁止抛未捕获异常）
- backtest(): 必须返回 core.backtest.BacktestResult（不支持则 .empty()）
- live_tick(): 默认 no-op，实盘双开关关闭
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from core.backtest import BacktestResult
from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)


@register_strategy(StrategyInfo(
    name="{name}",
    market="{market}",
    version="0.1.0",
    live_capable={live_capable},
    description="{desc}",
))
class {class_name}(StrategyBase):
    def produce(self, **kwargs: Any) -> list[Signal]:
        """产出信号。这里仅作骨架示例，按需接入 core.data_feed / 因子 / LLM。"""
        # TODO: 拉数据 -> 计算 -> 生成 Signal 并 self.publish(sig)
        return []

    def backtest(self, klines: pd.DataFrame, **kwargs: Any) -> "BacktestResult":
        """回测。不支持时返回空结果（绝不 raise）。"""
        if klines is None or klines.empty:
            return BacktestResult.empty(engine="none")
        # TODO: 用 core.backtest.EventEngine / GridBacktester 跑，返回 BacktestResult
        return BacktestResult.empty(engine="none")

    def live_tick(self, **kwargs: Any) -> None:
        if not self.is_live():
            logger.debug("{name}: 非实盘模式，live_tick no-op")
            return
        # TODO: 实盘下单逻辑（is_live() 已确保双开关开启）
'''

_INIT_TPL = '''"""{desc} 策略模块。

导出:
    - {class_name} : 策略类（继承 StrategyBase，已 @register_strategy）
    - run_{name}   : 供 apps.scheduler / CLI 调用的便捷入口
"""
from __future__ import annotations

from strategies.{market}.{name}.strategy import {class_name}


def run_{name}(symbol: str | None = None, **kwargs: Any) -> list:
    """便捷入口：按 configs/{market}.yaml 实例化并产出信号。"""
    from core.config import get_config
    cfg = get_config().get("modules", {{}}).get("{name}", {{}}) or {{}}
    strat = {class_name}(config=cfg)
    return strat.produce(symbol=symbol, **kwargs)


__all__ = ["{class_name}", "run_{name}"]
'''

_PYPROJECT_TPL = '''[project]
name = "quanthub-{name}"
version = "0.1.0"
description = "{desc}"
requires-python = ">=3.11,<3.13"
dependencies = [
    "quanthub-core",
    "strategies-base",
]

[tool.uv.sources]
quanthub-core = {{ workspace = true }}
strategies-base = {{ workspace = true }}
'''


def _class_name(name: str) -> str:
    return "".join(w.capitalize() for w in name.split("_")) + "Strategy"


def _insert_before_closing_bracket(text: str, marker: str, new_line: str) -> Optional[str]:
    """在 text 中定位以 marker 开头的块，在其闭合 `]` 前插入 new_line（幂等）。"""
    if new_line.strip() in text:
        return None  # 已存在，跳过
    idx = text.find(marker)
    if idx < 0:
        return None
    # 从 marker 行之后找第一个顶格的 `]`（块闭合）
    rest = text[idx:]
    m = re.search(r"\n(\s*)\]", rest)
    if not m:
        return None
    insert_at = idx + m.start() + 1 + len(m.group(1))  # 指向 `]` 前
    # 用与列表项一致的缩进
    indent = re.search(r"(\n\s*)\"[^\"]*\",", rest)
    prefix = indent.group(1) if indent else "\n    "
    return text[:insert_at] + prefix + new_line.strip() + "\n" + text[insert_at:]


def _append_yaml_module(text: str, name: str, desc: str) -> Optional[str]:
    """在 configs yaml 的 modules: 块末尾插入新模块（幂等）。"""
    if f"  {name}:" in text:
        return None
    lines = text.splitlines(keepends=True)
    mod_idx = next((i for i, l in enumerate(lines) if l.strip() == "modules:"), None)
    if mod_idx is None:
        # 无 modules 段则追加
        block = f"\nmodules:\n  {name}:\n    enabled: false\n    description: \"{desc}\"\n"
        return text + block
    # 找 modules: 下最后一个 2 空格缩进的子项
    last = mod_idx
    for j in range(mod_idx + 1, len(lines)):
        if re.match(r"  [A-Za-z]", lines[j]):
            last = j
        elif re.match(r"\S", lines[j]):  # 遇到顶格/其它键，块结束
            break
    new_block = f"  {name}:\n    enabled: false\n    description: \"{desc}\"\n"
    out = lines[:last + 1] + [new_block] + lines[last + 1:]
    return "".join(out)


def scaffold(
    name: str,
    market: str,
    desc: str,
    author: str = "QuantHub Team",
    live_capable: bool = False,
    repo_root: Path = _REPO_ROOT_DEFAULT,
    dry_run: bool = False,
) -> list[str]:
    """执行脚手架。返回将要/已经做的操作日志。"""
    log: list[str] = []
    if market not in _VALID_MARKETS:
        raise ValueError(f"market 必须是 {_VALID_MARKETS}，收到: {market}")
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise ValueError("name 需小写字母/数字/下划线，且以字母开头")

    pkg_dir = repo_root / "strategies" / market / name
    if pkg_dir.exists():
        raise FileExistsError(f"策略包已存在，拒绝覆盖: {pkg_dir}")

    class_name = _class_name(name)
    strategy_py = _STRATEGY_TPL.format(
        name=name, market=market, desc=desc, author=author, class_name=class_name,
        live_capable=str(live_capable).lower(),
    )
    init_py = _INIT_TPL.format(name=name, market=market, desc=desc, class_name=class_name)
    pyproject = _PYPROJECT_TPL.format(name=name, desc=desc)

    # 1) 生成包文件
    files = {
        pkg_dir / "strategy.py": strategy_py,
        pkg_dir / "__init__.py": init_py,
        pkg_dir / "pyproject.toml": pyproject,
    }
    if dry_run:
        log.append(f"[dry-run] 将创建目录: {pkg_dir}")
        for p, c in files.items():
            log.append(f"[dry-run] 将写入 ({len(c)}B): {p}")
    else:
        pkg_dir.mkdir(parents=True, exist_ok=True)
        for p, c in files.items():
            p.write_text(c, encoding="utf-8")
            log.append(f"已创建: {p}")

    # 2) 登记到 strategies/__init__.py
    init_py_path = repo_root / "strategies" / "__init__.py"
    module_line = f'    "strategies.{market}.{name}",'
    if dry_run:
        log.append(f"[dry-run] 将在 {init_py_path} 的 _STRATEGY_MODULES 追加: {module_line}")
    else:
        t = init_py_path.read_text(encoding="utf-8")
        new_t = _insert_before_closing_bracket(t, "_STRATEGY_MODULES = [", module_line)
        if new_t is None:
            log.append(f"跳过登记（已存在或找不到 _STRATEGY_MODULES）: {init_py_path}")
        else:
            init_py_path.write_text(new_t, encoding="utf-8")
            log.append(f"已登记模块: {init_py_path}")

    # 3) 追加到 configs/<market>.yaml
    cfg_path = repo_root / "configs" / f"{market}.yaml"
    if cfg_path.exists():
        if dry_run:
            log.append(f"[dry-run] 将在 {cfg_path} 的 modules: 下追加模块 {name}")
        else:
            t = cfg_path.read_text(encoding="utf-8")
            new_t = _append_yaml_module(t, name, desc)
            if new_t is None:
                log.append(f"跳过配置（{name} 已存在）: {cfg_path}")
            else:
                cfg_path.write_text(new_t, encoding="utf-8")
                log.append(f"已追加配置: {cfg_path}")
    else:
        log.append(f"[警告] 找不到 {cfg_path}，请手动创建并加 modules.{name}")

    # 4) 追加到根 pyproject.toml workspace members
    root_pyproject = repo_root / "pyproject.toml"
    member_line = f'    "strategies/{market}/{name}",'
    if dry_run:
        log.append(f"[dry-run] 将在 {root_pyproject} 的 [tool.uv.workspace] members 追加: {member_line}")
    else:
        t = root_pyproject.read_text(encoding="utf-8")
        new_t = _insert_before_closing_bracket(t, "[tool.uv.workspace]", member_line)
        if new_t is None:
            log.append(f"跳过 workspace 成员（已存在或找不到）: {root_pyproject}")
        else:
            root_pyproject.write_text(new_t, encoding="utf-8")
            log.append(f"已追加 workspace 成员: {root_pyproject}")

    log.append("")
    log.append("下一步：")
    log.append(f"  uv sync                         # 安装新成员")
    log.append(f"  uv run pytest tests/ -q        # 必须全绿（记得加 tests/ 覆盖新策略）")
    log.append(f"  uv run python -c \"from strategies import discover_and_register, list_strategies; "
               f"discover_and_register(); print('{name}' in list_strategies())\"")
    return log


def main() -> None:
    ap = argparse.ArgumentParser(description="QuantHub 策略脚手架")
    ap.add_argument("--name", required=True, help="策略名（小写_下划线）")
    ap.add_argument("--market", required=True, choices=_VALID_MARKETS)
    ap.add_argument("--desc", default="", help="策略描述")
    ap.add_argument("--author", default="QuantHub Team")
    ap.add_argument("--live-capable", action="store_true", help="是否支持实盘")
    ap.add_argument("--repo", default=str(_REPO_ROOT_DEFAULT), help="仓库根（测试用）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    args = ap.parse_args()

    try:
        log = scaffold(
            name=args.name, market=args.market, desc=args.desc or args.name,
            author=args.author, live_capable=args.live_capable,
            repo_root=Path(args.repo), dry_run=args.dry_run,
        )
    except (ValueError, FileExistsError) as e:
        print(f"[错误] {e}")
        raise SystemExit(2)
    print("\n".join(log))


if __name__ == "__main__":
    main()

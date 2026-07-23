# QuantHub 整合 + 团队技术提升 + 代码质量把控 · 总计划

> 版本：v1（执行稿）· 2026-07-23
> 作者：Senior Developer（高级开发工程师）
> 范围：把分散量化项目整合为统一仓库的基础上，**补齐团队工程能力 + 代码质量门禁**，并完成 PA_Agent 上游的「桌面 + 看板双轨」融合。

---

## 0. 执行摘要

**本次已落地（已验证）：**
- ✅ PA_Agent 上游以「双轨」方式并入 `apps/pa_agent/`（142 个引擎/UI 模块 + config + tests + docs，自包含，重依赖走可选组）。
- ✅ 收割上游的密钥拦截实践，搭建 QuantHub **全局质量门禁脚手架**：`.github/workflows/ci.yml` + `.pre-commit-config.yaml` + `tools/block_secrets.sh`。
- ✅ 实测：`uv sync --extra dev` 解析 192 包；`compileall` 校验 142 模块通过；原 **52 测试零回归**。

**待执行（见 §5）：** git 初始化、CI 激活、引擎统一（Phase 2）、看板视图增强、vendored 正本刷新、指数数据修复（P-C）。

---

## 1. 整合现状核查（实测，非文档宣称）

| 维度 | 发现 | 状态 |
|---|---|---|
| 分层架构 | apps / core / strategies / configs 齐备，uv workspace 16 成员 | ✅ |
| 测试 | 52 用例全过（核心健康） | ✅ |
| 策略插件 | 11 策略经 `strategies.discover_and_register()` 加载（顶层 import 不会自动注册） | ✅ |
| **版本控制** | **仓库不是 git 仓库（无 .git）**，文档却通篇讲 .gitignore 排除 | ❌ 重大缺口 |
| **CI / pre-commit** | 无 `.github`、无 pre-commit、无类型检查（仅有 ruff lint 配置） | ❌ |
| **测试可复现性** | `.venv` 默认未装 pytest，需 `uv sync --extra dev` 才能跑 | ❌ 团队大概率没在跑测试 |

> 结论：代码底座健康，但**工程纪律是真空**——这正是「团队技术能力提升 + 代码质量把控」要补的核心。

---

## 2. PA_Agent 融合（双轨方案）

### 2.1 现场评估（已克隆上游到隔离沙箱比对）
- 上游为 **~6.5 万行独立 PyQt6 桌面应用**（`pa-agent` CLI），自带 GUI（主窗口 / K线图 / 决策树面板 / 对话窗 / 设置对话框，且是代码写 UI 非 .ui 文件，利于移植）。
- 与现有整合层**仅文件名重叠** `orchestrator/two_stage.py`；上游**未用** QuantHub 的 `StrategyBase` 插件接口。
- 重依赖与 QuantHub 设计不兼容：PyQt6/GUI、MetaTrader5(win32)、tvdatafeed(git 依赖)、baostock、tushare、cursor-sdk、飞书/Cursor/QClaw/MIMO 连接器、独立 `config/settings.json`。
- **LICENSE = AGPL-3.0，与 QuantHub(AGPL-3.0-or-later) 完全兼容**，无许可冲突。

### 2.2 已落地（本次）
- `apps/pa_agent/` 成员：复制上游 `pa_agent/`（引擎+GUI）、`run.py`、`config/`（示例）、`tests/`、`docs/`，及上游的 `Makefile/README/CONTRIBUTING/SECURITY`。
- 成员 `pyproject.toml`：基础库常装；重依赖拆为可选组 `pa-agent-desktop` / `pa-agent-data` / `pa-agent-win32`（默认不装）。
- **【前端主基调】PA_Agent 的 PyQt6 桌面应用即整合后产品的旗舰前端**。已在成员 `pyproject.toml` 注册控制台入口 `quanthub-desktop = "pa_agent.main:main"`，`uv sync` 后可直接 `uv run quanthub-desktop` 启动；其暗色主题 / 决策树 / K线 / 分析快照 / 案例库的交互范式，作为整个产品（含 Web 配套视图）的设计基调。
- `apps/pa_agent/__main__.py` 入口 + `__init__.py` 说明；已登记进根 `pyproject.toml` 的 workspace members。
- 根 `.gitignore` 追加 PA_Agent 运行时（真实 `settings.json` / `logs/` / `records/` / `experience/` 等）。

### 2.3 启动方式（PA_Agent 桌面 = 旗舰前端）
```powershell
# 旗舰前端（PyQt6 桌面，需本地有显示环境 + Windows 推荐）
uv sync --extra pa-agent-desktop
uv run quanthub-desktop                    # 控制台入口，等价于 uv run python -m apps.pa_agent

# Web 配套视图（Streamlit 看板，浏览器可预览）
uv sync --extra dashboard
uv run streamlit run apps/dashboard/app.py
```
> 注：PyQt6 桌面应用无法在 headless 沙箱渲染；在本地 Windows（带显示器）环境运行旗舰前端。其视觉/交互设计已定为产品前端主基调。

### 2.4 后续 Phase（看板双轨 + 引擎统一）
- **P-A 看板增强**：把 PA_Agent 高价值视图移植进现有 Streamlit 看板（`apps/dashboard`）——
  K线图、决策树可视化、分析快照、案例库浏览器，补强 Web 展现（呼应「QuantHub 展现功能太少」）。
- **P-B 引擎统一（消除双引擎债）**：把 `apps/pa_agent/pa_agent/ai/` 分析引擎抽离为统一底座
  （`core/pa_engine/` 或归入 `strategies/ai_analysis/pa_agent/`），让**桌面应用**与**策略插件**
  共享同一引擎，移除现有 `strategies/ai_analysis/pa_agent/` 的轻量子集。

---

## 3. 团队技术能力提升方案

1. **工程规范文档**（`docs/STANDARDS.md`）：编码风格（ruff 已定）、模块边界（apps/core/strategies 单向依赖）、`Signal` 数据契约、配置 schema 约定。
2. **Code Review 流程与清单**：PR 必须过 pre-commit + CI； reviewer 按清单核对（接口契约、密钥、日志、异常、测试覆盖）。
3. **插件开发者 Onboarding**：以「实现 `StrategyBase` + `@register_strategy`」为模板，5 分钟挂一个新策略；配套最小可运行示例。
4. **架构决策记录 ADR**（`docs/adr/`）：重大取舍留痕（如本次「PA_Agent 双轨并入而非整包」的论证）。
5. **技术分享 + 结对**：双周 tech talk（复盘一次真实缺陷/性能优化）；新人首 PR 结对。

---

## 4. 代码质量把控体系（脚手架已搭，待激活）

| 层 | 资产 | 状态 | 激活条件 |
|---|---|---|---|
| 版本控制 | 需 `git init` + 接远程 + 分支模型（trunk-based：main 保护 + 短命 feature 分支） | ⬜ 待做 | 用户确认远程/分支策略后执行 |
| pre-commit | `.pre-commit-config.yaml`（ruff + 本地密钥拦截）→ `tools/block_secrets.sh` | ✅ 已写 | `git init` 后 `uv run pre-commit install` |
| CI | `.github/workflows/ci.yml`：ruff 检查 + ruff format + pytest+coverage + pa-agent 语法校验 | ✅ 已写 | 接 GitHub 远程后自动生效 |
| 类型检查 | 分阶段引入 `pyright`/`mypy`，先 `core/` 后 `strategies/` | ⬜ 规划 | 加入 `dev` 依赖与 CI job |
| 覆盖率门槛 | `core ≥ 80%`、`strategies ≥ 60%`，未达门槛 CI 失败 | ⬜ 规划 | 在 CI 加 `--cov-fail-under` |
| 密钥/合规 | `.gitignore` 已覆盖 `.env`/真实 settings/日志；pre-commit 拦截明文密钥 | ✅ | — |

> 上游自带的密钥拦截逻辑（挡 `api_key` / `sk-...` / `.env` / `logs/` / `records/`）已被强化并适配 QuantHub 路径，这是团队质量最直接的「现成资产」。

---

## 5. 落地执行清单（按优先级）

| # | 动作 | 命令 / 产物 | 优先级 |
|---|---|---|---|
| 1 | **git 初始化 + 接远程 + 首提交**（仅代码，.gitignore 已排除数据/vendored/zip） | `git init && git add -A && git commit` | 🔴 高 |
| 2 | 安装 pre-commit 钩子 | `uv sync --extra dev && uv run pre-commit install` | 🔴 高 |
| 3 | 推送并验证 CI 首次运行 | push 到 main / PR | 🔴 高 |
| 4 | 本地启动验证 PA_Agent 桌面应用 | `uv sync --extra pa-agent-desktop && uv run python apps/pa_agent/run.py` | 🟠 中 |
| 5 | 写 `docs/STANDARDS.md` + Code Review 清单 | 文档 | 🟠 中 |
| 6 | 引入类型检查（pyright）到 `core/` + CI job | 依赖 + CI | 🟡 低 |
| 7 | 覆盖率门槛接入 CI | `--cov-fail-under` | 🟡 低 |
| 8 | 看板增强 P-A：移植 K线/决策树/快照/案例库视图 | `apps/dashboard` | 🟡 低 |
| 9 | 引擎统一 P-B：抽离 `pa_agent/ai/` 为共享底座 | `core/pa_engine/` | 🟡 低 |
| 10 | vendored 正本刷新（受沙箱删除策略限制，本次未执行，建议手动 `cp -r` 或 Git 子树管理上游） | `vendored/agent/PA_Agent` | ⚪ 待定 |
| 11 | 指数数据修复 P-C（`tools/repair_indices_parquet.py --apply`，先自动备份） | 数据 | ⚪ 待定 |

---

## 6. 风险与注意

- **双引擎技术债**：当前 `strategies/ai_analysis/pa_agent`（轻量子集）与 `apps/pa_agent/pa_agent/ai/`（完整上游）并存；P-B 解决前，改引擎需两处同步。
- **PyQt / MT5 平台限制**：桌面应用仅能在有显示环境的桌面（Win / Linux-desktop）运行；`MetaTrader5` 仅 win32。CI 仅做语法/导入校验，不拉起 GUI。
- **外部连接器**：Cursor / QClaw / MIMO / 飞书 连接器代码已并入但默认不装依赖；启用需手动加依赖并自担合规。
- **数据质量 P-C**：指数 parquet 38.5 万损坏行未修复；执行 `--apply` 前需人工确认 drop vs 符号翻转。
- **vendored 正本**：本次因沙箱安全删除策略拦截 `rm -rf`，未刷新；旧副本仍可用作参考。

---

## 7. 本次验证记录

| 项 | 命令 | 结果 |
|---|---|---|
| workspace 解析 | `uv sync --extra dev` | 解析 192 包，构建 quanthub 成功 |
| 桌面应用语法 | `python -m compileall apps/pa_agent/pa_agent ...` | 142 模块编译通过 |
| 回归测试 | `uv run pytest tests/ -q` | 52/52 通过，0 失败 |
| 策略注册 | `strategies.discover_and_register()` | 11 策略正常加载（前置核查） |

# QuantHub

> 面向个人投资者与量化研究者的多市场量化研究、策略验证和模拟交易工作台。

QuantHub 将综合评估、因子验证、AI 研究证据、策略回测、信号审核、模拟交易、账户账本和运行治理整合到一个本地优先的 Web 应用中。项目采用 React + FastAPI，支持 A 股、美股、加密资产与 MT5 数据，并通过插件机制扩展策略。

![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=111827)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)
![Version](https://img.shields.io/badge/version-v0.3.0-4FB3C8)
![License](https://img.shields.io/badge/License-AGPL--3.0-blue)

![QuantHub 驾驶舱](design/screenshots/quanthub-overview.png)

> [!WARNING]
> QuantHub 当前定位为研究与模拟执行工具，实盘交易默认关闭。项目输出不构成任何投资建议；在接入真实账户前，请自行完成数据、策略、风控和合规验证。

## v0.3.0 更新

`v0.3.0` 将固定技术因子筛选器升级为可扩展、可审计的 AI 辅助因子发现系统。AI 只提交结构化经济假设、DSL 公式和证伪建议，数据检查、统计结论、生命周期与模拟交易门禁仍由确定性程序控制。

- **安全因子 DSL 与试验账本**：不可变因子注册表保存公式 AST、版本、公式族和哈希；禁止未来函数、非法单位、无限参数搜索和无记录重试。
- **真实 A 股研究基线**：仓库保留 300 个真实标的、516 个共同 ordinal session、14 个内置因子的可复现只读证据，以及 6 个预注册实验的成功和失败结果。
- **AI 研究治理**：候选收件箱区分人工、AI、模板、随机 DSL 和符号回归；AI 无权修改 `research_passed`、`trading_validated` 或统计结论，也不能读取锁定确认集标签。
- **证据工作台**：探索分数、研究状态、交易状态和 AI 审阅分开展示，可从假设追溯到 DSL、数据验证、实验、统计结果、组合决策和模拟运行。
- **模拟审计与持续降级**：逐笔记录信号时间、可成交时间、理论价格、模拟价格、滑点、拒单原因和容量占用；漂移门禁失败会追加 `degraded` 事件并定位受影响策略。
- **完整 provenance**：数据、公式、实验、模型、提示词、成本和结果分别保存版本与哈希；旧引擎研究记录保持只读并明确标记兼容口径。

完整变更、证据边界和升级说明见 [v0.3.0 发布说明](docs/releases/v0.3.0.md) 与 [AI 因子发现路线图](AI_FACTOR_DISCOVERY_ROADMAP.md)。

## 为什么使用 QuantHub

- **单一综合评估入口**：工作台支持一键启动量化快照、新闻 AI、价格结构 AI 和模型共识，并将结果写入同一份研究记录。
- **严格且可持续复验的因子验证**：使用训练、隔离和多窗口样本外区间评估 14 个趋势、反转、量价与风险因子；横截面研究按历史股票池、行业/市值/Beta 中性化与四市场门禁验证。结果自动保存、可回看、对比、导出、打标和归档，并提供状态矩阵和可展开证据。
- **多市场统一工作台**：统一管理 A 股、美股、加密资产和 MT5 数据及策略，美股历史行情支持 Yahoo 回退。
- **可配置 AI 能力**：在系统设置中切换 DeepSeek、OpenAI 或兼容 API，配置模型并执行连接测试。
- **AI 输出质量闸门**：PA 两阶段结果经过结构、概率、终局、交易几何与 K 线引用范围校验，可修复错误只重试一次，未通过时禁止发布信号。
- **插件式策略系统**：策略独立注册，共享行情、信号、回测、LLM 与告警能力。
- **审核优先的执行链路**：信号先进入审核中心，再进入模拟订单与账户账本。
- **闭合交易质量分析**：账户账本使用 FIFO 配对计算真实胜率、利润因子、盈亏比、持仓时长、多空差异和费用侵蚀。
- **本地优先与安全默认值**：默认使用本地 SQLite，密钥只从环境变量读取，实盘开关默认关闭。
- **完整运营视角**：提供自动化任务、故障状态、备份、访问治理和运行健康检查。
- **统一结果回链**：研究任务、作业调度、提醒、信号与全局检索共享同一结果定位规则，最多一次点击返回研究正文；自动化页面只保存产出类型和记录 ID，不复制研究内容。
- **隐私友好的易用性指标**：仅在本机记录研究步骤、完成耗时、放弃步骤与错误分类，不采集标的、密钥、持仓明细或模型配置。
- **新手 / 高级界面模式**：新手模式聚焦综合评估与模拟交易，高级模式开放完整研究、策略、执行和运营工作区。

## 功能概览

| 工作区 | 主要能力 |
| --- | --- |
| 驾驶舱 | 账户净值、持仓、自选、行情状态、行动队列与 PA 决策摘要 |
| 研究 | 综合评估、因子验证与研究任务；新闻 AI、价格结构 AI 和模型共识作为综合评估内部模块 |
| 策略 | 已安装策略运行、可复现策略实验与策略组合 |
| 执行 | 信号审核、模拟交易、账户账本与价格提醒 |
| 运营 | 标的与数据、作业调度、运行故障、成员权限、备份与系统设置 |

内置策略覆盖情绪分析、新闻扫描、选股、SuperTrend、早报、实时分析、OKX 网格、AlphaGPT、PA Agent 和 AlphaMaster 等方向。

`v0.3.0` 加入安全 DSL、全局试验账本、AI 候选治理、真实 A 股横截面证据、预注册实验队列、因子证据工作台、逐笔模拟审计和自动漂移降级。完整说明见 [v0.3.0 发布说明](docs/releases/v0.3.0.md)，研究实施状态见 [AI 因子发现路线图](AI_FACTOR_DISCOVERY_ROADMAP.md)，成本来源边界见 [交易成本来源](docs/TRADING_COST_SOURCES.md)，长期职责边界见 [功能边界](docs/FUNCTION_BOUNDARIES.md)。

## 技术栈

- 前端：React 18、TypeScript、Vite、React Router、Vitest
- 后端：FastAPI、Pydantic、SQLAlchemy、Alembic
- 数据：Pandas、NumPy、PyArrow、SQLite / PostgreSQL
- 工程：uv workspace、插件式策略、领域化 API、PowerShell 启停脚本

## 快速开始

### 环境要求

- Python 3.11 或 3.12
- Node.js 18+
- [uv](https://docs.astral.sh/uv/)
- Windows 一键启动需要 PowerShell

### 1. 获取项目

```bash
git clone https://github.com/1634594707/QuantHub.git
cd QuantHub
```

### 2. Windows 一键启动

启动脚本会检查运行环境、同步依赖、检查端口与 API 健康状态，并将日志写入 `logs/launcher/`。

```powershell
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1
```

启动完成后访问：

- Web 工作台：<http://127.0.0.1:5173>
- API 文档：<http://127.0.0.1:8001/docs>
- 健康检查：<http://127.0.0.1:8001/health>

停止由脚本启动的服务：

```powershell
powershell -ExecutionPolicy Bypass -File tools/stop-quanthub.ps1
```

已完成依赖安装时，可使用 `-SkipSync` 加快启动：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync
```

### 3. 手动启动

安装基础依赖：

```bash
uv sync --locked
npm --prefix web install
```

启动 API：

```bash
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8001
```

另开一个终端启动前端：

```bash
npm --prefix web run dev
```

Vite 会将 `/api` 请求代理到 `http://127.0.0.1:8001`。

### 4. Docker 镜像

正式版本会发布到 GitHub Container Registry。镜像在同一端口提供 Web 工作台和 API，并将 SQLite 数据持久化到 `/data`：

```bash
docker run --name quanthub -p 8080:8080 -v quanthub-data:/data ghcr.io/1634594707/quanthub:latest
```

启动后访问 <http://127.0.0.1:8080>，健康检查位于 <http://127.0.0.1:8080/health>。

## 可选能力

基础安装足以启动 Web 工作台。需要特定市场或分析能力时，再安装对应 extra：

```bash
# A 股数据与中文情绪分析
uv sync --locked --extra a_shares

# 加密资产数据源
uv sync --locked --extra crypto

# OpenAI 兼容 LLM 能力
uv sync --locked --extra ai

# Backtrader 回测引擎
uv sync --locked --extra backtest
```

多个能力可以在同一条命令中组合，例如：

```bash
uv sync --locked --extra a_shares --extra ai --extra backtest
```

## 配置

### 本地环境变量

基础量化与因子验证无需 API Key。若要启用 AI 研究证据，可直接在“系统设置 → 模型供应商”中配置 DeepSeek、OpenAI 或 OpenAI 兼容服务，也可以复制环境变量模板：

```powershell
Copy-Item apps/api/.env.example apps/api/.env
```

```dotenv
DEEPSEEK_API_KEY=your-key-here
# 或
OPENAI_API_KEY=your-key-here
# 或
QUANTHUB_CUSTOM_LLM_API_KEY=your-key-here
```

界面支持配置 API 地址、默认模型、超时、重试次数和连接测试。密钥仅写入运行时环境，不会回显明文；`apps/api/.env` 已被 Git 忽略。请勿将 API Key、数据库密码、交易所密钥或访问令牌提交到仓库。

### 主要配置文件

| 文件 | 用途 |
| --- | --- |
| `configs/base.yaml` | 全局开关、缓存、信号权重、告警、LLM 与回测配置 |
| `configs/a_shares.yaml` | A 股数据源与策略配置 |
| `configs/us_stocks.yaml` | 美股腾讯、Yahoo 与本地 Parquet 数据源顺序 |
| `configs/crypto.yaml` | 加密资产数据源与策略配置 |
| `configs/mt5.yaml` | MT5 数据与 AlphaMaster 配置 |
| `configs/ai_analysis.yaml` | PA Agent 分析配置 |
| `configs/portfolio.yaml` | 组合与账户配置 |

QuantHub 支持 `local`、`lan` 和 `postgresql` 三种部署模式。局域网与 PostgreSQL 部署必须显式配置 CORS、认证令牌和数据库连接，详情见 [部署与数据库迁移](docs/DEPLOYMENT.md)。

## 数据目录

| 目录 | 内容 |
| --- | --- |
| `data/parquet/` | A 股及通用 Parquet 行情 |
| `data/OKX_K线数据/` | OKX K 线数据 |
| `data/MT5_K线数据/` | MT5 K 线数据 |
| `apps/api/store.db` | 默认本地业务数据库，首次运行时创建 |

大型行情、模型、日志、数据库和本地密钥默认不会提交到 Git。克隆后的新环境需要自行准备真实行情数据，或者使用应用内可用的数据源与示例流程。

## 项目结构

```text
apps/
  api/          FastAPI 网关与领域 API
  dispatcher/   信号聚合、风控与订单路由
  scheduler/    自动化任务定义
core/           配置、行情、信号、回测、告警和 LLM 公共能力
strategies/     A 股、加密、AI 分析与 MT5 策略插件
web/            React + Vite Web 客户端
configs/        市场、组合与部署配置
data/           本地行情与运行时数据
docs/           架构、部署、质量和运维文档
tools/          启停、备份、迁移、恢复与策略脚手架
tests/          后端产品流程测试
```

## 开发与验证

安装开发工具并启用 Git 提交检查：

```bash
uv sync --locked --extra dev
uv run pre-commit install
```

运行后端测试：

```bash
uv sync --locked --group test
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

运行前端测试、类型检查和生产构建：

```bash
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

创建新策略前可以先用 `--dry-run` 预览变更：

```bash
uv run python tools/scaffold_strategy.py \
  --name my_alpha \
  --market a_shares \
  --desc "示例 Alpha 策略" \
  --dry-run
```

支持的市场值为 `a_shares`、`crypto`、`mt5` 和 `ai_analysis`。策略规范与数据流说明见 [架构文档](docs/ARCHITECTURE.md)。

## 安全边界

- `configs/base.yaml` 中的 `live_trading` 默认为 `false`。
- 真实执行需要同时满足全局开关、模块开关、凭据和人工确认条件。
- 当前项目重点是研究、回测和模拟执行；接入真实券商或交易所前请阅读 [实盘适配评估](docs/LIVE_TRADING_ADAPTER_EVALUATION.md)。
- 公开仓库前建议执行 `git status --short`，确认 `.env`、数据库、日志、模型和大型行情文件均未进入暂存区。

## 文档

- [文档索引](docs/README.md)
- [v0.3.0 发布说明](docs/releases/v0.3.0.md)
- [AI 因子发现路线图](AI_FACTOR_DISCOVERY_ROADMAP.md)
- [v0.2.0 发布说明](docs/releases/v0.2.0.md)
- [v0.2.0 社区更新帖子](docs/posts/2026-07-31-quanthub-v0.2.0.md)
- [架构设计](docs/ARCHITECTURE.md)
- [功能边界](docs/FUNCTION_BOUNDARIES.md)
- [研究工作流与因子验证更新](docs/posts/2026-07-30-research-factor-update.md)
- [部署与数据库迁移](docs/DEPLOYMENT.md)
- [质量门禁](docs/QUALITY_GATES.md)
- [升级与扩展](docs/UPGRADE.md)
- [数据质量](docs/DATA_QUALITY.md)

## 参与贡献

欢迎通过 Issue 提交问题、功能建议和数据源适配需求。提交 Pull Request 前，请至少运行与改动相关的后端测试、前端测试、类型检查和生产构建。

## License

本项目采用 AGPL-3.0-or-later。`strategies/mt5/alphamaster/_upstream` 中的上游组件保留其原始许可证与版权声明。

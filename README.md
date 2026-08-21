# QuantHub

> 面向个人投资者与量化研究者的多市场量化研究、策略验证和模拟交易工作台。

QuantHub 将综合评估、因子验证、AI 研究证据、策略回测、信号审核、模拟交易、账户账本和运行治理整合到一个本地优先的 Web 应用中。项目采用 React + FastAPI，支持 A 股、美股、加密资产与 MT5 数据，并通过插件机制扩展策略。

![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=111827)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)
![Version](https://img.shields.io/badge/version-v0.4.0-4FB3C8)
![License](https://img.shields.io/badge/License-AGPL--3.0-blue)

![QuantHub 因子研究工作台](design/screenshots/quanthub-factor-research.png)

> [!WARNING]
> QuantHub 当前定位为研究与模拟执行工具，实盘交易默认关闭。项目输出不构成任何投资建议；在接入真实账户前，请自行完成数据、策略、风控和合规验证。

> [!IMPORTANT]
> 当前版本适合本地单用户研究和模拟执行。多用户部署的持仓、信号、模拟订单、账本和全局搜索隔离仍在整改，生产多用户使用前请阅读[用户体验、分类与分析报告改进需求](docs/PRODUCT_USABILITY_AND_REPORT_REQUIREMENTS.md)中的 P0 数据隔离要求。

## 当前版本内容

当前版本基于 `v0.4.0`，产品入口统一为 `http://127.0.0.1:5173`，并按总览、研究、策略、交易、风控和设置组织功能。工作台后端已定义股票投资、主动交易、量化研究、运营管理和自定义五类画像；前端仍保留 `beginner/advanced` 兼容模式，画像与导航配置正在向账户级统一收口。

### Factor Factory：从候选生成到 7 天模拟门禁

- **研究目标绑定**：每次实验固定 `market + symbol + interval`；候选列表、详情和下一轮选择只显示当前研究标的的数据，切换标的会清空上一标的的候选视图。
- **可重复实验**：同一标的可通过新的 `experiment_nonce` 重复运行，不再被“每个标的只能实验一次”限制；每次运行仍保留独立记录以便审计。
- **多来源候选**：支持 BRAIN 风格规则挖掘、人工 JSON 批次、固定候选库和 AI 提案。AI 提案可在界面选择已配置的 DeepSeek 或兼容 API，AI 只负责提交假设与表达式，不负责修改统计结论。
- **候选可解释**：列表和详情检查器展示完整 DSL、因子家族、来源、阶段、样本覆盖、门禁结果和淘汰原因；只有存在足够真实观察时才绘制前向净值曲线，不使用占位曲线冒充结果。
- **安全 DSL 与相似性预检**：表达式先经过 AST 白名单、未来数据和参数边界检查，再按公式哈希删除完全重复项，并依据实际信号相关性过滤冗余候选；跨家族高相关阈值为 `0.985`。
- **确定性筛选**：统一执行滚动样本外验证、回撤与交易次数门禁，以及双倍成本压力测试。只有排名最高且全部通过的一个候选可以进入锁定确认集。
- **真实时间观察**：优胜因子进入 OKX Demo 或本地独立模拟后，必须累计至少 7 个真实自然日并满足收益、夏普、成交率、容量、风险与对账门禁；7 天阶段是单个优胜者的最终通过/失败验证，不是多个候选并行竞赛。

### 真实行情、连接与安全默认值

- **可用历史优先**：OKX 返回的历史 K 线少于请求值时，只要仍有至少 `240` 根有效 K 线就继续研究，并在界面同时显示请求样本和实际样本；数据不足或行情不可用会返回可解释的 `422`，而不是笼统的 `500`。
- **真实 OKX 数据**：系统可读取 OKX 公共合约目录和实时公共 K 线；当前只读 Demo 凭据验证已成功，连接测试能够返回账户币种信息。
- **本地凭据保护**：Windows 本地凭据由当前 Windows 用户的 DPAPI 加密保存在仓库之外，设置页只显示状态和指纹，不回显 Key、Secret 或 Passphrase。API 运行账户变化导致旧凭据不可解密时，状态接口会返回可诊断、可重建的恢复信息，不再以原始 `503` 阻断设置页。
- **执行默认关闭**：Web 只访问统一 API，API 再代理无界面的 OKX Runner。研究模式可通过 `-SkipRunner` 保持 Runner 关闭；启动 Runner 时默认仍为 `shadow` 只读模式，不会因为 Demo 失败而回退到实盘。
- **无静默假数据**：前端不会在首次访问时自动写入演示持仓或自选数据，真实数据失败会明确显示错误；假数据和产品凭据扫描覆盖 Python、TypeScript、JSON 与 YAML。

### 当前能力边界

- Factor Factory 的人工与 AI DSL 当前面向**单标的 OHLCV 时序数据**。类似 WorldQuant 的财务字段、情绪字段、`subindustry` 分组排名和大规模横截面运算，需要后续接入稳定的截面数据层后才能可靠支持。
- 当前相似性筛选使用公式结构和同一研究目标上的实际信号相关性，避免近似表达式重复进入下一轮；它不宣称跨市场、跨频率的两个因子天然等价。
- 模拟账户的 7 天结果仅用于研究验收，不构成实盘授权。实盘交易仍需独立配置、人工批准和更长观察期。

`v0.3.0` 同时保留安全因子 DSL、不可变试验账本、真实 A 股横截面研究基线、AI 候选治理、逐笔模拟审计、漂移降级和完整 provenance。完整变更与证据边界见 [v0.3.0 发布说明](docs/releases/v0.3.0.md)、[AI 因子发现路线图](AI_FACTOR_DISCOVERY_ROADMAP.md)、[Web 工作台与 OKX 路线图](docs/Plan/2026-08-09-Web工作台收口与OKX实盘路线图.md) 和 [交易安全边界](docs/TRADING_SAFETY.md)。

## 为什么使用 QuantHub

- **单一综合评估入口**：工作台支持一键启动量化快照、新闻 AI、价格结构 AI 和模型共识，并将结果写入同一份研究记录。
- **严格且可持续复验的因子验证**：使用训练、隔离和多窗口样本外区间评估 14 个趋势、反转、量价与风险因子；横截面研究按历史股票池、行业/市值/Beta 中性化与四市场门禁验证。结果自动保存、可回看、对比、导出、打标和归档，并提供状态矩阵和可展开证据。
- **多市场统一工作台**：统一管理 A 股、美股、加密资产和 MT5 数据及策略，美股历史行情支持 Yahoo 回退。
- **可配置 AI 能力**：在系统设置中切换 DeepSeek、OpenAI 或兼容 API，配置模型并执行连接测试。
- **AI 输出质量闸门**：PA 两阶段结果经过结构、概率、终局、交易几何与 K 线引用范围校验，可修复错误只重试一次，未通过时禁止发布信号。
- **插件式策略系统**：策略独立注册，共享行情、信号、回测、LLM 与告警能力。
- **审核优先的执行链路**：信号先进入审核中心，再进入模拟订单与账户账本。
- **闭合交易质量分析**：账户账本使用 FIFO 配对计算真实胜率、利润因子、盈亏比、持仓时长、多空差异和费用侵蚀。
- **本地优先与安全默认值**：默认使用本地 SQLite；LLM 密钥沿用运行时配置，OKX 桌面端凭据使用 Windows DPAPI 加密保存且不回显原文；实盘开关默认关闭。
- **完整运营视角**：提供自动化任务、故障状态、备份、访问治理和运行健康检查。
- **结果回链**：研究任务、作业调度、提醒、信号和账本提供来源定位；正式报告、任务、提醒、故障和全局搜索的统一回链仍按需求文档继续收口。
- **隐私友好的易用性指标**：仅在本机记录研究步骤、完成耗时、放弃步骤与错误分类，不采集标的、密钥、持仓明细或模型配置。
- **工作台画像**：五类账户画像决定默认工作区和入口；`beginner/advanced` 仅作为现有前端兼容模式保留。

## 功能概览

| 工作区 | 主要能力 |
| --- | --- |
| 驾驶舱 | 账户净值、持仓、自选、行情状态、行动队列与 PA 决策摘要 |
| 研究 | 综合评估、因子验证与研究任务；新闻 AI、价格结构 AI 和模型共识作为综合评估内部模块 |
| 策略 | 已安装策略运行、可复现策略实验与策略组合 |
| 执行 | 信号审核、模拟交易、账户账本与价格提醒 |
| 运营 | 标的与数据、作业调度、运行故障、成员权限、备份与系统设置 |

内置策略覆盖情绪分析、新闻扫描、选股、SuperTrend、早报、实时分析、OKX 网格、AlphaGPT、PA Agent 和 AlphaMaster 等方向。

### 当前明确边界

- 股票研究能力按市场区分：A 股已接入财报、估值、公告和宏观模块；美股当前不启动公司事件和宏观模块；加密资产当前使用行情、价格结构和模型共识，财报与估值不适用。
- 研究报告当前同时存在结构化研究运行结果和报告流结果；正式报告的异步生成、SSE 续传、停止、单章重试和最终快照门禁仍在建设。
- 总览账户口径、自选与持仓离线缓存、历史研究结果复用和状态后的下一步动作仍需按[用户体验、分类与分析报告改进需求](docs/PRODUCT_USABILITY_AND_REPORT_REQUIREMENTS.md)执行整改。

`v0.4.0` 在 `v0.3.0` 研究治理基础上加入单一 Web 工作台、目标绑定的 Factor Factory、候选表达式检查器、相似性预检、7 天 Demo 门禁、AI 提案模型选择和真实 OKX 行情接入。完整说明见 [v0.4.0 发布说明](docs/releases/v0.4.0.md)，研究实施状态见 [AI 因子发现路线图](AI_FACTOR_DISCOVERY_ROADMAP.md)，成本来源边界见 [交易成本来源](docs/TRADING_COST_SOURCES.md)，长期职责边界见 [功能边界](docs/FUNCTION_BOUNDARIES.md)。

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

### 2. Windows 一键启动（推荐）

启动脚本会检查运行环境、同步依赖、检查端口与 API 健康状态，并将日志写入
`logs/launcher/`。一条命令同时启动三个进程：Web 工作台、统一 API、无 UI 的
OKX Runner。

首次启动，或依赖发生变化时，运行：

```powershell
# 安全默认值：Runner 使用 shadow 只读模式，不会下单
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1
```

依赖已经安装完成时，日常开发可加 `-SkipSync` 加快启动：

```powershell
# 只读研究和交易状态查看
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync

# OKX 模拟盘联调：启动 Web、API 和 Demo Runner
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync -Demo

# 仅启动 Web 和 API，不启动 Runner
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync -SkipRunner
```

启动完成后访问：

- Web 工作台：<http://127.0.0.1:5173>（唯一用户入口）
- API 文档：<http://127.0.0.1:8001/docs>
- 健康检查：<http://127.0.0.1:8001/health>

OKX Runner 监听 `127.0.0.1:8103`，**不对浏览器开放**，也没有独立界面；
Web 只经统一 API 的 `/api/trading/*` 访问它。Runner 默认以 `shadow`（只读、不下单）
环境启动；需要模拟交易、OKX 预检和账户同步时使用 `-Demo`。首次使用 Demo 前，
在“系统设置 -> OKX 连接”中保存模拟盘专用 API Key、Secret Key 和 Passphrase。
实盘另需 `QH_RUNNER_LIVE_APPROVED=1`，启动脚本不会代为开启。

切换 `shadow`、`Demo` 或 `-SkipRunner` 模式前，先停止现有进程；否则启动器会复用
端口上已经运行的旧进程，其环境不会随新命令改变：

```powershell
powershell -ExecutionPolicy Bypass -File tools/stop-quanthub.ps1
```

### 3. 手动启动

安装基础依赖：

```bash
uv sync --locked
npm --prefix web install
```

分别打开三个终端。终端 1 启动 API：

```bash
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8001
```

终端 2 启动前端：

```bash
npm --prefix web run dev
```

终端 3 启动默认的只读 OKX Runner：

```bash
uv run uvicorn apps.okx_runner.main:app --host 127.0.0.1 --port 8103
```

Vite 会将 `/api` 请求代理到 `http://127.0.0.1:8001`，统一 API 再访问
`http://127.0.0.1:8103` 上的 Runner。只启动前两个进程时，研究页面仍可使用，
但交易工作台会显示 `TRADING_RUNNER_UNAVAILABLE`。Demo 模式需要 API 与 Runner
共享认证配置，推荐直接使用上一节的 `start-quanthub.ps1 -Demo`，避免手动配置不一致。

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

### OKX 本地凭据

打开“系统设置 → OKX 连接”，依次填写 API Key、Secret Key 和 API Passphrase，然后先执行只读连接测试。这里的 API Passphrase 是创建这把 API Key 时单独设置的口令，不是 OKX 登录密码或查看 API 列表时使用的验证密码。

首次联调建议只授予“读取”权限，并在 OKX 的“模拟交易”环境中创建专用 Key。若测试返回 `50101`，表示 OKX 判定该 Key 与当前请求环境不一致；请在模拟交易环境重新创建 Key，而不是开启实盘回退。凭据加密文件保存在 `%LOCALAPPDATA%\QuantHub\secrets\`，位于仓库和业务数据库之外，状态接口只返回指纹和时间，不返回密钥原文。

Runner 的安全默认值如下：

- `QH_RUNNER_ENVIRONMENT=shadow`：只读影子模式，不下单。
- `QH_RUNNER_ENVIRONMENT=demo`：显式连接 OKX 模拟交易环境。
- 实盘还必须额外设置 `QH_RUNNER_LIVE_APPROVED=1`，且应在完成 Demo 观察期和人工验收后才启用。

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
  okx_runner/   无独立 UI 的 OKX 执行、风控与对账服务
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
uv run --frozen python -B tools/run_backend_tests.py
```

运行前端测试、类型检查和生产构建：

```bash
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

运行数据与凭据门禁：

```bash
uv run --frozen python -B tools/check_fake_data.py
uv run --frozen python -B tools/check_product_secrets.py --product okx-runner
```

验证命令、测试范围和历史浏览器证据见 `docs/README.md`、`docs/QUALITY_GATES.md` 与 `docs/Plan/evidence/`；固定数量只以当前提交对应的测试输出为准，不在 README 中使用过期统计。

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
- OKX Runner 默认使用 `shadow`；真实执行需要同时满足环境、全局开关、模块开关、有效凭据和人工批准条件。
- Demo 凭据与实盘凭据不混用，连接失败时不会自动尝试另一环境。
- 当前项目重点是研究、回测和模拟执行；接入真实券商或交易所前请阅读 [实盘适配评估](docs/LIVE_TRADING_ADAPTER_EVALUATION.md)。
- 公开仓库前建议执行 `git status --short`，确认 `.env`、数据库、日志、模型和大型行情文件均未进入暂存区。

## 文档

- [文档索引](docs/README.md)
- [用户体验、分类与分析报告改进需求](docs/PRODUCT_USABILITY_AND_REPORT_REQUIREMENTS.md)
- [历史归档说明](docs/archive/README.md)
- [视频与宣传素材](docs/media/)
- [v0.4.0 发布说明](docs/releases/v0.4.0.md)
- [v0.3.0 发布说明](docs/releases/v0.3.0.md)
- [AI 因子发现路线图](AI_FACTOR_DISCOVERY_ROADMAP.md)
- [v0.2.0 发布说明](docs/releases/v0.2.0.md)
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

# QuantHub 用户功能路线图

> 复核日期：2026-07-27
>
> 目标：从高频使用者的日常路径出发，减少研究、审核、模拟执行、对账和故障恢复之间的切换成本。
>
> 状态规则：`[x]` 表示源码、页面和测试已经形成可用闭环；`[ ]` 表示用户侧闭环仍未完成。接口存在但页面未接入、页面存在但关键动作仍需手工绕行时，统一保持 `[ ]`。
>
> 证据边界：结论只来自当前仓库源码、测试、配置和 2026-07-27 的只读运行态检查。真实交易继续排除在当前交付范围之外；`GET /health` 返回 `live_trading=false`。

## 已确认可用的功能板块

- [x] 研究、信号、模拟执行和账本已经形成可追溯闭环。
  - 信号支持 `new`、`accepted`、`rejected`、`expired`、`converted` 状态，接受后可创建模拟订单。
  - 模拟成交自动同步 `ledger_trades`，同步结果保存 `ledger_sync_status`、`ledger_trade_id` 和 `ledger_sync_error`，失败后可重试。
  - 浏览器闭环由 `web/e2e/closed-loop.spec.ts` 覆盖。
- [x] 自动化中心已经具备启停、Cron 编辑、立即运行、历史、日志、重试、告警确认和域内审计。
  - 依据：`apps/api/domains/automation/`、`web/src/pages/AutomationPage.tsx`。
- [x] 数据库备份已经具备创建、验证、恢复前安全备份和保留策略确认删除。
  - 依据：`apps/api/domains/backups/`、`web/src/pages/ConfigPage.tsx`。
- [x] 故障状态中心已经聚合分析任务、自动化、账本同步和数据源异常。
  - 依据：`apps/api/domains/incidents/service.py`、`web/src/pages/IncidentsPage.tsx`。
- [x] 账户与账本已经提供持仓、成交、现金、组合汇总、绩效、敞口和基准数据。
  - 精确接口：`/ledger/positions`、`/ledger/trades`、`/ledger/cash`、`/ledger/summary`、`/ledger/performance`、`/ledger/exposures`、`/ledger/benchmarks`。
- [x] 策略实验室已经支持策略定义、版本、实验、回测运行、数据快照、随机种子和多运行指标对比。
  - 依据：`apps/api/domains/strategy_lab/`、`web/src/pages/StrategyLabPage.tsx`、`tests/test_strategy_lab_domain.py`。
- [x] 系统配置页已经聚合网关、模型密钥、通知、调度器、数据库备份和数据源状态。
  - 精确接口：`/health`、`/config/status`。

## P0：先消除每天都会遇到的操作阻力

### 信号审核工作台

- [x] 把信号中心改为审核队列、当前信号详情和执行影响三部分组成的连续审核工作台。
  - 实现：`web/src/pages/SignalsPage.tsx` 与 `web/src/pages/SignalsPage.module.css` 使用三栏审核台；移动端改为记录队列与顺序展开的审核、执行区域。
  - 验收：选择下一条信号时保留筛选条件、列表滚动位置和其他信号尚未提交的审核备注。
  - 验收：详情区直接展示 `meta.research_run_id` 对应的研究证据、有效期、审核记录、关联模拟订单和账本结果。
- [x] 增加仅显示待审核信号的稳定队列视图和连续键盘操作。
  - 验收：完成接受或拒绝后自动进入下一条 `new` 信号，不需要重新展开表格行。
- [x] 在转模拟订单前展示数量、当前持仓、账户敞口和规则校验结果。
  - 实现：`POST /simulation/orders/preview` 使用当前模拟账户、最新价格和市场风险配置计算预计持仓、现金、总敞口及逐条校验结果；行情不可用时明确返回 `unavailable`，不填造价格。
  - 验证：`tests/test_simulation_preview.py`、`web/src/pages/SignalsPage.test.tsx`、`web/e2e/closed-loop.spec.ts`。

### 全局检索与快捷操作

- [x] 把命令面板从固定路由过滤器升级为业务数据检索入口。
  - 实现：`web/src/components/CommandPalette/CommandPalette.tsx` 并行读取业务数据并按快捷操作、页面、标的、策略定义、策略实验、研究运行、信号和模拟订单分组。
  - 检索范围：标的、策略定义、策略实验、研究运行、信号和模拟订单。
  - 现有精确入口包括 `/instruments/search`、`/strategy-lab/definitions`、`/strategy-lab/experiments`、`/research/runs`、`/signals` 和 `/simulation/orders`。
- [x] 在检索结果中提供打开记录、新建研究、创建实验和进入待审核信号的直接动作。
  - 精确记录状态：`run_id`、`definition_id`、`experiment_id`、`signal_id`、`order_id`、`status`、`action`。
- [x] 为全局检索补充键盘导航、加载、空结果、接口失败和结果分组测试。
  - 验证：`web/src/components/CommandPalette/CommandPalette.test.tsx`、`web/e2e/command-palette.spec.ts`。

### 页面状态与请求反馈

- [x] 将高频页面的筛选、当前记录和工作视图写入 URL。
  - 信号：`q`、`direction`、`market`、`source`、`status`、`signal_id`。
  - 模拟订单：`q`、`status`、`order_id`。
  - 标的研究：`market`、`tf`、`view`、`run_id`、`favorite`、`compare_run_id`。
  - 策略实验室：`definition_id`、`experiment_id`、`action`。
- [x] 统一页面请求的首次加载、保留旧数据更新、确定失败和成功空数据反馈。
  - 实现：`web/src/components/ui/AsyncStateBoundary/AsyncStateBoundary.tsx`；`web/src/api/useApi.ts` 通过 `resetKey` 防止跨标的或跨记录显示上一上下文。
  - 验证：`web/src/components/ui/AsyncStateBoundary/AsyncStateBoundary.test.tsx`、`web/src/api/useApi.test.tsx`。
- [x] 全局检索使用 `Ctrl/Cmd+Shift+K`，对话框内支持正反向焦点循环，关闭后焦点返回触发按钮。
  - 验证：`web/src/components/CommandPalette/CommandPalette.test.tsx`、`web/e2e/command-palette.spec.ts`。

### 账户与账本

- [x] 重排账本首屏，默认先展示账户变化、持仓和最近流水，成交、现金和基准录入按需展开。
  - 实现：`web/src/pages/LedgerPage.tsx` 首屏依次展示账户汇总、绩效摘要和合并后的最近流水；成交与现金通过“录入流水”按需展开，账本明细默认进入持仓视图。
- [x] 用受控表单替代基准的“权益曲线 JSON”和“指标 JSON”手工输入。
  - 实现：基准权益曲线使用“时间/权益”动态行，指标使用“名称/值”动态行；提交时由页面构造 `equity_curve` 和 `metrics`，不再要求用户编写 JSON。
- [x] 增加成交、现金流水和基准的更正流程，并保留更正原因和前后值。
  - 实现：`PATCH /ledger/trades/{trade_id}`、`PATCH /ledger/cash/{entry_id}` 和 `PATCH /ledger/benchmarks/{benchmark_id}` 要求填写 `reason`，前后值写入 `ledger_corrections`；`GET /ledger/corrections` 提供更正历史。
  - 前端：`web/src/pages/LedgerPage.tsx` 支持从现有记录进入更正表单并展示更正原因和历史。
- [x] 从持仓和绩效指标下钻到组成成交、现金流水和关联研究记录。
  - 实现：持仓行可按 `instrument_id` 打开组成成交，并进入对应标的研究历史；绩效区可直接切换到成交和现金流水。

### 数据源故障恢复

- [x] 让数据源异常可以在故障状态中心直接执行自检、重试和恢复确认。
  - 实现：故障页直接调用 `POST /incidents/data-sources/check` 重新检查，并通过 `POST /incidents/data-sources/{incident_id}/acknowledge` 保存恢复处理结果。
- [x] 在数据源状态中展示最近一次成功时间、最近一次错误、调用次数和错误率，并支持按数据源重新检查。
  - 实现：`web/src/pages/ConfigPage.tsx` 展示 `calls`、`error_rate`、`last_success_at` 和 `last_error`；单源检查使用 `POST /market-data/check` 的 `market`、`source`、`operation`、`symbol` 和 `interval` 请求契约。
  - 验证：`tests/test_market_data_status.py`。
- [x] 数据源恢复后保留故障开始、恢复时间和处理结果，避免记录直接消失。
  - 实现：`data_source_incidents` 持久化 `started_at`、`recovered_at`、`acknowledged_at`、`resolution` 和最近检查结果；`GET /incidents/data-sources/history` 返回历史记录。

### 移动端高频操作

- [x] 将信号、分析任务、模拟订单、账本成交和现金流水改为移动端记录模式。
  - 实现：信号审核使用移动记录队列；分析任务和模拟订单通过响应式详情展开；账本持仓、成交和现金在窄屏使用 `<details>` 记录。
  - 验收：每条记录先显示主次两行摘要，展开后完成审核、重试、成交和查看关联记录，不依赖横向滚动。
- [x] 为上述页面补充 `390x844` 视口的核心操作测试，不只检查页面无整体溢出。
  - 验证：`web/e2e/mobile-core-flows.spec.ts` 覆盖信号筛选、备注、接受、拒绝与自动前进，模拟成交与账本同步重试，以及分析任务、账本成交和现金记录展开。

## P1：提高研究与策略工作的复用效率

### 策略工作区

- [x] 将策略库从卡片网格改为可扫描列表，同时保留快速运行、回测和详情入口。
  - 实现：`web/src/pages/StrategiesPage.tsx` 提供市场、实盘能力、关键词和排序控制；扫描行保留运行、回测和打开详情操作。
- [x] 在策略详情建立固定运行栏，使参数、运行、停止状态和最近结果在切换内容区时保持可见。
  - 实现：`web/src/pages/StrategyDetailPage.tsx` 的 `operationBar` 固定展示状态、参数摘要、最近结果、运行和回测入口。
- [x] 将策略实验室重排为定义与版本、实验、运行与对比三部分，减少创建和比较时的纵向跳转。
  - 实现：`web/src/pages/StrategyLabPage.tsx` 使用“01 定义与版本”“02 实验”“03 运行与比较”三段工作流。
- [x] 用策略参数结构生成表单，替代策略版本和实验的参数 JSON 文本框。
  - 实现：策略详情和策略实验室使用 `StructuredParamsEditor`；版本与实验提交直接使用受控参数对象。
- [x] 增加策略定义、版本和实验的编辑、复制与归档生命周期。
  - 实现：`apps/api/domains/strategy_lab/router.py` 提供定义、版本和实验的编辑、复制与归档接口；`web/src/pages/StrategyLabPage.tsx` 接入完整操作和归档确认。
- [x] 增加数据快照差异视图，明确展示两次回测使用的数据、参数、代码哈希和指标差异。
  - 实现：`GET /strategy-lab/compare` 返回 `data_snapshot`、`params`、`code_hash` 和 `metrics` 的结构化差异，策略实验室直接展示前后值。

### Instrument 主数据统一

- [x] 让关注列表、研究持仓、研究运行、信号、策略实验、模拟订单和账本统一保存并关联 Instrument ID。
  - 实现：相关业务表均保存 `instrument_id`，领域服务使用 Instrument 主数据解析结果写入关联值。
- [x] 在写入业务记录时完成精确标的解析，无法解析时向用户显示错误并阻止生成孤立记录。
  - 实现：写入入口调用 `apps/api/domains/instrument/service.py` 的严格解析流程；解析失败返回明确错误，不持久化业务记录。
- [x] 增加主数据合并与引用迁移工具，处理同一标的已有的分散记录。
  - 实现：`tools/migrate_instrument_references.py` 提供只读审计和显式 `--apply` 迁移，覆盖关注列表、研究持仓、研究运行、信号、策略实验和模拟订单引用。

### 绩效归因与决策复盘

- [x] 在现有 TWR、最大回撤、基准超额和敞口之上增加标的、策略、方向和时间段归因。
  - 实现：`GET /ledger/attribution` 返回标的、策略、方向和时间段归因，账本页面提供归因视图。
- [x] 建立研究运行、信号、模拟订单、模拟成交、账本成交和持仓变化的统一时间线。
  - 实现：`GET /ledger/timeline` 按 `instrument_id` 汇总关联事件并按时间排序。
- [x] 从亏损或异常持仓直接回到生成它的研究证据、审核备注和执行记录。
  - 实现：`GET /ledger/positions/{instrument_id}/decision-context` 返回持仓和决策时间线，账本持仓行可直接打开关联上下文。

## P2：平台可靠性与多用户治理

- [x] 将 APScheduler 限定为触发器，实际任务交给持久化任务队列执行。
  - 实现：`apps/scheduler/jobs.py` 只提交自动化运行；任务状态、重试和恢复由 `apps/api/domains/automation/` 的持久化队列负责。
  - 验收：任务重启后可恢复，重复触发保持幂等，排队、运行、成功、失败和重试状态可查询。
- [x] 让风控从真实账本和策略分配读取 `total_equity`、`position_value` 和 `symbol_position_value`，并使用实际订单金额。
  - 实现：`apps/dispatcher/main.py` 从账本汇总、敞口、标的持仓和策略分配构造风控上下文，按分配权重计算订单金额。
- [x] 增加用户、角色和权限控制，并把审计扩展到信号审核、账本更正、配置、备份恢复和自动化操作。
  - 实现：`apps/api/domains/governance/` 提供会话、用户、角色、令牌和统一审计接口；API middleware 对受控请求执行精确权限校验并记录写操作。
- [x] 引入 SQLAlchemy 2 和 Alembic 管理业务数据模型与迁移。
  - 实现：`apps/api/database.py`、`apps/api/models.py`、`alembic.ini` 和 `apps/api/migrations/` 已接入，首个 revision 接管当前 33 张业务表。
- [x] 保持 SQLite 为默认单机模式，并增加 PostgreSQL 配置、迁移和回归测试。
  - 实现：仓储接口保持不变，底层连接适配 SQLite 和 PostgreSQL；CI 使用 PostgreSQL 16 执行 schema 与治理读写回归。
- [x] 明确本机与局域网部署配置，收紧生产环境 CORS、密钥和恢复权限。
  - 实现：`apps/api/deployment.py` 和 `configs/deployment.*.env*` 定义 `local`、`lan`、`postgresql` 三种模式；非本机模式拒绝通配 CORS，要求至少 32 个字符的管理令牌，并限制恢复权限。
- [x] 建立性能基线、数据量基线、故障演练和发布检查清单，并接入 CI。
  - 实现：`tools/quality_baseline.py`、`tools/run_recovery_drill.py`、`docs/QUALITY_GATES.md` 和 `.github/workflows/ci.yml` 覆盖性能、数据量、恢复演练和发布门禁。
- [x] 模拟执行、权限、审计和恢复演练完成后，再单独评估真实券商或交易所适配器。
  - 结论：`docs/LIVE_TRADING_ADAPTER_EVALUATION.md` 已完成单独评估；真实订单状态、提交幂等和外部账户对账未闭环，当前继续保持 `live_trading=false`。

## 文档与验收

- [x] 更新根 `README.md` 的当前功能描述与 API 路由列表，补充 `/backups`、`/incidents`、`/market-data` 和故障状态页面。
- [x] 本轮完成的功能条目已同步网页端实现，并在本文件更新状态。
- [x] 本轮交付已执行后端定向回归、前端单元测试、类型检查、生产构建和关键桌面/移动端浏览器测试。
  - 历史结果已归档；当前精简版以 TypeScript、生产构建和 FastAPI 导入检查为准。

## 推荐实施顺序

1. 信号连续审核工作台与下单前影响展示。
2. 账本首屏重排、更正流程和移动端记录模式。
3. 数据源自检、重试与恢复确认。
4. 全局业务检索与快捷操作。
5. 策略工作区重排、结构化参数和生命周期管理。
6. Instrument ID 统一与绩效归因时间线。
7. 持久化任务队列、真实账本风控、权限审计和数据库迁移。

## 每轮验收命令

```powershell
$env:UV_CACHE_DIR=(Resolve-Path '.uv-cache').Path
uv run python -m compileall -q apps/api apps/dispatcher apps/scheduler core strategies
uv run python -c "from apps.api.main import app; assert app.title"
Set-Location web
npm.cmd run test
npm.cmd run typecheck
npm.cmd run build
npm.cmd run e2e
# 本地启动 API 与 Vite 后进行网页验收
npm.cmd run e2e:isolated
```

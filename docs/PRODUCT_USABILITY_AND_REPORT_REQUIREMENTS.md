# QuantHub 用户体验、分类与分析报告改进需求

> 审计日期：2026-08-22  
> 审计视角：高频使用者、长期使用者  
> 审计范围：当前源代码、前端 API 调用、后端路由与存储、已有测试、项目文档，以及 `D:\Administrator\Desktop\video\QuantHub-视频功能清单.md`。  
> 判定原则：只有在现有文件中找到明确实现或明确缺失时才下结论；现有文件无法确认的事项列入“需手动验证”。

## 1. 结论摘要

当前项目已经形成研究、因子验证、信号审核、模拟订单和账本复盘的主要链路，但高频使用时有四个直接影响信任和效率的问题：

1. 工作台的产品分类同时存在五类画像和 `beginner/advanced` 两套入口模型，首页、导航、命令面板和账户配置没有完全使用同一套分类。
2. 分析报告存在“研究运行结构化结果”和“报告流结果”两套来源；报告生成在请求内同步完成，前端再读取已生成事件，停止、断线恢复、单章重试和最终导出门禁没有形成完整闭环。
3. 多用户数据隔离没有覆盖持仓、组合配置、信号、账本成交、模拟订单和全局搜索；提醒全量检查接口还会对所有用户的启用规则执行检查。
4. 总览账户口径、本地缓存同步、旧研究结果复用和状态后的下一步动作没有统一规则，长期使用时容易出现“看到的是哪套数据”“这个结论还能不能用”“失败后应该做什么”的判断负担。

优先级定义：

- **P0**：安全边界、跨用户数据、正式报告可信度；必须在继续扩展功能前完成。
- **P1**：高频工作流、数据口径、错误恢复和分析质量；直接影响日常使用。
- **P2**：效率、可发现性和展示增强；在 P0/P1 完成后实施。

## 2. 当前用户主流程与正确分类

### 2.1 高频用户主流程

```text
选择工作台画像
  → 选择市场与标的
  → 选择研究模式和可用模块
  → 运行研究并查看证据、数据截止时间和失效条件
  → 生成正式报告
  → 审核研究结论
  → 发布信号
  → 预览并创建模拟订单
  → 同步到账本
  → 复盘收益、费用、风险和研究来源
```

每一步必须显示三个信息：数据来源、数据时间边界、当前结果是否允许进入下一步。

### 2.2 工作台画像与功能分类

源码中已定义五类 `WorkspaceProfile`：`stock_investor`、`active_trader`、`quant_research`、`operations`、`custom`。前端仍通过 `InterfaceMode = 'beginner' | 'advanced'` 选择导航和页面集合，`navigationPreferences.ts` 还把固定、隐藏和最近入口保存在浏览器本地。因此产品分类目前不是单一模型。

需求：

- 五类 `WorkspaceProfile` 成为唯一产品分类；`beginner/advanced` 只能作为兼容迁移字段，不能继续决定正式菜单和首页。
- `visible_workspaces`、`effective.workspaces`、`effective.hidden_modules`、`effective.pinned_routes` 和 `effective.default_home` 必须由前端统一消费。
- Sidebar、移动导航、命令面板、首页卡片、研究入口和深链接使用同一套可见性函数。
- `default_home` 无权限时，后端返回可见入口中的回退值；前端不能自行猜测默认页。
- 画像、隐藏工作区、隐藏模块、固定入口、默认首页、默认市场、最近入口全部保存到账户级配置，刷新、清空 `localStorage` 和更换设备后保持一致。
- 服务端权限回收后，当前页面、轮询、SSE 和写操作统一进入无权限状态；不显示已缓存的私有结果。

验收：五类画像分别登录测试；修改画像后刷新、清空本地存储、换设备；验证 Sidebar、命令面板、首页、深链接和 API 返回完全一致。

### 2.3 市场能力矩阵

`ResearchWorkspacePage.tsx` 已明确区分市场能力：

| 市场 | 当前启动模块 | 当前不启动或不适用模块 | 产品要求 |
|---|---|---|---|
| `a_shares` | `market`、`news`、`pa`、`ensemble`、`fundamentals`、`valuation`、`announcements`、`macro` | 无 | 入口、任务、结果、报告和导出统一显示完整能力与数据边界 |
| `us_stocks` | `market`、`pa`、`ensemble`、`fundamentals`、`valuation` | `announcements`、`macro` | 入口明确显示“公司事件未接入”“宏观传导未接入”，不得显示为已完成模块 |
| `crypto` | `market`、`pa`、`ensemble` | 财报、估值、公司事件不适用；宏观传导标记为当前版本未建立可靠传导 | 任务配置、进度、报告、导出和提醒统一显示不适用原因 |

需求：后端返回市场能力矩阵和数据源状态；前端按该矩阵渲染，不再在页面中维护第二份隐式规则。未接入模块不得被提交为可执行任务，也不得在正式报告中生成空章节。

## 3. 分析报告改进需求

### P0-报告结果单一来源与最终快照门禁

现状证据：

- `ResearchWorkspacePage.tsx` 通过 `buildReadableReport(detailedRun)` 从 `ResearchRun` 直接构建主报告。
- 导出使用 `createReadableReportHtml(detailedRun, readableReport)`。
- `ResearchReportStream` 另行读取或创建 `ResearchReport`。
- `apps/api/domains/workspace/report_service.py` 的 `generate_report()` 在请求内同步生成章节，再写入事件。
- 前端 `ResearchReportStream.tsx` 调用 `api.researchReportEvents()`，没有使用 `/workspace/reports/{report_id}/stream` 的 SSE 接口。

用户影响：同一研究运行存在两套可见结果；结构化运行结果、报告正文、历史和导出无法证明来自同一版本。点击停止不能中断已经在请求内执行的完整生成。

需求：

1. `ResearchDecision` 作为结构化决策源，`ResearchReport` 作为解释和展示源，`ResearchRun` 不得绕过报告状态成为正式导出源。
2. 报告创建接口立即返回报告记录；章节生成进入后台任务。
3. 事件类型固定为 `report_started`、`section_started`、`delta`、`section_completed`、`report_completed`、`report_error`、`heartbeat`，每个事件包含 `task_id`、`research_run_id`、`report_id`、`sequence`、`event_version` 和服务端时间。
4. 前端直接使用 SSE；通过 `Last-Event-ID` 或 `after_sequence` 精确续传，执行去重、乱序保护、心跳、超时和用户隔离。
5. 停止后不再产生新的章节事件；已完成章节保留，未开始章节标记为取消。
6. 单章重试创建新报告版本，只替换指定章节并保留其他已完成章节；旧版本继续可读。
7. 只有收到 `report_completed` 且最终快照哈希校验通过的报告，才允许导出、历史复盘、提醒关联和进入执行链路。

验收：断线后从最后序号恢复且无重复；停止后无后续事件；单章重试不丢失其他章节；未完成报告的导出和执行接口返回明确阻断原因。

### P1-报告内容和解释质量

现有代码已提供证据、来源、新鲜度和失效条件字段，但页面没有把这些字段统一提升为每个结论的固定解释结构。高频用户需要在结论旁边直接看到：

- 结论对应的 `ResearchDecision` 字段；
- 使用的证据 ID、来源、抓取时间和数据截止时间；
- 支持结论的证据与冲突证据；
- 当前状态：完整、部分完成、数据不足、来源冲突、已过期或不适用；
- 失效条件和下一次复核时间；
- 是否允许发布信号、创建模拟订单、创建提醒或导出。

需求：报告章节使用统一的“结论—证据—冲突—边界—动作”结构；缺失关键证据时显示 `insufficient`，不得以默认文字填充方向；每章显示生成版本、研究运行版本和证据版本。

## 4. P0 多用户数据隔离与跨用户副作用

### 4.1 已确认的隔离缺口

源码证据：

- `apps/api/domains/portfolio/router.py` 的 `get_portfolio()`、`add_holding()`、`update_holding()`、`delete_holding()` 没有接收 `Request`。
- `apps/api/domains/portfolio/repository.py` 的 `list_holdings()`、`add_holding()`、`update_holding()`、`delete_holding()` 没有 `owner_id` 参数。
- `apps/api/store.py` 中 `holdings`、`portfolio_allocs`、`signals`、`ledger_trades`、`simulation_orders` 表定义没有用户字段。
- `apps/api/domains/simulation/router.py` 和 `apps/api/domains/ledger/router.py` 的查询、写入、更正和删除路由没有读取用户身份。
- `apps/api/domains/search/router.py` 的 `global_search()` 没有接收 `Request`；`search/service.py` 直接查询 `research_runs`、`signals` 和 `simulation_orders`，没有用户过滤。
- `apps/api/domains/alerts/router.py` 的 `POST /alerts/check` 没有接收用户身份；`alerts/service.py::check_all_rules()` 执行 `SELECT * FROM alert_rules WHERE enabled=1`，会检查所有用户的启用规则。

需求：

1. 为持仓、组合配置、信号、模拟订单、账本成交、现金流水、基准、风险决策、搜索结果补齐用户归属字段和迁移脚本。
2. 所有查询、创建、修改、删除、补偿同步、导出和更正接口从 `Request.state.principal` 获取用户身份，并在 repository/service/store 全链路传递。
3. 全局搜索只返回当前用户有权访问的研究运行、报告、任务、信号、订单、提醒和故障记录；搜索结果增加对象类型、市场、标的、更新时间、状态和版本。
4. `POST /alerts/check` 改为只检查当前用户规则；后台监控器执行全量检查时必须在服务内部按用户隔离，并记录触发用户。
5. 跨用户访问统一返回 404，不泄露对象是否存在；审计日志记录拒绝原因和主体。

验收：创建两个用户，各自写入持仓、信号、订单、账本、研究和提醒；双方搜索、列表、详情、修改、删除、导出和重试均不能读写对方数据；后台提醒检查不产生跨用户可见事件。

## 5. P1 总览账户口径与本地缓存同步

### 5.1 总览账户口径

`OverviewPage.tsx` 使用 `quanthub.overview.account-scope`、`quanthub.overview.modules.beginner.v1` 和 `quanthub.overview.modules.advanced.v1` 保存浏览器本地配置，同时展示研究组合、模拟账户和账本账户。

需求：

- 默认账户口径由账户级画像配置决定。
- 页面标题、指标、按钮和导出文件明确标注“研究持仓”“模拟账户”或“账本账户”。
- 不同账户的写操作入口分开，禁止在同一按钮语义下混用研究持仓、模拟订单和账本成交。
- 账户切换保留来源标识、切换时间和审计记录。

### 5.2 `useEditableWatchlist.ts` 与 `useEditableHoldings.ts` 同步策略

现状：后端加载失败时保留 `localStorage`；设置 `seeded=true` 后不继续自动重试；编辑退出时逐条调用 API；失败只收集标的字符串，没有服务器版本和逐条冲突信息。

需求：

- 本地缓存附带用户身份、服务器版本、缓存时间和同步状态。
- 后端恢复后执行拉取、合并和冲突提示；本地数据不得静默覆盖服务端数据。
- 每条保存结果显示成功、失败、冲突和可重试动作；支持撤销。
- 多设备同时编辑使用版本号或 ETag；冲突解决后才标记同步完成。
- UI 明确区分“服务端数据”“本地缓存”“尚未同步”。

## 6. P1 结果复用、任务和状态动作

### 6.1 最近研究结果复用

`ResearchWorkspacePage.tsx` 会从当前详细结果或历史 `succeeded`/`partial` 运行中选择最近记录，当前选择位置没有统一校验数据版本、新鲜度、研究周期、市场和报告模式。

需求：后端统一返回可复用条件：研究运行版本、数据截止时间、数据源、有效期、研究模式、市场和标的。条件不满足时显示“需要重新评估”；旧结果只能作为历史参考，不能自动成为当前结论。

### 6.2 状态到动作的统一映射

项目中同时使用 `pending`、`missing`、`unsupported`、`partial`、`failed`、`cancelled`、`timeout`、`insufficient`、`conflicted` 等状态。

需求：为每个状态定义统一映射：解释、下一步动作、是否允许导出、是否允许模拟交易、是否允许创建提醒、是否需要重新拉取、是否属于暂时故障或永久不适用。任务页、研究页、报告流、提醒页、信号页和模拟订单页使用同一映射。

### 6.3 任务和搜索回链

现状：`AnalysisTasksPage.tsx` 已支持筛选、SSE 路由和失败重试；`CommandPalette.tsx` 支持标的、策略定义、策略实验、研究、信号和模拟订单，但后端搜索没有任务、报告、提醒、故障记录，也没有用户过滤。

需求：搜索结果分组增加分析任务、正式报告、提醒事件和故障；结果显示状态、市场、标的、更新时间和版本；点击后进入对应详情页；失败任务可从同一入口重试并回到原研究运行；报告版本可直接定位。

## 7. P1 数据与研究质量

### 7.1 财报、估值、新闻和宏观

当前代码已聚合基本面、估值、公告、新闻和宏观模块，但市场支持范围不同，且财务质量、公司行为、竞争对手/行业传导和多源一致性仍未形成统一结果模型。

需求：

- 财报指标按期间、口径、币种、来源和更新时间保存；缺少关键字段时结论为 `insufficient`。
- 估值假设保存版本、输入、重算时间和敏感度结果；报告显示假设变化对结论的影响。
- 新闻、公司事件和宏观传导分别保存来源、影响对象、影响方向、证据强度和失效条件。
- A 股、美股、加密资产按市场能力矩阵展示可用和不可用模块，不用空结果代替不适用。

### 7.2 账本复盘的行动化

`TradeAnalyticsPanel.tsx` 已显示 FIFO、胜率、利润因子、盈亏比、持仓时间、费用侵蚀和归因链接，但当前重点仍是指标展示。

需求：每个异常指标提供可执行入口，例如查看对应成交、查看信号、打开研究运行、创建复核提醒；归因守恒不一致时禁止把结果标记为完整复盘；未知归因必须进入待补全队列。

## 8. 需用户手动验证的事项

以下事项不能仅凭当前代码确认，需你按真实环境执行并提供结果：

1. 两个真实账户同时访问持仓、信号、模拟订单、账本和搜索时的实际数据是否互相可见。
2. `POST /alerts/check` 在两个账户存在启用规则时是否产生跨账户可见事件。
3. 真实 LLM provider 是否提供持续 chunk 流，以及停止请求到 provider 的实际中断时间。
4. 浏览器断开网络后重新进入报告页，SSE 是否能从最后事件序号恢复。
5. OKX 私有 WebSocket、REST 补偿和连续七日 Demo 观察的真实证据。
6. A 股、美股、加密资产在当前部署配置下各模块的数据源、更新时间和失败率。

手动验证结果应记录请求时间、用户身份（脱敏）、标的、市场、数据截止时间、接口响应、事件序号和截图路径，不能用单元测试结果替代。

## 9. 实施顺序

1. P0 数据隔离、搜索隔离和提醒检查隔离。
2. P0 报告单一来源、后台生成、SSE 恢复、停止和最终快照门禁。
3. P0 五类画像统一分类并收口账户级配置。
4. P1 总览账户口径、本地缓存冲突处理和研究结果复用规则。
5. P1 状态动作映射、任务/报告/提醒/故障统一搜索回链。
6. P1 财报、估值、新闻、宏观和账本复盘的行动化改进。
7. P2 展示和效率增强。

## 10. 关联文件

- `D:\Administrator\Desktop\video\QuantHub-视频功能清单.md`
- `apps/api/domains/workspace/report_service.py`
- `apps/api/domains/workspace/router.py`
- `web/src/components/ResearchReportStream.tsx`
- `web/src/pages/ResearchWorkspacePage.tsx`
- `web/src/pages/OverviewPage.tsx`
- `web/src/hooks/useEditableWatchlist.ts`
- `web/src/hooks/useEditableHoldings.ts`
- `apps/api/domains/portfolio/router.py`
- `apps/api/domains/portfolio/repository.py`
- `apps/api/domains/search/router.py`
- `apps/api/domains/search/service.py`
- `apps/api/domains/alerts/router.py`
- `apps/api/domains/alerts/service.py`
- `apps/api/domains/simulation/router.py`
- `apps/api/domains/ledger/router.py`
- `apps/api/store.py`

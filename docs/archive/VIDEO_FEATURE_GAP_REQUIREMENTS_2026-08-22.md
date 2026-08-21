# QuantHub 视频功能差距与未实现需求

> 审计对象：`D:\Administrator\Desktop\video\QuantHub-视频功能清单.md` 与当前项目代码
>
> 审计日期：2026-08-22
>
> 目的：区分视频功能中已经具备的代码能力、仅部分具备的能力，以及当前仍未实现或未完成真实验收的能力，并将后两类转化为可执行需求。

## 1. 判定口径

| 标记 | 含义 |
| --- | --- |
| ✅ 已实现 | 代码、接口和前端入口基本形成闭环；相关测试或文档有证据。 |
| 🟡 部分实现 | 有代码或接口，但仍缺少关键交互、权限收口、生产数据能力或真实运行验收。 |
| ❌ 未实现 | 当前项目中没有可用的完整实现，或现有实现与视频承诺的语义不一致。 |

“代码存在”不等于“生产能力已验证”。特别是 OKX 私有 WebSocket 和连续 7 天观察，需要真实环境证据，不能用单元测试替代。

## 2. 视频功能实现审计

### 2.1 研究工作台总览

| 视频功能 | 状态 | 现有证据 |
| --- | --- | --- |
| 股票研究、财报、估值、新闻、宏观、因子、信号、模拟交易、账本统一到一个 Web 工作台 | ✅ | `web/src/main.tsx`、`web/src/navigation/workspaces.tsx`、`apps/api/domains/*/router.py` |
| 研究结论回到来源和证据 | ✅ | `core/research_decision.py`、`apps/api/domains/research/service.py`、`web/src/components/EvidenceRail/` |
| 研究运行复用统一 `ResearchDecision` | ✅ | `apps/api/domains/research/service.py`、`docs/FUNCTION_BOUNDARIES.md` |
| 本地优先、SQLite、Web/API/Runner 分层 | ✅ | `README.md`、`apps/api/store.py`、`apps/okx_runner/` |

### 2.2 工作台画像与权限

| 视频功能 | 状态 | 结论 |
| --- | --- | --- |
| 股票投资、主动交易、量化研究、运营管理、自定义五类画像 | 🟡 | 后端已定义五类画像，前端仍保留“精简/完整”`InterfaceMode` 首次选择，画像没有完全替代旧字段。 |
| 画像影响默认工作区、首页和模块显示 | 🟡 | 工作区过滤存在；首页内容没有按五类画像形成独立信息架构，`default_home`/`default_market` 也未完整驱动启动行为。 |
| 画像、隐藏模块、固定入口、最近入口跨设备保存 | 🟡 | `/workspace/config` 已支持账户级画像和配置，但 `web/src/navigation/navigationPreferences.ts` 仍把隐藏/固定/最近入口保存在 `localStorage`。 |
| 权限 ∩ 画像 ∩ 个人设置 | 🟡 | API 中间件有服务端权限拦截；前端 Sidebar/App 没有完全消费服务端 `effective` 配置，权限回收后的已打开页面和命令面板也未统一失效。 |
| 无权深链接不能访问 | ✅/🟡 | 服务端会返回 403；前端可见性主要按模式/画像判断，需补统一无权限页面和异步请求失效处理。 |

### 2.3 研究报告与研究运行

| 视频功能 | 状态 | 结论 |
| --- | --- | --- |
| 简明、投资研究、专业验证、量化实验四种报告模式 | ✅ | `ResearchReport.mode`、`MODE_SECTIONS`、研究页 `mode` 查询参数均已存在。 |
| 四种模式复用同一研究运行和 `ResearchDecision` | ✅ | `apps/api/domains/workspace/report_service.py` 从同一 run 读取 decision；模式只改变章节集合。 |
| 章节级事件、sequence、事件查询、`after_sequence` | ✅ | `research_report_events` 表、`/workspace/reports/{id}/events` 已实现。 |
| 真正的流式生成、断线期间可恢复 | 🟡 | 当前 `generate_report()` 在请求内同步生成完整报告，再把正文切成 delta 事件；不是 provider-neutral 的异步 LLM 流。 |
| SSE 重连、心跳、去重、超时、取消 | 🟡 | SSE/Last-Event-ID 接口存在，但前端实际使用事件轮询，生成同步导致“生成中取消”无法真正中断。 |
| 单章节失败后只重试该章 | 🟡 | API 有 regenerate 接口，但新版本只生成被选章节，未完整合并旧版本其它章节；前端没有“重新生成本章节”操作。 |
| 半成品不能导出/执行/触发提醒 | ❌ | 研究页仍以研究运行快照生成 HTML/PDF；没有把 `report_completed` 最终快照作为统一导出、历史、提醒和执行门禁。 |

### 2.4 因子研究与安全门禁

| 视频功能 | 状态 | 现有证据 |
| --- | --- | --- |
| 表达式安全检查、未来数据检查、参数边界 | ✅ | `apps/api/domains/factor_research/`、`apps/api/domains/factor_factory/service.py` |
| 重复公式和高度相关候选拦截 | ✅ | 因子 redundancy/candidate validation 接口与测试 |
| 样本外、回撤、交易成本、容量、成交率检查 | ✅ | 因子实验/Factor Factory 验证逻辑与 `tests/test_factor_*` |
| 第一名因子不得直接进入真实交易 | ✅ | 生命周期和手工批准接口；实盘开关默认关闭。 |
| OKX Demo/本地模拟观察、至少 7 个真实自然日 | 🟡 | 代码有 `paper_observing` 和 7 天判定；但 OKX 私有 WS 的真实端到端验证、连续 7 天观察证据仍未完成，见 `reports/M4_COMPLETION_REPORT.md`。 |
| 数据不足不画漂亮占位曲线 | ✅ | 研究结果包含数据质量/缺口状态，前端显示明确缺口。 |

### 2.5 股票研究、财报、估值、新闻和宏观

| 视频功能 | 状态 | 结论 |
| --- | --- | --- |
| K 线之外的财报、估值、新闻、宏观研究 | ✅ | `ResearchWorkspacePage` 已聚合基本面、估值、事件和量化模块。 |
| 增长质量、盈利、营运效率、稀释风险 | 🟡 | 基本财务质量/盈利趋势已计算；增长来源拆分、偿债/资本开支/股东回报、非经常性损益和行业模板仍不完整。 |
| 利润率、贴现率、终值假设可调并查看敏感度 | 🟡 | 后端有有限敏感度字段，但没有完整的可编辑假设模型、场景持久化和交互式重算。 |
| 新闻和宏观分别判断公司/行业/竞争对手影响 | 🟡 | 公司事件和宏观传导契约存在；事件影响仍主要依赖规则与单源数据，竞争对手/行业分层和多源一致性不足。 |
| 来源、新鲜度、失效条件 | 🟡 | provenance、freshness、invalidation 字段存在；前端和统一门禁尚未覆盖所有模块和所有过期场景。 |
| AI 只整理材料，不改写确定性结论 | 🟡 | `ResearchDecision` 和确定性模块已建立；报告流当前是 deterministic explanation，尚未完成带证据 ID 的 provider-neutral LLM 编排、schema 拒绝和受约束重试。 |

### 2.6 信号审核、模拟交易、账户账本

| 视频功能 | 状态 | 现有证据 |
| --- | --- | --- |
| 信号生成 → 审核中心 → 模拟订单 | ✅ | `apps/api/domains/signals/`、`simulation/`、`web/src/pages/SignalsPage.tsx` |
| 模拟订单与账户账本连接 | ✅ | simulation ledger-sync 接口、`SimulationOrdersPage` |
| FIFO 配对、逐笔胜率、利润因子、盈亏比、费用侵蚀 | ✅ | `apps/api/domains/ledger/service.py`、`web/src/components/ledger/TradeAnalyticsPanel.tsx` |
| 策略为什么赚钱、在哪里失效的复盘链路 | ✅ | Ledger attribution、decision timeline、研究/信号/订单/成交链接。 |

### 2.7 Web、API、Runner 安全边界

| 视频功能 | 状态 | 现有证据 |
| --- | --- | --- |
| 浏览器只访问统一 API，API 代理无界面 Runner | ✅ | `apps/api/domains/trading/router.py`、`README.md` |
| Runner 默认 shadow 只读 | ✅ | `apps/okx_runner/config.py`、`apps/api/domains/trading/config.py` |
| 实盘默认关闭，需独立批准 | ✅ | `QH_RUNNER_LIVE_APPROVED=1`、`live_trading=false`、交易服务门禁 |
| Windows DPAPI 加密，前端不回显密钥 | ✅ | `packages/credential_vault/okx.py`、`web/src/components/settings/OkxDemoCredentials.tsx`、`tests/test_okx_credentials.py` |
| 私有 WS 推送、断线 REST 补偿 | 🟡 | 协议和 mock E2E 已有；真实 OKX WS 因网络/DNS 未完成验证。 |

### 2.8 本地运行与项目边界

| 视频功能 | 状态 |
| --- | --- |
| PowerShell 一键启动 Web/API/Shadow Runner | ✅ |
| API=local、`live_trading=false`、Runner=shadow 默认配置 | ✅ |
| AGPL 开源、免责声明、不承诺收益 | ✅ |
| 真实 Demo 连续 7 天运行并形成可审计证据 | 🟡，当前未完成 |

## 3. 未实现/不完整需求

以下需求按优先级排序。P0 是影响安全边界或视频核心承诺的缺口；P1 是影响研究质量和生产可用性的缺口；P2 是增强项。

### P0-01 工作台画像、账户配置和前端权限收口

**目标**：让五类画像真正成为用户入口，并保证“用户权限 ∩ 画像默认能力 ∩ 用户个人设置”在前后端一致。

**需求**

1. 删除或降级 `beginner/advanced` 作为产品画像的角色；首次进入直接选择五类工作台画像，并展示每类默认工作区说明。
2. 画像、隐藏工作区、隐藏模块、固定入口、默认首页、默认市场、最近入口全部使用账户级配置；清空浏览器存储或更换设备后仍可恢复。
3. 前端启动时读取 `/workspace/config` 的 `effective` 字段，不再只读取 `localStorage` 的隐藏/固定入口。
4. Sidebar、移动导航、命令面板、首页卡片和深链接都执行同一套可见性过滤。
5. 服务端权限变化后，当前页面和进行中的异步请求收到统一 403 状态；页面显示无权限状态，不泄露数据。
6. `default_home` 必须在登录/启动后实际生效；无权默认首页自动回退到第一个可见入口。

**验收标准**

- 五类画像均可切换，历史研究、订单和提醒不丢失。
- 修改配置后刷新浏览器、清空 localStorage、换设备仍能恢复。
- 无权限用户看不到对应菜单/命令/卡片，直接访问 URL 返回统一 403 页面。
- 回收权限后已打开页面不再显示数据，写操作全部被服务端拒绝。

**涉及模块**：`web/src/hooks/useInterfaceMode.tsx`、`web/src/navigation/navigationPreferences.ts`、`web/src/navigation/workspaces.tsx`、`web/src/App.tsx`、`web/src/components/Sidebar.tsx`、`apps/api/domains/workspace/`、`apps/api/main.py`。

### P0-02 报告真正异步流式化和最终快照门禁

**目标**：把当前“同步生成后切 delta”改为可中断、可恢复、可审计的章节流。

**需求**

1. 增加 provider-neutral LLM streaming adapter，供应商 chunk 只能在后端转换为内部事件。
2. 报告任务拆分为 `report_started`、`section_started`、`delta`、`section_completed`、`report_completed`、`report_error`、`heartbeat`；事件必须包含 `task_id`、`research_run_id`、`report_id`、`sequence`、`event_version`、服务端时间。
3. 生成放入后台任务/队列，接口立即返回 report；取消操作必须能真正停止尚未完成的章节。
4. 实现 `Last-Event-ID`/`after_sequence` 续传、心跳、超时、重复事件去重、乱序保护和用户隔离。
5. 章节失败时保留已完成章节；单章节重试生成新报告版本，并合并旧版本其它已完成章节，不覆盖旧版本。
6. 前端以章节卡片显示等待/生成中/完成/部分失败/跳过，支持停止、重连恢复、暂停自动滚动、复制正文和查看完整引用。
7. 导出、历史复盘、提醒和执行入口只能读取 `report_completed` 且快照 hash 校验通过的报告。

**验收标准**

- 断开 SSE 后按最后 sequence 恢复，事件无重复、无乱序、无丢失。
- 点击停止后不会继续产生新章节事件。
- 单章重试后新版本包含其它旧章节，旧版本仍可读取。
- 未完成报告在导出/提醒/执行接口被拒绝。
- 覆盖正常完成、超时、模型拒绝、证据缺失、取消、刷新恢复和重复点击测试。

**涉及模块**：`apps/api/domains/workspace/report_service.py`、`apps/api/domains/workspace/router.py`、`apps/api/store.py`、`apps/api/domains/tasks/service.py`、`web/src/components/ResearchReportStream.tsx`、`web/src/pages/ResearchWorkspacePage.tsx`。

### P0-03 完成 OKX 私有 WS 与连续 7 天 Demo 观察

**目标**：把“协议代码存在”升级为真实环境可审计证据。

**需求**

1. 在受限 OKX Demo 账户上完成私有 WS 登录、订阅、推送、重连和 REST 补偿验证。
2. 连续运行至少 7 个真实自然日，记录重复下单、漏记成交、订单/成交/资金/持仓对账差异、网络故障和恢复时间。
3. 观察中任一关键差异未解释或发生中断，观察周期重新起算。
4. 所有证据脱敏落盘，凭据轮换后重新执行安全扫描。

**验收标准**：7 天报告齐全；重复下单=0；漏记成交=0；未解释账实差异=0；WS 断线可恢复；对账 diff 已关闭。

**涉及证据**：`reports/M4_COMPLETION_REPORT.md`、`../m4_observation_template.md`、`apps/okx_runner/private_ws.py`、`apps/okx_runner/reconcile_scheduler.py`。

### P1-01 财报数据管线和公司行为补齐

**需求**

- A 股增加业绩预告、业绩快报、分红送转等结构化提供方。
- 美股增加 8-K 和公司指引结构化提供方。
- 增加后台增量抓取缓存、失败重试和独立计划任务。
- 完整处理停牌、复权、拆股、增发、分红和跨币种换算，并把调整原因写入 provenance。
- 关键财务字段至少两个独立来源交叉验证；只有单源时明确标注。

**验收标准**：同一研究 cutoff 下可重放；公司行为前后价格、股本和估值分母一致；数据源不可用时显示结构化缺口而非伪造数值。

**涉及模块**：`packages/financial_data/*`、`apps/api/domains/financials/`、`apps/api/store.py`。

### P1-02 财务质量与盈利趋势行业化

**需求**

- 将增长拆分为价格、销量、并表、一次性项目、会计口径和汇率影响。
- 补充盈利能力、营运效率、偿债能力、资本开支、股东回报和稀释风险指标。
- 增加应收、存货、现金流和非经常性损益异常规则。
- 银行、制造、软件、周期行业使用不同阈值和指标模板。
- 每个结论附指标来源、期间、口径、数据新鲜度和失效条件。

**验收标准**：行业模板可配置、版本化；缺失关键指标时结论变为 `insufficient`，不得用默认阈值强行给方向。

### P1-03 估值假设、敏感度和情景分析

**需求**

- 支持盈利、利润率、贴现率、终值等关键假设的输入、版本和审计记录。
- 支持“低估但基本面恶化”“高估但盈利上修”“周期底部失真”等情景分类。
- 敏感度结果同时保存假设、输入数据、计算版本和输出，不仅返回一个展示字段。
- 前端提供可交互场景切换；重算必须复用同一研究 cutoff，不得引入未来数据。

**验收标准**：任何场景均可重放；模式切换不改变 `ResearchDecision`；输入超出边界时服务端拒绝。

**涉及模块**：`packages/financial_data/analysis.py`、`apps/api/domains/financials/service.py`、`web/src/pages/ResearchWorkspacePage.tsx`。

### P1-04 新闻、宏观与事件传导增强

**需求**

- 公司、行业、竞争对手影响分别计算，不能复用一个情绪分数。
- 事件增加新颖度、来源可信度、多源一致性、价格已反映程度和明确失效条件。
- 扩展汇率、国债收益率、流动性等宏观数据提供方。
- 支持地缘政治、制裁、贸易政策、大宗商品冲击，并保存来源等级和不确定性。
- 标的关系图扩展到行业、商品、供应链、收入区域和监管暴露。
- K 线叠加财报公告、公司事件和宏观事件；支持“只通知重要变化”。

**验收标准**：宏观传导结论同时引用事件证据和标的暴露证据；单源/过期/方向冲突时自动降低结论状态，不输出确定性交易措辞。

**涉及模块**：`packages/financial_data/events.py`、`packages/financial_data/macro.py`、`apps/api/domains/news/`、`web/src/pages/NewsPage.tsx`、`web/src/pages/ResearchWorkspacePage.tsx`。

### P1-05 AI 证据边界和解释质量

**需求**

- LLM 输入只能来自已保存、带 evidence ID 的摘要；禁止把未持久化模型字段直接交给前端。
- 输出采用固定 schema；引用不存在的数字、事件或来源时整项拒绝。
- 事实、确定性计算、模型推断和不确定性分层显示。
- 重要结论至少有直接来源；宏观传导必须同时有事件和暴露证据。
- 支持一次受约束修复重试，仍失败则降级为结构化规则结果。
- 预测内容必须有时间范围、反例和失效条件；禁止收益承诺性措辞。

**验收标准**：模型无法覆盖程序生成的证据不足、冲突、过期和执行门禁状态；任何拒绝均在报告事件中记录原因。

### P2-01 研究复用和观察提醒

**需求**

- 最近研究复用时校验数据版本、新鲜度、用户目的和研究周期。
- 记录上次观察条件是否触发，以及触发后价格和基本面如何演化。
- 重要变化提醒支持订阅、去噪、取消和审计。

## 4. 已验证命令与证据

本次只做只读核对并运行了相关回归：

- 后端相关测试：`102 passed in 6.00s`
- 前端类型检查：`npm.cmd run typecheck` 通过

代表性测试范围：研究执行闭环、研究运行元数据、股票研究契约、Factor Factory OKX Demo、账本交易分析、交易代理、OKX 凭据保护。

## 5. 交付优先级建议

1. 先完成 P0-01、P0-02，避免视频中“多用户工作台”和“可恢复流式报告”被误认为已经生产可用。
2. 同步完成 P0-03 的真实 Demo 观察；在此之前只能声称“协议和 mock 已验证”。
3. 再补齐 P1-01～P1-05 的真实数据和研究质量能力。
4. P2 用于提升复用、提醒和长期研究体验，不应替代 P0/P1 验收。

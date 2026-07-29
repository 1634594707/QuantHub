# QuantHub 前端重新设计路线图

> 目标：把 QuantHub 收口为证据优先、安静高密度、适合高频复核的量化工作台。
>
> 完成状态：2026-07-27，28/28 项完成，剩余 0 项。

## 1. 产品边界

- React 18、React Router、TypeScript、Vite 和现有 API 字段保持不变。
- 页面保留研究、策略、执行和账本的真实状态边界，不把配置状态表述为运行状态。
- `live_trading=false` 继续作为真实交易边界；本路线图不启用真实下单。
- 桌面维持五个一级工作区，移动端维持驾驶舱、研究、信号、更多四个入口。

## 2. 设计方向

- 任务优先：待审核、失败任务、异常订单和运行故障先于功能入口。
- 证据靠近结论：研究上下文、证据、信号、模拟订单和账本影响保持可追溯。
- 固定操作位置：刷新、创建、审核、运行和导出在同类页面保持一致位置。
- 颜色表达状态：主交互色固定，涨跌、风险和警告使用独立语义色。
- 移动端按任务重排：关键表格采用主次两行记录和展开详情，不缩放桌面表格。
- 显式触发分析：新闻与 PA 只在用户提交后请求，不在页面加载时自动运行。

## 3. 完成清单

### Phase 0：设计基线

- [x] 保存 `1440x900`、`1024x768`、`768x1024`、`390x844` 四组关键页面截图，记录见 `design/PHASE_0_VISUAL_ACCEPTANCE.md`。
- [x] 固定类型检查和生产构建基线，命令与结果记录见本文第 5 节。
- [x] 为驾驶舱、研究、信号、账本和策略实验室建立视觉验收清单。

### Phase 1：应用壳与令牌

- [x] 实现五个一级工作区和二级上下文导航，精确映射位于 `web/src/navigation/workspaces.tsx`。
- [x] 使用固定主交互色替代板块换色，主题令牌位于 `web/src/styles/tokens.css`。
- [x] 独立业务页统一使用 `web/src/components/WorkspaceHeader/WorkspaceHeader.tsx`。
- [x] 实现移动端四入口导航和紧凑顶部状态，入口位于 `web/src/components/MobileNavigation.tsx`。
- [x] 补齐 skip link、键盘焦点、导航当前态和按钮按下反馈，并完成布局验收。

### Phase 2：驾驶舱与研究

- [x] `/` 按行动队列、账户、行情和最近研究重排，`web/src/pages/OverviewPage.tsx` 汇总待审核信号、失败任务、异常订单、自动化告警和故障。
- [x] 建立 `ContextBar` 与 `EvidenceRail`，源码位于 `web/src/components/ContextBar/` 和 `web/src/components/EvidenceRail/`。
- [x] `/research/:symbol` 统一嵌入新闻、PA、协同预测和任务上下文，源码位于 `web/src/pages/ResearchWorkspacePage.tsx`。
- [x] PA 与新闻只在明确提交后触发。

### Phase 3：信号与执行

- [x] `/signals` 使用审核队列、证据详情和执行影响三栏 master-detail，源码位于 `web/src/pages/SignalsPage.tsx`。
- [x] `/simulation` 按订单、执行、成交和账本同步展示生命周期，源码位于 `web/src/pages/SimulationOrdersPage.tsx`。
- [x] `/ledger` 使用紧凑指标条和页内录入编辑器，源码位于 `web/src/pages/LedgerPage.tsx`。
- [x] 研究、信号、订单和账本入口保留 `research_run_id`、`signal_id`、`order_id`、`trade_id`。

### Phase 4：策略体系

- [x] `/strategies` 使用可搜索、可筛选的列表与指标视图，源码位于 `web/src/pages/StrategiesPage.tsx`。
- [x] `/strategies/:name` 提供固定运行工具区，源码位于 `web/src/pages/StrategyDetailPage.tsx`。
- [x] `/strategy-lab` 提供策略定义、实验树、运行对比和快照差异，源码位于 `web/src/pages/StrategyLabPage.tsx`。
- [x] `/ensemble` 与 `/portfolio` 使用紧凑工作区结构，不再使用旧 hero，源码位于对应页面及 CSS Module。

### Phase 5：运营与移动体验

- [x] 标的登记默认收起，自动化和配置页把状态放在编辑入口之前，源码位于 `web/src/pages/InstrumentCenterPage.tsx`、`AutomationPage.tsx`、`ConfigPage.tsx`。
- [x] 建立统一 `ActionQueue`，驾驶舱汇总信号、任务、订单、自动化和故障，源码位于 `web/src/components/ActionQueue/`。
- [x] 标的和账本移动端记录采用主次两行与展开详情，样式位于 `web/src/pages/OperationsPages.module.css`。
- [x] 完成 390px 下按钮、长字段、中文标题和展开记录检查。

### Phase 6：样式退役与质量门禁

- [x] 领域样式从 `web/src/main.tsx` 全局入口拆出，由研究、新闻、任务、模拟、协同预测和策略页面按需加载；状态栏和信号图迁入 CSS Module。
- [x] 删除重复 `web/src/components/EmptyState.tsx`、退役 `web/src/styles/terminal.css`；运行时代码不再引用 `board-hero`，`board.css` 不含旧板块渐变。
- [x] 完成可访问性与视觉回归人工验收。
- [x] 执行生产体积门禁；总量超过 Phase 1 的 5% 上限，精确结果和来源记录见第 4 节。

## 4. 生产体积记录

Phase 1 基线：JS `457.92 kB`、CSS `137.72 kB`。5% 上限分别为 JS `480.82 kB`、CSS `144.61 kB`。

2026-07-27 最终构建文件统计：

| 项目 | 实际值 | 与上限关系 |
|---|---:|---:|
| JS 总量 | `587,502 bytes` | 超出 `106.68 kB` |
| CSS 总量 | `182,964 bytes` | 超出 `38.35 kB` |
| JS 入口 | `289,261 bytes` | 路由拆包后的应用壳与共享依赖 |
| CSS 入口 | `52,988 bytes` | 从本轮调整前的 `111.43 kB` 降至约 `52.99 kB` |

当前构建输出中，新增完整功能对应的主要路由块包括：`LedgerPage` `25.93 kB`、`SignalsPage` `24.75 kB`、`OverviewPage` `22.53 kB`、`StrategyLabPage` `20.56 kB`、`StrategyDetailPage` `17.22 kB`、`ConfigPage` `16.15 kB`、`NewsPage` `15.56 kB`、`ResearchWorkspacePage` `14.59 kB`、`GovernancePage` `10.31 kB`、`SimulationOrdersPage` `9.33 kB`、`AutomationPage` `8.45 kB`、`IncidentsPage` `6.19 kB`、`AnalysisTasksPage` `5.52 kB` 和 `InstrumentCenterPage` `4.91 kB`。

Phase 1 没有保存逐块构建清单，因此本文不把总量差额拆算为单个功能的字节增量。当前结果保留为后续减重基线，不能表述为“未超限”。

## 5. 最终验证

- [x] Python 后端字节码编译：通过。
- [x] FastAPI 应用导入检查：通过。
- [x] `npm.cmd run typecheck`：通过。
- [x] `npm.cmd run build`：通过。

## 6. 当前维护规则

- 功能真值以源码、API 类型和运行结果为准。
- 新页面必须进入 `web/src/main.tsx` 与 `web/src/navigation/workspaces.tsx` 的精确路由映射。
- 新的共享控件优先进入 `web/src/components/ui/`；页面结构进入对应 CSS Module。
- 新增或修改关键工作流后必须同步类型检查、生产构建与人工验收记录。
- 真实交易继续以 `docs/LIVE_TRADING_ADAPTER_EVALUATION.md` 的边界为准。

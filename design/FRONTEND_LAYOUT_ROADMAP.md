# QuantHub 前端布局优化路线图

> 建立日期：2026-07-28
>
> 目标：在不改变现有 React、React Router、API 数据真值与暗色终端设计方向的前提下，收敛布局层的重复实现，使 chrome 信息只有一处归属、页面骨架只有一套原语、响应式断点只有四档。
>
> 状态规则：`[x]` 表示改动落地且相应测试或视觉基线均已通过；`[ ]` 表示仍未形成可验收闭环。
>
> 证据边界：条目只使用当前仓库中的组件、样式、令牌和测试作为依据。所有行号基于 2026-07-28 工作树。
>
> 范围边界：本轮只处理布局与样式结构，不改动业务逻辑、API 调用和数据真值。

## 现状诊断

以下 7 项为静态阅读 `web/src` 全部 24 个页面容器与 11308 行 CSS 后确认的结论，每项都附源码位置。

- 状态信息在三处重复渲染。`components/Topbar.tsx` 有信号数、连接状态和 `market-status`（模式 + 策略数）三个只读徽标；`components/StatusBar/StatusBar.tsx` 底栏重复渲染连接状态、信号数、策略数、时钟和全局检索入口；`components/Sidebar.tsx:128` 页脚第三次渲染时钟。顶栏因此没有位置放页面级主操作。
- 竖向预算被 chrome 占用。`--topbar-h` 52px（`styles/tokens.css:233`）+ `WorkspaceHeader` 64 至 72px（`components/WorkspaceHeader/WorkspaceHeader.module.css`）+ StatusBar 约 30px 合计约 150px。总览页在此之上再叠三条数字带：`WorkspaceHeader` metrics 四项、`ActionQueue` 五项、`KpiRow` 四张卡。
- 没有统一页面骨架。`LedgerPage`、`IncidentsPage`、`InstrumentCenterPage`、`PortfolioPage`、`AutomationPage`、`NewsPage` 用 `<div className={s.page}>`；`StrategiesPage` 用 `<>`；`PaAnalysisPage` 用 `.stack-4`；`SignalsPage.tsx:507` 用 `<main className={s.page}>`，嵌在 `App.tsx:125` 的 `<main id="main-content">` 内部，形成重复 landmark。
- 布局原语是全局类且语义冲突。`.grid-2` 在 `styles/base.css:190` 为 `1fr 1fr`，在 `styles/app.css:646` 被覆盖为 `1fr 360px`，全站共用同一名字；`.col-left`、`.col-right` 同为全局类（`styles/app.css:727`）。同时 `LedgerPage.module.css`、`StrategyLabPage` 各自定义 module 内的 `grid2`。右栏存在三套实现：总览固定 360px、研究页 `EvidenceRail` 320px sticky、`SignalsPage.module.css:164` 三列硬编码 `minmax`。
- 断点是 19 个散值：520、560、600、680、720、760、767、820、860、880、900、920、960、980、1023、1100、1180、1200。后果是中间态错位。1024 至 1117px 区间侧栏已隐藏，但信号页三列最小宽合计 853px 加内容 padding 仍在挤压，其断点却在 980；总览 `.grid-2` 在 900 才塌单列，而 `WorkspaceHeader` 在 1180 就隐藏描述。
- 一处失效的高度计算。`components/EvidenceRail/EvidenceRail.module.css:6` 与 `:37` 两条 `max-height` 使用 `var(--statusbar-h)`，该令牌在全项目零定义，两条 calc 均无效，证据栏高度实际不受约束。
- CSS 资产冗余。`styles/app.css` 中 10 个选择器重复定义：`.app-shell`（17、1942）、`.sidebar`（48、1955）、`.topbar`（411、2282）、`.search`（444、2287）、`.scrim`（43、2297）、`.market-status`（481、2293）、`.context-nav-count`（2136、2142）、`.kline-toolbar`（788、917）、`.kline-svg`（844、890）、`.kline-market-select`（767、785）。432 个全局类中 110 个在 `src/`、`index.html`、`e2e/` 全部零引用，含 `.brand*`、`.collapse-btn`、`.sidebar-foot`、`.side-foot-*`、`.nav-*` 旧侧栏整块，以及已被 `ActionQueue` 取代的 `.pending-strip*`。

## P0：删除冗余与建立常量

本阶段只做删减和常量定义，不改变任何渲染结构，风险最低。

### CSS 资产收敛

- [ ] 合并 `styles/app.css` 中 10 个重复选择器，保留后出现的生效定义并删除被覆盖的前一份。
  - 处理清单：`.app-shell`、`.sidebar`、`.topbar`、`.search`、`.scrim`、`.market-status`、`.context-nav-count`、`.kline-toolbar`、`.kline-svg`、`.kline-market-select`。
  - 验收：合并前后 `1440x900`、`1024x768`、`768x1024`、`390x844` 四视口截图与 `design/baselines/2026-07-27/` 无差异。
- [ ] 删除 110 个零引用全局类。
  - 旧侧栏整块：`.brand`、`.brand-logo`、`.brand-name`、`.collapse-btn`、`.sidebar-foot`、`.side-foot-clock`、`.side-foot-meta`、`.side-foot-ver`、`.nav-caret`、`.nav-group`、`.nav-icon`、`.nav-section`、`.nav-section-text`、`.nav-sub`、`.nav-sub-desc`、`.nav-sub-dot`、`.nav-sub-label`、`.nav-sub-text`、`.nav-subitem`。
  - 已被 `ActionQueue` 取代：`.pending-strip`、`.pending-strip-head`、`.pending-strip-grid`、`.pending-item`、`.pending-warn`、`.pending-danger`。
  - 已被 CSS Module 取代的信号页残留：`.signals-layout`、`.signals-toolbar`、`.signals-filters`、`.signals-agg`、`.signal-review`、`.signal-review-actions`、`.signal-review-meta`、`.signal-action`、`.signal-action-error`、`.signal-decision-note`、`.signal-order-quantity`、`.signal-status`、`.signal-viz`、`.sig-group*`、`.sig-detail-cell`。
  - 未使用工具类：`.stack-1`、`.stack-2`、`.stack-3`、`.stack-5`、`.stack-6`、`.row-1`、`.row-2`、`.row-3`、`.row-4`、`.grid-3`、`.full-w`、`.full-h`、`.text-right`、`.text-center`、`.nowrap`、`.uppercase`、`.hairline`、`.glass`、`.density-tight`、`.focus-ring`、`.sr-only`、`.tnum`。
  - 保留例外：`.skip-link` 在 `index.html` 有引用，不得删除。
  - 验收：删除后 `npm run build` 通过，四视口截图无差异。
- [ ] 完整零引用清单以脚本方式复核，避免误删动态拼接的类名。
  - 复核范围：`src/**/*.tsx`、`src/**/*.ts`、`src/**/*.html`、`index.html`、`e2e/**`。
  - 已知动态拼接风险点：`SignalsPage.tsx` 中 `s[dirClass(...)]`、`s[\`status_${...}\`]` 属于 CSS Module，不在本清单范围。

### 布局令牌

- [ ] 在 `styles/tokens.css` 定义 `--statusbar-h: 30px`，修复 `EvidenceRail.module.css:6` 与 `:37` 两条失效 calc。
  - 验收：证据栏在 `1440x900` 下高度受约束，内部出现独立滚动而非撑破容器。
- [ ] 在 `styles/tokens.css` 定义四档断点常量：`--bp-sm: 640px`、`--bp-md: 900px`、`--bp-lg: 1200px`、`--bp-xl: 1600px`。
  - 说明：CSS 自定义属性不能用于 `@media` 条件，本条只建立文档级唯一真值源，实际 `@media` 值在 P2 统一替换时手工对齐这四个数。

### 顶栏与底栏分工

- [ ] 从 `components/Topbar.tsx` 移除 `signal-pill`、`connection-pill` 和 `market-status` 三个只读徽标。
  - 保留：移动端菜单按钮、移动端面包屑、全局检索、主题切换、头像。
  - 连带：`Topbar` 的 `health`、`apiOnline`、`signalCount` 三个 prop 随之移除，`App.tsx:116` 传参同步收敛。
- [ ] 在 `components/StatusBar/StatusBar.tsx` 补齐实盘或研究模式显示，使系统状态在底栏形成唯一归属。
  - 数据源：沿用 `App.tsx` 已有的 `health.data.live_trading`。
- [ ] 从 `components/Sidebar.tsx:128` 页脚移除时钟，只保留版本与终端标识。
  - 连带：`Sidebar` 的 `clock` prop 移除，`App.tsx:113` 传参同步收敛。
- [ ] 为 `Topbar` 增加页面主操作插槽，使各页主动作可从内容区上移到顶栏。
  - 首批接入：标的研究「运行分析」、信号中心「发布手动信号」。
  - 验收：顶栏在 `1440x900` 下横向留白不少于移除三个徽标前的水平，`390x844` 下不出现横向溢出。
- [ ] 更新 `App.tsx` 中 `Topbar` 与 `Sidebar` 的调用签名，并确认 `boardForPath` 与 `BOARD_LABEL` 不受影响。
  - 验收：`npm run test` 通过，`e2e/smoke.spec.ts` 与 `e2e/accessibility.spec.ts` 通过。

## P1：统一页面骨架与布局原语

本阶段改动面覆盖全部业务页，但每处改动机械且可逐页验证。

### PageShell

- [ ] 新建 `components/layout/PageShell`，统一承担页面内边距、区块纵向间距、内容最大宽、滚动容器、右栏 sticky 与折叠行为。
  - 接口：`header`（承载 `WorkspaceHeader`）、`sub`（可选通栏条，如 `ActionQueue`）、`rail`（可选右侧栏）、`children`。
  - 约束：不渲染 `<main>`，避免与 `App.tsx:125` 的 `#main-content` 形成重复 landmark。
- [ ] 将 24 个页面容器全部迁移到 `PageShell`，移除各页自有的 `s.page`、`.stack-4` 和裸 `<>` 写法。
  - 迁移清单：总览、标的研究、新闻分析、PA 分析、分析任务、策略库、策略详情、策略实验室、协同预测、策略分配、信号中心、模拟执行、账户与账本、标的中心、自动化中心、故障状态、访问治理、系统配置。
- [ ] 修复 `SignalsPage.tsx:507` 的嵌套 `<main>`，改为 `PageShell` 的普通区块。
  - 验收：`e2e/accessibility.spec.ts` 的 axe 检查不再报告重复 landmark。
- [ ] 删除迁移后失效的各页 `.page` 规则及其响应式覆盖。
  - 涉及：`pages/OperationsPages.module.css`、`pages/SignalsPage.module.css`、`pages/NewsPage.module.css`、`pages/PortfolioPage.module.css`、`pages/ConfigPage.module.css`、`pages/GovernancePage.module.css`。

### 布局原语

- [ ] 新建 `components/layout/Split`，承担主栏加副栏的两列结构，副栏宽度统一为 `clamp(300px, 24vw, 380px)`，塌列断点内置。
- [ ] 新建 `components/layout/Stack`、`components/layout/Cluster`、`components/layout/MetricStrip`，替代散落的 flex 与 grid 内联写法。
- [ ] 将 `OverviewPage.tsx:152` 与 `EnsemblePage.tsx:383` 的 `.grid-2` 加 `.col-left` 加 `.col-right` 改为 `Split`。
- [ ] 将 `SignalsPage.module.css:164` 的三列硬编码 `minmax(238px, 0.78fr) minmax(350px, 1.35fr) minmax(265px, 0.87fr)` 改为 `Split` 嵌套，使最小宽由原语保证。
- [ ] 将 `LedgerPage.module.css` 与 `StrategyLabPage` 的 module 内 `grid2` 统一到 `Split`。
- [ ] 迁移完成后删除 `styles/base.css:190` 的 `.grid-2`、`styles/app.css:646` 的 `.grid-2` 覆盖、`styles/app.css:727` 的 `.col-left` 与 `.col-right`，以及 `styles/app.css:1662` 的 900px 塌列覆盖。
  - 验收：全站不再存在同名不同义的全局网格类。
- [ ] 将 `EvidenceRail` 的 sticky 与折叠职责移交 `PageShell` 的 `rail` 插槽，`EvidenceRail` 只负责内容。
  - 验收：研究页右栏行为与迁移前一致，且 `--statusbar-h` 参与的高度约束生效。

## P2：竖向预算与响应式收敛

本阶段会改变可见尺寸，需重录视觉基线。

### 竖向预算

- [ ] 将 `--topbar-h` 从 52px 调整为 48px。
- [ ] 将 `WorkspaceHeader` 的 `min-height` 与 `max-height` 从 64 至 72px 调整为固定 60px。
  - 连带：`e2e/operations-layout.spec.ts` 中 `expect(headerHeight).toBeLessThanOrEqual(72)` 同步改为 60。
- [ ] 将总览页三条数字带压缩为两条。
  - `WorkspaceHeader` metrics 只保留组合净值；持仓标的、自选标的、市场宽度并入 `KpiRow`。
  - 涉及：`pages/OverviewPage.tsx:126` 的 metrics 数组与 `components/KpiRow.tsx` 的 `summaryToKpis`。
- [ ] 为 `.content` 增加 `max-width: 1680px` 与 `margin-inline: auto`，避免宽屏下表格与 K 线无限拉伸。
  - 验收：`1920x1080` 下内容区居中且不超过 1680px。

### 断点收敛

- [ ] 将 19 个散值断点全部归并到 `--bp-sm` 640、`--bp-md` 900、`--bp-lg` 1200、`--bp-xl` 1600 四档。
  - 待归并文件：`styles/app.css`、`styles/base.css`、`styles/research.css`、`styles/news.css`、`styles/ensemble.css`、`styles/strategy-module.css`、`pages/*.module.css`、`components/**/*.module.css`。
- [ ] 按四档统一响应式规则，使 shell 折叠点与页面塌列点对齐。
  - 大于等于 `--bp-lg`：主栏加副栏加右栏三列。
  - `--bp-md` 至 `--bp-lg`：两列，右栏降级为可折叠 rail。
  - `--bp-sm` 至 `--bp-md`：单列，侧栏为抽屉。
  - 小于 `--bp-sm`：单列，底部四入口导航。
- [ ] 消除 1024 至 1200px 夹缝态，确认信号页三列在该区间不再挤压。
  - 验收：新增 `1100x800` 与 `1280x800` 两个视口进入 `e2e/workspace-layout.spec.ts`，横向溢出断言小于等于 1。

### CSS 文件拆分

- [ ] 将 `styles/app.css` 现有 2439 行拆分为 `styles/shell.css`（App Shell、Sidebar、Topbar、StatusBar）与按业务域归位的其余部分。
  - 说明：`KlineCard`、`HoldingsTable`、`Watchlist`、`MarketBreadth` 相关规则迁入各自 `.module.css`。
  - 同步更新 `main.tsx` 的样式加载顺序与 `styles/app.css` 顶部的分层注释。
- [ ] 更新 `design/UI_CONTROL_PANEL.md` 中的样式真值源说明，使其指向拆分后的文件。

## 验收与风险

- [ ] P0 完成后运行 `npm run test`、`npm run build`、`npm run e2e:isolated`，四视口截图与 `design/baselines/2026-07-27/` 逐张比对无差异。
- [ ] P1 完成后运行同一组命令，`e2e/workspace-layout.spec.ts` 与 `e2e/operations-layout.spec.ts` 的横向溢出断言全部通过。
- [ ] P2 完成后重录视觉基线到 `design/baselines/`，并在 `docs/README.md` 的维护规则中更新基线日期与张数。
  - 风险：`e2e/visual-regression.spec.ts` 的稳定截图比较在 P1 与 P2 后必然失败，重录基线是唯一需要事先确认的破坏性动作。
- [ ] 记录改动前后的量化结果：全局 CSS 类数量、`app.css` 行数、断点数量、`1024x768` 下内容区可用高度。
  - 说明：当前预估首屏内容区从约 570px 提升到约 660px，该数字按令牌值推算，未经浏览器实测，需在 P2 验收时以实测值替换。

## 实施顺序

1. P0 CSS 资产收敛与布局令牌，先建立干净基线。
2. P0 顶栏与底栏分工，释放顶栏横向空间。
3. P1 `PageShell` 与布局原语，先在总览与信号两页验证，再批量迁移剩余页面。
4. P1 删除失效全局网格类与各页 `.page` 规则。
5. P2 竖向预算调整与宽屏最大宽。
6. P2 断点四档收敛与夹缝态修正。
7. P2 `app.css` 拆分与文档同步。

## 每轮验收命令

```powershell
cd web
npm.cmd run test
npm.cmd run build
npm.cmd run e2e:isolated
```

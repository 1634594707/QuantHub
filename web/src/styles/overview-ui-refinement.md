# UI 精修交付概要

## 变更范围

### 1. app.css 死代码清理（-1580 行）

`web/src/styles/app.css` 从 ~2520 行精简到 ~940 行。

删除的旧样式块（对应已被 workspace-rail / context-nav 结构替代的旧 Sidebar）：
- `.brand` / `.brand-logo` / `.brand-name` / `.collapse-btn` / `.chevron-flip`
- `.nav` / `.nav-section` / `.nav-section-text` / `.nav-item` / `.nav-icon` / `.nav-badge`
- `.nav-caret` / `.nav-group` / `.nav-sub` / `.nav-subitem` / `.nav-sub-text` / `.nav-sub-label` / `.nav-sub-desc` / `.nav-sub-dot`
- `.sidebar-foot` / `.side-foot-meta` / `.side-foot-ver` / `.side-foot-clock`
- 对应的折叠态选择器和 hover/active 态

保留并精修的样式：
- App Shell / Sidebar（workspace-rail + context-nav 结构）
- Topbar（搜索 + 信号药丸 + 连接状态 + 模式指示 + 主题切换 + 头像）
- Card / KPI Row / Grid 布局
- Kline Card / Period Tabs / Zoom
- Table / Editable Lists
- Decision Panel（d-verdict / d-tabs / d-metrics / d-probs / d-trace / d-reason）
- Market Breadth / Watchlist / Pending Strip
- Data Source / Reconnect Badge / Skip Link
- 完整响应式断点（1023px / 900px / 767px）

**所有硬编码颜色值替换为 tokens 语义变量**（如 `rgba(22,199,132,0.12)` → `var(--up-weak)`）。

### 2. 文案去 AI 痕迹

| 位置 | 旧文案 | 新文案 |
|---|---|---|
| OverviewPage header | `驾驶舱 / 总览` | `驾驶舱` |
| OverviewPage header desc | `账户、行情、研究与执行状态` | `账户、行情与执行状态` |
| OverviewPage KPI labels | `自选标的` / `市场宽度 (涨/跌)` | `自选` / `涨/跌` |
| OverviewPage 数据口径 | `当前数据口径` | `数据口径` |
| OverviewPage 评估入口 tag | `新手入口` | 删除 |
| OverviewPage 评估入口 title | `综合评估一个标的` | `标的评估` |
| OverviewPage 评估入口 desc | `量化快照、新闻 AI、价格结构 AI 与模型共识汇总到同一份研究记录。` | `输入一个标的，自动汇总行情快照、新闻事件与价格结构到同一份研究记录。` |
| OverviewPage 按钮文案 | `开始综合评估` / `查看历史评估` / `连接我的数据` | `开始评估` / `历史记录` / `数据设置` |
| TradingWorkspacePage desc | `信号审核、下单、订单查询与撤单收口在此。浏览器只经 /api/trading/* 访问 OKX Runner。` | `下单、查询与撤单` |
| TradingWorkspacePage metric | `首期范围: 永续 SWAP · 限价单` | `范围: 永续 SWAP · 限价` |
| AccountRiskPage desc | `余额、持仓、风险模式、对账差异与停机操作的唯一入口，全部来自服务端真实状态。` | `余额、持仓、风险与对账` |
| StockEvaluationStartPage title | `单标的综合评估` | `标的评估` |
| StockEvaluationStartPage desc | `量化快照、AI 证据与模型共识统一归档` | `行情快照、新闻与价格结构归档到同一研究记录` |

### 3. Topbar 精简

- 信号药丸去掉 `信号` 文字标签，只留铃铛图标 + 数字
- 连接状态 tooltip 去掉策略计数冗余信息
- 模式指示从 `实盘模式` / `研究模式` 简化为 `实盘` / `研究`

### 4. OverviewPage CSS 修正

- `.evaluationEntry` 背景从旧变量 `--surface-1` 改为 `--bg-elevated`
- `.evaluationEntry` 左边框从 `4px` 改为 `3px`（更克制）
- `.evaluationEntry` 添加 `border-radius: var(--r-card)` 与其他卡片统一
- `.entryCopy h2` 字号从不存在的 `--fs-title` 改为 `--fs-h1`

### 5. 验证结果

- TypeScript 类型检查：0 错误
- 前端测试：97 tests 全部通过（24 test files）
- 生产构建：成功，1.18s

# QuantHub · 概览（Overview）单屏像素规范

> 配合 `overview.html`（高保真像素稿）使用 · 设计：UI Designer · 2026-07-23
> 用途：**React + TypeScript 1:1 还原参照**。所有尺寸为 CSS 像素（px），间距遵循 4px 基准 8pt 网格。

---

## 1. 全局骨架

| 区块 | 属性 | 值 |
|---|---|---|
| 应用栅格 | grid-template-columns | `240px 1fr`（折叠态 `64px 1fr`） |
| 侧边栏 | width / 背景 / 右边框 | 240 / `--bg-surface` / `1px var(--border-subtle)` |
| 顶栏 | height / 背景 / 底边框 | 56 / `color-mix(--bg-surface 72%, transparent)` + blur(10px) / `1px var(--border-subtle)` |
| 内容区 | max-width / padding / 纵向 gap | 1440（居中）/ 24 / 16 |
| 圆角基准 | card / button / chip | 14 / 8–9 / 999(pill) |
| 过渡 | 通用 | 160ms cubic-bezier(.16,1,.3,1) |

---

## 2. 区块像素标注

### 2.1 顶部 KPI 行（`.kpis`）
- 栅格：`repeat(4,1fr)`，gap **16**
- 卡片（`.kpi`）：padding **16/18**；内部纵向 gap **10**；hover `translateY(-2px)` + 加深阴影
- 标签 `.k-label`：12px / 600 / `--text-secondary`
- 图标 `.k-ico`：30×30 / radius 8 / 背景 `--accent-soft` / 字色 `--accent`
- 数值 `.k-val`：**26px** / 700 / `letter-spacing:-.3px` / `.mono`
- 副文案 `.k-sub`：12px / 600 / 涨绿跌红

### 2.2 主区栅格（`.grid-2`）
- 列：`1.6fr 1fr`，gap **16**，align-items:start
- 左列 = 图表卡 + 持仓表（纵向 gap 16）；右列 = 决策面板 + 市场广度 + 关注列表（纵向 gap 16）

### 2.3 K线图表卡
- 卡头：padding **14/18**，底边框 `1px var(--border-subtle)`
  - 标题 15px/700；时间周期 Tab `.tabs`：背景 `--bg-base`、边框 `1px var(--border-subtle)`、radius 9、内距 3；按钮 12px/600，active = `--accent` 实心白字
  - 「刷新」按钮 `.btn-ghost`：1px 描边、radius 8、padding 7/12、12px/600
- 卡体 padding **18**；图表 svg `width:100% height:300`
- OHLC 行：margin-top 10、12px、`.monce .sec`，收价 `--up`

### 2.4 持仓表
- 表头 `th`：11px/600/`--text-muted`/大写+字距.4px/底边框
- 单元格 `td`：padding **11/14**、13px；数字列 `.num` 右对齐；hover 行背景 `--bg-hover`
- 胜率 `.bar`：高 6 / radius 999 / 轨道 `--bg-hover`；填充 `--accent`
- 信号用 `.badge`（up/down/warn/info/neutral 五态）

### 2.5 PA 决策面板
- 网格 `.dec-grid`：`1fr 1fr`，gap **12**
- 单元 `.dec-item`：padding **10/12**、背景 `--bg-base`、边框 `1px var(--border-subtle)`、radius 10
- 键 `.d-k`：11px/600/`--text-muted`；值 `.d-v`：14px/600
- `.span2` 跨两列；理由 `.reason`：13px/`--text-secondary`/行高 1.55

### 2.6 市场广度卡
- `.breadth-bar`：高 10 / radius 999 / 轨道 `--bg-hover`
- 三段：涨 `--up` 62% / 平 `--text-muted` 7% / 跌 `--down` 31%（示例值，动态）
- 图例 `.breadth-legend`：margin-top 10、12px/600

### 2.7 关注列表卡
- `.wl-row`：纵向 padding 10、横向 4、底边框；末行无边框
- 代码 `.wl-sym` 13px/600；名称 `.wl-name` 11px/`--text-muted`
- 价格 `.wl-price` 13px/600 右对齐；涨跌 `.wl-chg` 12px/600 右对齐 min-width 56

---

## 3. React + TSX 组件树（开发映射）

```
<AppShell theme="dark|light">                 // 持有 data-theme，提供 ThemeContext
 ├─ <Sidebar collapsed={bool}>                 // 240↔64，nav 高亮 aria-current
 │   ├─ <Brand/>
 │   ├─ <NavGroup><NavItem/></NavGroup> × N
 │   └─ <UserFooter/>
 └─ <Main>
     ├─ <Topbar onToggleTheme onToggleSidebar>
     │   ├─ <IconButton/>  ├─ <PageTitle sub="日期"/>
     │   ├─ <SearchBox/>  ├─ <MarketStatusPill dot/>
     │   ├─ <ThemeToggle/> └─ <IconButton/>
     └─ <PageContainer maxW=1440 gap=16>
         ├─ <KpiRow>
         │   └─ <KpiCard label icon value delta/> × 4
         └─ <Grid cols="1.6fr 1fr" gap=16>
             ├─ <LeftCol gap=16>
             │   ├─ <CandlestickCard>            // 自绘 SVG：蜡烛+成交量+最新价标签
             │   │   ├─ <CardHeader><Tabs/></CardHeader>
             │   │   └─ <Chart height=300/>
             │   └─ <HoldingsTable>             // 语义色 + 胜率 Bar
             └─ <RightCol gap=16>
                 ├─ <DecisionPanel items={...}/> // 数据来自 view_models.build_decision_view
                 ├─ <MarketBreadth up/flat/down/>
                 └─ <Watchlist rows={...}/>
```

**数据契约（与现有代码对齐）**
- `DecisionPanel` 直接消费 `pa_agent.view_models.build_decision_view()` 输出（已在 Web 端抽离，零 PyQt 依赖）
- KPI / 持仓 / 关注列表 / 市场广度 由 Overview 页面容器通过数据 Hook（如 `useOverview()`）获取

**还原验收门槛**
- 间距/字号/圆角与本文档一致度 ≥ 95%
- 暗↔亮切换无闪烁、对比度达标（正文 ≥ 4.5:1）
- 所有交互态（hover/active/focus/disabled）与 `design-system.md` §4.8 一致

---
**UI Designer** · 概览像素规范 v0.1 · 2026-07-23 · 就绪供 React 开发对接

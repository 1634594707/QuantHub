# QuantHub 量化平台 · UI 设计系统

> 版本 v0.1 · 设计日期 2026-07-23 · 设计：UI Designer
> 适用范围：量化平台 Web 端全新重构（React/Vue 自研前端）
> 主题策略：**暗色为主、亮色可选**，默认暗色（契合长时间盯盘与数据聚焦）

---

## 1. 设计原则（Design Principles）

| 原则 | 说明 |
|---|---|
| 数据优先 | 行情、收益、信号是主角；chrome（导航/边框）退居背景，降低视觉噪声 |
| 暗色护眼 | 默认暗色基调 `#0B1018`，减少长时间盯盘的视觉疲劳 |
| 一致即专业 | 全站统一间距网格、圆角、语义色，杜绝「装配感」 |
| 密度可控 | 信息密集但不拥挤，8pt 网格保证呼吸感 |
| 可达性内建 | 默认满足 WCAG 2.1 AA（正文对比度 ≥ 4.5:1） |

---

## 2. 设计基座（Design Tokens）

### 2.1 颜色系统

> 以 CSS 变量承载双主题。暗色 token 落在 `:root[data-theme="dark"]`，亮色在 `:root[data-theme="light"]`。

**暗色主题（默认）**
```
--bg-base:        #0B1018   /* 应用底色 */
--bg-surface:     #0F1620   /* 卡片/面板 */
--bg-elevated:    #16202E   /* 浮层/下拉 */
--bg-hover:       #1B2735   /* 行 hover */
--border-subtle:  rgba(255,255,255,0.08)
--border-strong:  rgba(255,255,255,0.16)

--text-primary:   #E6EDF3
--text-secondary: #9AA7B5
--text-muted:     #5C6B7A

--accent:         #5B8DEF   /* 主品牌色（冷静蓝） */
--accent-hover:   #7AA2F7
--accent-soft:    rgba(91,141,239,0.14)

--up:             #16C784   /* 涨/盈利（绿） */
--down:           #EA3943   /* 跌/亏损（红） */
--warning:        #F5A623
--info:           #5B8DEF
```

**亮色主题**
```
--bg-base:        #F5F7FA
--bg-surface:     #FFFFFF
--bg-elevated:    #FFFFFF
--bg-hover:       #EEF2F7
--border-subtle:  rgba(15,22,32,0.08)
--border-strong:  rgba(15,22,32,0.16)

--text-primary:   #0F1620
--text-secondary: #4A5563
--text-muted:     #8A97A6

--accent:         #2F6BDF
--accent-hover:   #1F56C2
--accent-soft:    rgba(47,107,223,0.10)

--up:             #0E9F6E
--down:           #DC2626
--warning:        #D97706
--info:           #2F6BDF
```

**语义色契约（跨主题恒定含义）**
- 涨 / 盈利 / 多头 → `--up`（绿）
- 跌 / 亏损 / 空头 → `--down`（红）
- 警告 / 待处理 → `--warning`（琥珀）
- 信息 / 主操作 → `--accent`（蓝）

> 可达性：暗色下 `--text-primary`(#E6EDF3) 对 `--bg-base`(#0B1018) 对比度 ≈ 15:1；亮色下 ≈ 14:1，均远超 AA 4.5:1。涨绿 `#16C784` 对暗底 ≈ 7:1，跌红 `#EA3943` 对暗底 ≈ 5.3:1，达标。

### 2.2 字体系统

| 角色 | 字体 | 用途 |
|---|---|---|
| 主要 / 标题 / UI | Plus Jakarta Sans | 导航、标题、正文、按钮 |
| 等宽 / 数字 | JetBrains Mono | 价格、收益率、代码、时间戳 |

**字号阶梯（8pt 节奏对齐）**
```
12 / 14 / 16 / 18 / 20 / 24 / 30 / 36 px
  ↕    ↕    ↕    ↕    ↕    ↕    ↕    ↕
xs   sm   base  lg   xl   2xl  3xl  4xl
```
- 字重：400（正文）/ 500（UI 控件）/ 600（小标题）/ 700（大标题）
- 数字一律 `font-variant-numeric: tabular-nums`，保证列对齐、跳动不抖。

### 2.3 间距系统（4px 基准 · 8pt 网格）

```
4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px
```
- 卡片内边距：16–24px；卡片间距：16–24px；区块间距：32–48px。

### 2.4 圆角 / 阴影 / 过渡

```
--radius-sm: 8px    --radius-md: 12px   --radius-lg: 16px
--shadow-card: 0 1px 2px rgba(0,0,0,.2), 0 8px 24px rgba(0,0,0,.25)  /* 暗色 */
--transition: 160ms cubic-bezier(.16,1,.3,1)
```
- 微交互：hover 轻微上浮 `translateY(-2px)` + 阴影加深；尊重 `prefers-reduced-motion`。

---

## 3. 信息架构（Information Architecture）

```
QuantHub
├─ 概览 Dashboard        （资产总览 / KPI / 持仓 / 精选信号）
├─ 信号 Signals           （实时信号流 / 筛选）
├─ 回测 Backtest          （策略回测配置与曲线）
├─ 策略模块 Strategies     （策略注册表 / 启用开关）
├─ PA 分析工作台          （K线 + 决策树 + 决策 + 未来走势 + 指标卡）★新增
└─ 配置 Settings          （数据源 / API Key / 主题）
```

**布局骨架**：左侧可折叠侧边栏（240px ↔ 64px）+ 顶栏（48–56px）+ 主内容区（自适应栅格）。

---

## 4. 核心组件库（Component Library）

### 4.1 侧边栏导航（Sidebar）
- 折叠态仅留图标（64px），展开态 240px，过渡 160ms。
- 当前页：左侧 3px accent 指示条 + `accent-soft` 背景。
- 分组标题用 `--text-muted`、11px、字间距加宽。

### 4.2 顶栏（Topbar）
- 左侧：页面标题 + 面包屑；右侧：全局搜索、市场状态徽章（开盘绿点/休市灰点）、主题切换、用户头像。
- 市场状态用 `--up` 绿点表示「交易中」，`--text-muted` 表示「休市」。

### 4.3 KPI 指标卡（Metric Card）
- 结构：标签（secondary）+ 主数值（JetBrains Mono, 24–30px）+ 环比徽章（▲绿/▼红, 带符号与百分比）。
- hover 上浮 + 阴影。

### 4.4 图表卡（Chart Card）
- 标题行：名称 + 时间周期 Tab（1m/5m/1h/1d）+ 更多菜单。
- K 线用 SVG 蜡烛（涨绿跌红），含网格、坐标、最新价标签。
- 加载态：骨架屏 shimmer；空态：「暂无数据」+ 引导按钮。

### 4.5 PA 决策面板（Decision Panel）★新增
- 展示 `view_models.build_decision_view` 输出：趋势 / 周期 / 阶段 / 双向置信度 / 方向 / 三价位（止损/入场/止盈）/ 盈亏比 / 胜率 / 理由。
- 用键值对网格 + 语义色徽章，方向用 ▲/▼ 强化。

### 4.6 数据表（Data Table）
- 斑马纹（hover 高亮），数字列右对齐 + tabular-nums。
- 涨绿跌红单元格，胜率用进度条。
- 排序表头、行内操作（查看/编辑）。

### 4.7 基础控件
- **按钮**：primary（accent 实心）/ secondary（描边）/ ghost（纯文字）；尺寸 sm/md。
- **输入框 / 下拉**：focus 时 accent 边框 + `accent-soft` 光环。
- **徽章 Badge**：up/down/warning/info/neutral 五态。
- **Toast**：右下角，自动消失，含成功/错误/警告三态。

### 4.8 组件状态契约
| 状态 | 表现 |
|---|---|
| default | 标准底色/边框 |
| hover | 上浮 2px + 阴影加深 / 背景 `--bg-hover` |
| active | 背景 `--accent-soft` |
| focus | 2px accent 轮廓 + 2px offset（键盘可见） |
| disabled | 透明度 .55 + `cursor: not-allowed` |
| loading | 骨架屏 / spinner |
| error | `--down` 边框 + 行内错误文案 |

---

## 5. 响应式策略（Responsive）

| 断点 | 宽度 | 行为 |
|---|---|---|
| Mobile | < 640px | 侧边栏抽屉化（汉堡），KPI 单列，表格横向滚动 |
| Tablet | 640–1023px | 侧边栏自动折叠，KPI 2 列 |
| Desktop | 1024–1279px | 完整侧边栏，KPI 4 列，主区 2 栏 |
| Large | ≥ 1280px | 主区可扩为 3 栏，留白加大 |

栅格：12 列弹性栅格；容器最大宽 1440px 居中。

---

## 6. 可达性（Accessibility · WCAG 2.1 AA）

- **对比度**：正文 ≥ 4.5:1，大字 ≥ 3:1（已达标，见 §2.1）。
- **键盘**：全功能可 Tab 操作，focus 轮廓清晰，逻辑 tab 顺序。
- **屏幕阅读器**：语义标签（nav/main/aside/table[scope]）+ ARIA（`aria-current`、`aria-label`）。
- **触控目标**：交互元素 ≥ 40×40px（按钮 md 高度 40px）。
- **动效降级**：`prefers-reduced-motion: reduce` 时关闭位移/淡入，仅保留必要状态变化。
- **文本缩放**：布局支持浏览器 200% 缩放不破版。

---

## 7. 交付与开发对接（Handoff）

1. **Token 即源码**：上述 CSS 变量直接迁移为 `:root` + `[data-theme]`，React/Vue 用 CSS Modules 或 Tailwind theme 扩展复用。
2. **组件粒度**：每个组件给出尺寸标注 + 状态矩阵 + 间距标注，供前端 1:1 还原。
3. **原型先行**：`design/prototype.html` 为单文件可点击原型，含暗/亮切换，作为视觉基线。
4. **QA 门槛**：还原度 ≥ 90%；主题切换无闪烁；所有交互态与文档一致。

---
**UI Designer** · QuantHub Design System v0.1 · 2026-07-23 · 已就绪进入开发对接

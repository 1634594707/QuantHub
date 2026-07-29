# QuantHub Web UI 控制文档

> 本文档只记录当前 React 前端的入口和样式真值源。路由以 `web/src/main.tsx` 为准，工作区映射以 `web/src/navigation/workspaces.tsx` 为准，颜色以 `web/src/styles/tokens.css` 为准。

## 1. 工作区导航

| 一级工作区 | 二级入口 |
|---|---|
| 驾驶舱 | 总览 |
| 研究 | 标的研究、新闻分析、PA 分析、分析任务 |
| 策略 | 策略库、策略实验室、协同预测、策略分配 |
| 执行 | 信号中心、模拟执行、账户与账本 |
| 运营 | 标的中心、自动化中心、系统配置 |

桌面由 64px 一级工作区图标轨和当前工作区二级导航组成。移动端固定显示驾驶舱、研究、信号、更多四入口；“更多”打开完整工作区导航。

## 2. 路由与页面标识

| 路由 | `data-board` | 页面职责 |
|---|---|---|
| `/` | `overview` | 总览、行情、关注、研究持仓和 PA 快捷分析 |
| `/research/:symbol` | `research` | 标的研究、新闻、PA、共识和研究历史 |
| `/news` | `news` | 独立新闻分析 |
| `/pa` | `pa` | 独立 PA 两阶段分析 |
| `/ensemble` | `ensemble` | 协同预测与信号生成 |
| `/tasks` | `tasks` | 持久化分析任务 |
| `/strategies` | `library` | 策略库 |
| `/strategies/:name` | `workbench` | 策略详情、运行与回测 |
| `/strategy-lab` | `strategy-lab` | 策略定义、版本、实验和回测对比 |
| `/signals` | `signals` | 信号发布、审核与模拟订单入口 |
| `/simulation` | `simulation` | 模拟订单、成交和模拟账户 |
| `/ledger` | `ledger` | 现金、成交、持仓、绩效、敞口和基准 |
| `/instruments` | `instruments` | Instrument 搜索、解析和登记 |
| `/portfolio` | `portfolio` | 策略分配，不承担账本真值 |
| `/automation` | `automation` | 调度配置清单与运行态边界 |
| `/config` | `config` | 网关、模型密钥、数据源和运行入口 |

开发环境还注册 `/__ui` 组件展示页，生产构建不注册该路由。

## 3. 样式真值源

| 文件 | 责任 |
|---|---|
| `web/src/styles/tokens.css` | 暗色/亮色主题、文本、边框、语义色、间距、字号、圆角和动效令牌 |
| `web/src/styles/board.css` | 保留 `data-board` 页面语义，并统一映射到固定交互色 |
| `web/src/styles/base.css` | HTML 元素、表单和基础可访问性行为 |
| `web/src/styles/app.css` | 应用壳层、侧边栏、顶栏、主内容布局和仍在使用的共享旧组件样式 |
| `web/src/styles/strategy-module.css` | 由策略页面和共享策略组件按需加载的策略布局 |
| `web/src/components/StatusBar/StatusBar.module.css` | 底部运行状态与移动端隐藏规则 |
| `web/src/components/SignalViz.module.css` | 方向分布、分数分布和来源分布图 |
| `web/src/pages/*.module.css` | 页面局部样式，避免全局类名扩散 |

`web/src/main.tsx` 只全局导入 `tokens.css`、`base.css`、`board.css` 和 `app.css`；研究、新闻、任务、模拟、协同预测和策略领域样式由精确使用它们的页面或组件加载。新增路由时必须同时更新 `App.tsx` 的 `boardForPath()` 与 `navigation/workspaces.tsx` 的精确工作区映射。页面归属不得改写 `--accent`。

## 4. 组件入口

- 通用控件位于 `web/src/components/ui/`，包括 Button、Input、Select、Table、Modal、SegmentedControl 和 EmptyState。
- 全局命令入口位于 `web/src/components/CommandPalette/`。
- 底部运行信息位于 `web/src/components/StatusBar/`。
- 紧凑页头位于 `web/src/components/WorkspaceHeader/`，所有独立业务页统一使用。
- 研究上下文与证据分别位于 `web/src/components/ContextBar/`、`web/src/components/EvidenceRail/`。
- 驾驶舱统一待处理事项位于 `web/src/components/ActionQueue/`。
- 新闻组件位于 `web/src/components/news/`。
- 页面只组合领域数据和交互；可复用控件状态应留在通用组件或对应 hook 中。

## 5. 布局规则

- 页面板块使用全宽区带或无外框布局；卡片只用于重复项目、模态框和需要明确框定的工具。
- 不在同类卡片内继续嵌套同类卡片。子区域使用无边框分组和标题层级区分。
- 表格、标签页和工具栏必须设置稳定尺寸或溢出策略，避免动态数据导致布局位移。
- 小屏幕下表格允许横向滚动；表单由双列收敛为单列；按钮文字不得溢出容器。
- 涨跌、盈亏和方向颜色使用 `tokens.css` 的语义变量，不在页面文件中另建含义相反的颜色。
- 独立业务页桌面页头高度不得超过 72px；页面标题使用 20px/600。
- 一级工作区固定为五个，移动底栏固定为四个入口；新增业务页先归入现有工作区。

## 6. 验证

```powershell
cd web
npm.cmd run typecheck
npm.cmd run build
```

当前精简版以 TypeScript 类型检查、生产构建和人工网页验收为准。

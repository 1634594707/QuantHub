# QuantHub 前端细节优化路线图

> 建立日期：2026-07-27
>
> 目标：在不改变现有 React、React Router、API 数据真值与暗色终端设计方向的前提下，降低高频检索、审核、执行、对账和故障处理的操作成本。
>
> 状态规则：`[x]` 表示页面实现、交互反馈和相应测试均已完成；`[ ]` 表示仍未形成可验收闭环。
>
> 证据边界：条目只使用当前仓库中的组件、路由、类型、测试和样式作为依据，不推测未定义字段或接口。

## P0：高频入口与反馈

### 全局业务检索

- [x] 将 `web/src/components/CommandPalette/CommandPalette.tsx` 从静态页面过滤改为分组业务检索。
  - 精确数据源：`api.instruments()`、`api.strategyLabDefinitions()`、`api.strategyLabExperiments()`、`api.researchRuns()`、`api.signals()`、`api.simulationOrders()`。
  - 分组：快捷操作、页面、标的、策略定义、策略实验、研究运行、信号、模拟订单。
- [x] 为命令面板增加输入防抖、加载状态、部分接口失败提示、空结果和重新检索反馈。
- [x] 保留 `ArrowUp`、`ArrowDown`、`Enter`、`Escape` 键盘操作，并确保活动结果自动滚入可见区域。
- [x] 让业务结果打开精确记录，而不是只进入板块首页。
  - URL 状态：`run_id`、`definition_id`、`experiment_id`、`signal_id`、`order_id`、`status`、`action`。
- [x] 提供“新建研究”“创建实验”“进入待审核信号”的直接动作。
- [x] 增加命令面板交互测试，覆盖分组结果、键盘导航、加载、空结果和部分接口失败。
  - 验证：`web/src/components/CommandPalette/CommandPalette.test.tsx`、`web/e2e/command-palette.spec.ts`。
- [x] 为移动端顶栏提供具备可访问名称的全局检索图标按钮，并验证 `390x844` 面板无横向溢出。

### 页面状态一致性

- [x] 将筛选、当前记录和工作视图保存在 URL 中，使刷新、返回和分享链接后仍能恢复当前上下文。
  - 信号：`q`、`direction`、`market`、`source`、`status`、`signal_id`。
  - 模拟订单：`q`、`status`、`order_id`。
  - 标的研究：`market`、`tf`、`view`、`run_id`、`favorite`、`compare_run_id`。
  - 策略实验室：`definition_id`、`experiment_id`、`action`。
- [x] 为页面级异步请求统一“首次加载、保留旧数据重连、确定失败、空数据”四种反馈。
  - 统一组件：`web/src/components/ui/AsyncStateBoundary/AsyncStateBoundary.tsx`。
  - 接入范围：总览、分析任务、策略库、策略详情、策略分配、策略实验室、信号、模拟订单、账本、标的中心、自动化、故障、系统配置与研究历史。
  - `web/src/api/useApi.ts` 使用 `resetKey` 区分业务上下文变化与同一请求刷新；跨标的或跨记录时清空旧数据，同一上下文刷新和重连时保留上次成功数据。
- [x] 统一刷新按钮的忙碌状态、完成反馈和最后更新时间位置。
  - 实现：`RefreshControl` 统一刷新、重连和 `updatedAt` 展示。
- [x] 统一破坏性操作的确认层级，并在操作完成后保留可追溯结果。
  - 实现：`ConfirmActionButton` 接入删除、取消、移除和重置操作。

### 键盘与焦点

- [x] 为审核队列、故障记录、模拟订单和研究历史建立一致的上下选择与打开行为。
  - 实现：`web/src/hooks/useRecordNavigation.ts`。
- [x] 解决 Windows Chrome 占用 `Ctrl+K` 打开地址栏搜索的问题，并为全局检索确定不冲突的跨平台快捷键。
  - 实现：使用 `Ctrl/Cmd+Shift+K`；2026-07-27 运行时键盘事件验证该组合可到达页面。
- [x] 对话框打开后锁定焦点，关闭后把焦点还给触发按钮。
  - 实现：支持 `Tab`、`Shift+Tab` 循环，`Escape` 关闭后恢复触发按钮焦点，并完成桌面与 `390x844` 验收。
- [x] 所有仅图标按钮提供可访问名称和悬停说明；焦点轮廓在深色与浅色主题下均可见。

## P0：移动端高频操作

- [x] 将分析任务、模拟订单、账本成交和现金流水从横向表格改为主次两行记录，详细字段按需展开。
- [x] 信号审核在 `390x844` 视口完成筛选、选择、填写备注、接受或拒绝和进入下一条记录。
- [x] 模拟订单在 `390x844` 视口完成筛选、查看成交进度、录入成交和重试账本同步。
- [x] 移动端固定操作区避开底部导航和安全区域，不遮挡输入、错误消息或最后一条记录。
- [x] 上述核心路径已完成 `390x844` 操作验收，不只检查页面宽度。

## P1：账户、策略与运营页面

### 账户与账本

- [x] 账本首屏优先展示账户变化、持仓和最近流水，录入表单按需展开。
- [x] 基准权益曲线与指标改为受控字段，不再要求直接输入 JSON 文本。
- [x] 持仓、成交、现金、绩效和基准使用一致的数值对齐、时间格式与空值表示。
- [x] 持仓与绩效指标可下钻到组成成交、现金流水和关联研究记录。

### 策略工作区

- [x] 策略库改为可排序、可筛选的扫描列表，保留快速运行、回测和详情入口。
- [x] 策略详情的参数、运行、停止状态和最近结果保持在固定操作区。
- [x] 策略实验室按“定义与版本、实验、运行与比较”分区，减少纵向往返。
- [x] 由策略参数结构生成受控表单，替代版本参数和实验参数 JSON 文本框。

### 故障与配置

- [x] 故障记录在当前页完成可执行动作，并显示动作进行中、成功、失败和重试结果。
- [x] 数据源状态展示最近成功时间、最近错误、调用次数和错误率，并支持单源检查。
  - 精确接口：`POST /market-data/check`。
- [x] 配置保存前显示影响范围，保存后显示实际生效状态与精确错误。

## P2：视觉与性能收口

- [x] 将命令面板从 `web/src/styles/terminal.css` 迁移到同目录 CSS Module，收紧全局样式影响范围。
  - 实现：`web/src/components/CommandPalette/CommandPalette.module.css`。
- [x] 统一页面标题、上下文、主操作和最后更新时间的高度与对齐规则。
- [x] 统一表格、记录列表、表单和状态标签的密度级别，避免动态内容引发布局跳动。
- [x] 检查并移除仅用于说明界面功能的可见文案，保留任务、状态、风险和业务数据。
- [x] 按路由拆分大型页面代码，记录生产构建的 JS 与 CSS 体积变化。
  - 路由拆分前入口 JS：505.15 kB（gzip 158.35 kB）。
  - 当前 JS 总计 587,502 bytes、CSS 总计 182,964 bytes；入口 JS 289,261 bytes（gzip 91.83 kB），入口 CSS 52,988 bytes（gzip 10.28 kB）。
  - 总量超过旧 Phase 1 的 5% 上限，构建块来源与无法逐块反算的边界记录在 `design/FRONTEND_REDESIGN_PLAN.md`。
- [x] 在 `1440x900`、`1024x768`、`768x1024`、`390x844` 视口完成截图回归。
  - 结果：`design/baselines/2026-07-27/` 共 24 张 PNG。

## 每轮验收

- [x] `npm.cmd run test`：77/77 通过。
- [x] `npm.cmd run typecheck`：通过。
- [x] `npm.cmd run build`：通过；体积以本路线图上方的最终文件统计为准。
- [x] `npm.cmd run e2e:isolated`：52/52 通过，包含桌面业务检索、移动端核心操作、四视口布局、访问治理、axe、稳定截图与研究到对账闭环。
- [x] 后端全量回归通过；本机缺少 PostgreSQL 服务时 1 项 PostgreSQL 回归明确跳过。
- [x] 同步 `USER_FUNCTIONAL_ROADMAP.md`、根 `README.md` 与 `docs/README.md`。

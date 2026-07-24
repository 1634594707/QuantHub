# 策略工作台 · 功能确认与更新地图

> 目的：确认策略工作台（StrategyDetailPage，5 Tab）当前"哪些是真功能、哪些是框架"，并给出后续更新的清晰地图。
> 确认基线：2026-07-24 代码快照（web/ + apps/api/ + strategies/ + core/）。

## 0. 一句话结论

**前端策略工作台不是空壳**——"运行策略"会真实调用后端 `produce()` 计算出 TA 信号并返回，5 个 Tab 已端到端打通。
你感觉"只是框架"，准确地说是指 **持久化 / 预设 UI / 实盘 / 回测集成 / 信号中心数据源** 这几层还是脚手架——逻辑或类型有了，UI 或后端没接。

---

## 1. 真实可用的部分（已逐字节核实）

### 1.1 运行链路（核心真功能，端到端验证）

```
浏览器 POST /strategies/{name}/run {params}
  → 网关 _call_produce() 用 inspect 反射，只传 produce() 接受的参数
  → strategy.produce() 真实计算
       （如 SuperTrend：core.data_feed 拉 K 线 → st_ind.supertrend() → 构造 Signal）
  → _signal_to_dict() 映射 → RunResp { ok, name, count, signals[] }
  → 前端 SignalResults / DirectionDonut / ScoreHistogram / SignalRow 消费真实数据
```

**契约对齐**：前端 `SignalResp` 的 10 个字段（symbol/market/timeframe/direction/score/confidence/source/tags/meta/ts）与后端 `_signal_to_dict` **逐字段一致**，`RunResp` 也一致。无字段漂移。

### 1.2 各 Tab 现状

| Tab | 真实能力 | 数据源 |
|---|---|---|
| 概览 | ✅ 策略说明 / 市场 / 实盘 / 预设数 / 运行次数 / 最近运行 / 上次信号数（6 瓦片真实） | registry + localStorage(runs/presets) |
| 参数 | ✅ `paramFields` 按策略渲染表单 + JSON 兜底编辑器，改动即时生效 | 本地 state |
| 运行 | ✅ 调真实接口，显示成功 / 失败 / 空结果三态 | `/strategies/{name}/run` |
| 历史 | ✅ 本地运行记录 + "恢复结果与参数" | localStorage(runs) |
| 信号 | ✅ 读本次运行结果或最近一次运行 → 方向环图 / 分数分布 / 方向筛选 / 排序 | localStorage(runs) |

### 1.3 可视化组件（真）

`DirectionDonut`（CSS conic-gradient 零依赖）、`ScoreHistogram`（10 桶）、`SourceBars`（跨策略分布）——均无第三方依赖，暗/亮主题自适应。

---

## 2. 真正的"框架"缺口

| # | 缺口 | 现状 | 影响 |
|---|---|---|---|
| **G1** | 参数预设 UI 缺失 | hook `save`/`remove` 已写好，但页面**从未调用**，仅概览显示预设数量 | 预设功能半成品：逻辑有、界面无 |
| **G2** | 持久化全在 localStorage | runs/presets 仅浏览器本地，无后端 `/presets`、无账号维度 | 换浏览器/清缓存即丢，无法团队协作 |
| **G3** | 信号双源不统一 | 工作台"信号"Tab 读 localStorage 运行结果；信号中心读全局 `/signals` 总线；两源互不打通 | 中心页默认空 |
| **G4** | 全局信号总线无自动灌入 | 总线靠 `produce()` 内 `self.publish()` 写入；无调度/定时运行，**开箱即空** | 信号中心需手动触发才有数据 |
| **G5** | 实盘未接 | `live_capable` 标志有、`live_tick()` 是 no-op、`okx_grid.live` 透传但无执行后端 | 不可实盘 |
| **G6** | 回测未接入工作台 | `backtest()` 真实存在（supertrend 用 EventEngine），但 `/backtest` 是独立最小页 | 工作台无法回测 |
| **G7** | 组合管理未建 | Task #68 第二部分 | 无 |
| **G8** | 无定时/自动运行 | 全手动 | 无法做"每日自动扫描" |

---

## 3. 更新地图（要改哪、改哪里）

### G1 补预设 UI（最小改动、立刻见效）
文件：`web/src/pages/StrategyDetailPage.tsx`
- 参数 Tab：加预设名输入框 + 「保存预设」按钮 → 调 `save(name, presetName, params)`
- 参数/概览 Tab：加预设下拉（`forStrategy`）→ 选中即 `setParams(preset.params)`；每项「删除」→ `remove(name, id)`
- 代码骨架已具备，只差把 `save`/`remove` 接到按钮上。

### G2 后端持久化（若要团队协作）
- 新增 `POST/GET /strategies/{name}/presets`、`/strategies/{name}/runs` 落盘
- 前端 hook 改为优先读后端、localStorage 兜底

### G3/G4 统一信号源（让信号中心开箱即用）
- 推荐方案：工作台"信号"Tab 也读全局 `/signals?source={name}`，中心页默认就非空
- 备选：运行后增加"是否发布到总线"开关

### G5/G6/G7
- 见 `design/strategy-module-design.md` 的 P1/P2 规划

---

## 4. 代码质量观察（团队提升视角）

### 好的实践（保持）
- 端到端契约用 TS interface 与后端 `_signal_to_dict` 严格对齐，类型安全
- `_call_produce` 用 inspect 反射兼容异构 `produce()` 签名——插件式架构解耦好
- 可视化零依赖（conic-gradient / 纯 CSS），性能与可维护性佳
- 方向色**恒定语义**（绿涨红跌），不随主题漂移——可读性纪律好
- 空态/加载态/错误态齐全，不伪装数据（crypto 无源标"无行情"）

### 需要收紧（带团队改）
1. **半成品代码要清理或补全**：`save`/`remove` 导入但 0 调用，是典型"写了框架忘了接"。规则：要么接上 UI，要么删掉 hook 以免误导后续维护者。
2. **两个信号源是架构债**：G3 的双源未来谁维护都会困惑。应在架构层统一为一个 `SignalSource` 抽象。
3. **魔法字符串重复**：`direction === 'buy' || 'bullish'` 在 `SignalViz`/`StrategyShared`/`StrategyDetailPage` 共 4 处重复。建议抽到 `strategy-shared.ts` 的单一来源 `dirBucket()`/`directionColor()`。
4. **localStorage 作为"真源"**：runs/presets 把浏览器当数据库。若有多端需求，应后置到后端，前端只做缓存层。规则：持久化边界要在架构图里画清楚。
5. **Tab 内联大函数**：`SignalResults` 在 StrategyDetailPage 顶部定义——建议下沉为 `components/SignalResults.tsx` 独立组件，归属更清晰（虽已在复用，但组件边界模糊）。

---

## 5. 建议的下一步（按"便于后续更新"的目标）

1. **立即补 G1 预设 UI**（约 0.5 天，纯前端，消除半成品）
2. **统一 G3/G4 信号源**（让信号中心开箱即用）
3. **清理 G2 持久化边界 + 抽 `dirBucket` 单一来源**（消除重复/架构债）
4. 再上实盘 G5 / 回测 G6 / 组合 G7（P1/P2）

---

## 附：文件清单（更新时按图索骥）

| 关注点 | 文件 |
|---|---|
| 工作台页面 | `web/src/pages/StrategyDetailPage.tsx` |
| 共享组件/参数表单 | `web/src/components/StrategyShared.tsx` |
| 可视化组件 | `web/src/components/SignalViz.tsx` |
| 工作台/信号样式 | `web/src/styles/strategy-module.css` |
| 运行历史 hook | `web/src/hooks/useStrategyRuns.ts` |
| 预设 hook | `web/src/hooks/useStrategyPresets.ts` |
| 类型契约 | `web/src/api/types.ts` |
| API client | `web/src/api/client.ts` |
| 后端运行端点 | `apps/api/main.py`（`run_strategy` / `_call_produce` / `_signal_to_dict`） |
| 策略基类 | `strategies/base.py`（`StrategyBase.produce/backtest/live_tick`） |
| 信号总线 | `core/signals/__init__.py`（`SignalBus.publish/history`） |
| 具体策略示例 | `strategies/a_shares/supertrend/strategy.py` |

# QuantHub 概览屏 · 前后端联调 + 实时面板 + 决策面板（完成）

## 完成范围

- **Task #20**：K 线端点 + 缓存缺陷修复 + 前端数据层 + 概览屏基础接入（实时 / 降级）
- **Task #21**：补齐 KPI / 持仓 / 市场广度 / 关注列表 四个实时面板
- **Task #22**：UI 微调 + 侧边栏可折叠
- **Task #23**：决策面板接入真实 PA 两阶段分析（带 mock 降级）

## 后端端点（`apps/api/main.py`）

| 端点 | 方法 | 返回 | 真实数据来源 |
|------|------|------|--------------|
| `/health` | GET | 11 策略 + `live_trading` | `strategies.discover_and_register()` |
| `/data/kline` | GET | `candles[240]` + `source` | `core.data_feed.get_kline` |
| `/portfolio` | GET | summary + 5 持仓（实时价） | `_latest_close(600519/300750/000858/002594/601318)` |
| `/market/breadth` | GET | up/flat/down + 行业 | 静态（可后续接在线源） |
| `/market/watchlist` | GET | 4 关注（可用处真实价） | NVDA / AVGO / 600036 / BTC-USDT |
| `/strategies/pa_agent/analyze` | POST | decision / future / tree / stage1 / stage2 | `run_two_stage` + `pa_agent.view_models` |

> 注：网关需 `apps/api/pyproject.toml` 含 `quanthub-apps-pa-agent` workspace 依赖，方可 `import pa_agent`。
> `analyze` 端点无 `DEEPSEEK_API_KEY` 时返回 `ok:false` 并优雅降级（前端显 mock 决策 + 提示）。

## 前端组件（`web/src`）

- **数据层**：`api/types.ts`、`api/client.ts`、`api/useApi.ts`（返回 `{data, loading, error, refetch}`）
- **KpiRow**：真实 portfolio → 4 KPI（账户净值 / 今日盈亏 / 持仓胜率 / 可用资金），null 回退 `KPIS`
- **HoldingsTable**：真实持仓，空回退 `HOLDINGS`
- **MarketBreadth**：真实广度，回退 `BREADTH` / `SECTORS`
- **Watchlist**：真实关注，回退 `WATCH`
- **Sidebar**：`collapse-btn` 折叠（chevron 旋转 180°）、移动端 `mobile-open`
- **App**：聚合 `portfolio` / `breadth` / `watchlist` / `decision` 四路 `useApi`
- **DecisionPanel**：`analyzePa(symbol,'1h')` → `mapPaToDecision`；按钮 `refetch()`；无 Key 显 mock

## 验证结果

| 检查项 | 结果 |
|--------|------|
| Vite `:5173` | HTTP 200，渲染完整 |
| FastAPI `:8000` | HTTP 200 |
| `/health` | 11 策略 |
| `/data/kline?symbol=600519&interval=1h&limit=240` | `ok=true`、`source=local`、`count=240` |
| `/portfolio` | nav 994668 / 5 持仓 |
| `/market/watchlist` | 4 条 |
| `/strategies/pa_agent/analyze` | `ok:false` 优雅降级（无 DeepSeek Key） |
| `tsc --noEmit` | 通过 |
| `ruff check apps/api/main.py` | All checks passed |
| DOM 标记 | 实时×4 / 模拟×2 / 研究模式×1 / 运行PA分析×3 / 账户净值×1 / 持仓明细×1 / 市场广度×1 / 关注列表×1 / 策略模块×2 |
| 截图证据 | `D:\tmp\quanthub_v2.png` / `quanthub_collapsed.png` / `quanthub_final.png` |

## 关键决策

- **离线优先 / 优雅降级**：所有面板保留 mock 路径，网关 / Key 不可用时自动降级并显「模拟」徽章，保证 UI 可独立演示。
- **缓存 key 必须含请求参数**：`core/data_feed/cache.py` 已修复（追加 `limit`），这是真实工程质量隐患。
- **侧边栏折叠态类挂到 `<aside>` 自身**：修复折叠态 DOM 不反映的渲染 bug。
- **决策面板暂不强制真数据**：PA 决策需 DeepSeek Key，当前设计为「拿到 Key 即显真实分析，否则显 mock + 提示」。

## 后续待办

- **A）Git 提交**：本次改动（apps/api/main.py、apps/api/pyproject.toml、uv.lock、web/src/**/*）均未提交；建议走 pre-commit + commit 固化。
- **B）DeepSeek API Key**：用户提供后，决策面板即显真实 PA 分析（替换 mock）。
- **C）广度 / 关注列表真数据**：当前静态 / 种子（仅 600036 / 贵州茅台用真实 parquet，NVDA / AVGO / BTC 与 breadth 行业为占位），后续可接 akshare / 在线源。

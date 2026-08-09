# QuantHub 运行与依赖基线

- 生成时间：`2026-08-09T14:50:48+08:00`
- 分支：`codex/web-workbench-consolidation`
- HEAD：`9abd1d592753f81e019de488e1911cb6344888cc`
- 工作区未提交条目数：`75`

> 本文件由 `tools/export_runtime_baseline.py` 生成，禁止手工编辑。

## 1. 前端路由

| 路由 | 页面文件 | 文件存在 |
| --- | --- | --- |
| `/__ui` | `web/src/components/ui/_demo/UiShowcasePage.tsx` | 是 |
| `//` | `web/src/pages/OverviewPage.tsx` | 是 |
| `/evaluate` | `web/src/pages/StockEvaluationStartPage.tsx` | 是 |
| `/research/:symbol` | `web/src/pages/ResearchWorkspacePage.tsx` | 是 |
| `/ensemble` | `web/src/pages/EnsemblePage.tsx` | 是 |
| `/radar` | `web/src/pages/RadarPage.tsx` | 是 |
| `/signals` | `web/src/pages/SignalsPage.tsx` | 是 |
| `/trading` | `web/src/pages/TradingWorkspacePage.tsx` | 是 |
| `/account-risk` | `web/src/pages/AccountRiskPage.tsx` | 是 |
| `/tasks` | `web/src/pages/AnalysisTasksPage.tsx` | 是 |
| `/alerts` | `web/src/pages/AlertsPage.tsx` | 是 |
| `/simulation` | `web/src/pages/SimulationOrdersPage.tsx` | 是 |
| `/ledger` | `web/src/pages/LedgerPage.tsx` | 是 |
| `/instruments` | `web/src/pages/InstrumentCenterPage.tsx` | 是 |
| `/factor-research` | `web/src/pages/FactorResearchPage.tsx` | 是 |
| `/automation` | `web/src/pages/AutomationPage.tsx` | 是 |
| `/incidents` | `web/src/pages/IncidentsPage.tsx` | 是 |
| `/governance` | `web/src/pages/GovernancePage.tsx` | 是 |
| `/news` | `web/src/pages/NewsPage.tsx` | 是 |
| `/strategies` | `web/src/pages/StrategiesPage.tsx` | 是 |
| `/strategies/:name` | `web/src/pages/StrategyDetailPage.tsx` | 是 |
| `/strategy-lab` | `web/src/pages/StrategyLabPage.tsx` | 是 |
| `/pa` | `web/src/pages/PaAnalysisPage.tsx` | 是 |
| `/portfolio` | `web/src/pages/PortfolioPage.tsx` | 是 |
| `/config` | `web/src/pages/ConfigPage.tsx` | 是 |

## 2. 一级导航项

| key | 标签 | 目标 |
| --- | --- | --- |
| `overview` | 总览 | `/` |
| `evaluation` | 标的研究 | `/evaluate` |
| `radar` | 信号雷达 | `/radar` |
| `tasks` | 研究任务 | `/tasks` |
| `instruments` | 标的与数据 | `/instruments` |
| `strategy` | 策略运行 | `/strategies` |
| `portfolio` | 策略组合 | `/portfolio` |
| `trading` | 交易工作台 | `/trading` |
| `signal` | 信号审核 | `/signals` |
| `simulation` | 模拟交易 | `/simulation` |
| `account-risk` | 账户与风控 | `/account-risk` |
| `ledger` | 账户账本 | `/ledger` |
| `alerts` | 价格提醒 | `/alerts` |
| `config` | 系统设置 | `/config` |
| `automation` | 作业调度 | `/automation` |
| `incidents` | 运行故障 | `/incidents` |
| `watchlist` | 自选 | `/#watchlist` |

## 3. 页面 -> API -> 后端路由 依赖矩阵

| 前端文件 | 调用的 api 方法 | 实际请求路径 |
| --- | --- | --- |
| `web/src/App.tsx` | 4 个 | `/auth/session`, `/health`, `/signals`, `/strategies` |
| `web/src/api/taskRunner.ts` | 2 个 | `/analysis/tasks`, `/analysis/tasks/${encodeURIComponent(id)}` |
| `web/src/components/CommandPalette/CommandPalette.tsx` | 1 个 | `/search` |
| `web/src/components/DecisionPanel.tsx` | 3 个 | `/analysis/tasks/${encodeURIComponent(id)}/cancel`, `/research/runs/${encodeURIComponent(id)}/evidence`, `/signals/publish` |
| `web/src/components/KlineCard.tsx` | 1 个 | `/data/kline` |
| `web/src/components/settings/LLMProviderSettings.tsx` | 4 个 | `/config/llm`, `/config/llm/key`, `/config/llm/test` |
| `web/src/hooks/useEditableHoldings.ts` | 4 个 | `/portfolio/holdings`, `/portfolio/holdings/${encodeURIComponent(id)}`, `/portfolio/holdings/reset` |
| `web/src/hooks/useEditableWatchlist.ts` | 3 个 | `/market/watchlist`, `/market/watchlist/${encodeURIComponent(id)}` |
| `web/src/hooks/useSecurityNameResolver.ts` | 1 个 | `/market/quote` |
| `web/src/hooks/useSignals.ts` | 1 个 | `/signals` |
| `web/src/hooks/useStrategyPresets.ts` | 2 个 | `/strategies/${encodeURIComponent(name)}/presets`, `/strategies/${encodeURIComponent(name)}/presets/${id}` |
| `web/src/hooks/useStrategyRuns.ts` | 1 个 | `/strategies/${encodeURIComponent(name)}/runs` |
| `web/src/pages/AlertsPage.tsx` | 8 个 | `/alerts/check`, `/alerts/events`, `/alerts/events/${encodeURIComponent(eventId)}/acknowledge`, `/alerts/rules`, `/alerts/rules/${encodeURIComponent(ruleId)}`, `/alerts/rules/${encodeURIComponent(ruleId)}/check` |
| `web/src/pages/AnalysisTasksPage.tsx` | 4 个 | `/analysis/tasks`, `/analysis/tasks/${encodeURIComponent(id)}/cancel`, `/analysis/tasks/${encodeURIComponent(id)}/retry` |
| `web/src/pages/AutomationPage.tsx` | 13 个 | `/automation/alerts`, `/automation/audit`, `/automation/factor-research-jobs`, `/automation/jobs`, `/automation/jobs/${encodeURIComponent(name)}`, `/automation/jobs/${encodeURIComponent(name)}/run`, `/automation/runs`, `/automation/runs/${encodeURIComponent(runId)}/acknowledge` … |
| `web/src/pages/ConfigPage.tsx` | 15 个 | `/backups`, `/backups/${encodeURIComponent(name)}/restore`, `/backups/${encodeURIComponent(name)}/verify`, `/backups/retention/apply`, `/backups/retention/preview`, `/backups/status`, `/config/notifications`, `/config/notifications/${channel}` … |
| `web/src/pages/CrossSectionResearchPanel.tsx` | 7 个 | `/factor-research/cross-sectional/analyze`, `/factor-research/cross-sectional/status/${encodeURIComponent(factorKey)}${query}`, `/factor-research/status-matrix/${encodeURIComponent(factorKey)}`, `/factor-research/universes`, `/factor-research/universes${market `, `/factor-research/universes/${encodeURIComponent(universeId)}/members`, `/factor-research/universes/${encodeURIComponent(universeId)}/members${asOf ` |
| `web/src/pages/EnsemblePage.tsx` | 2 个 | `/research/runs/${encodeURIComponent(id)}/evidence`, `/signals/publish` |
| `web/src/pages/FactorConfirmationPanel.tsx` | 4 个 | `/factor-research/experiments${query `, `/factor-research/plans${targetMarket `, `/factor-research/plans/${encodeURIComponent(planId)}/confirmation-set`, `/factor-research/plans/${encodeURIComponent(planId)}/confirmation-set/open` |
| `web/src/pages/FactorResearchPage.test.tsx` | 1 个 | `/factor-research/universes/${encodeURIComponent(universeId)}/members${asOf ` |
| `web/src/pages/FactorResearchPage.tsx` | 6 个 | `/factor-research/ai-review`, `/factor-research/analyze`, `/factor-research/runs`, `/factor-research/runs/${encodeURIComponent(runId)}`, `/research/runs/${encodeURIComponent(id)}`, `/research/runs/batch` |
| `web/src/pages/GovernancePage.tsx` | 11 个 | `/auth/audit`, `/auth/roles`, `/auth/session`, `/auth/tokens`, `/auth/tokens/${encodeURIComponent(tokenId)}`, `/auth/users`, `/auth/users/${encodeURIComponent(userId)}/roles`, `/auth/users/${encodeURIComponent(userId)}/status` … |
| `web/src/pages/IncidentsPage.tsx` | 6 个 | `/analysis/tasks/${encodeURIComponent(id)}/retry`, `/automation/runs/${encodeURIComponent(runId)}/acknowledge`, `/automation/runs/${encodeURIComponent(runId)}/retry`, `/incidents`, `/research/runs/${encodeURIComponent(id)}`, `/simulation/orders/${encodeURIComponent(orderId)}/executions/${encodeURIComponent(executionId)}/ledger-sync` |
| `web/src/pages/InstrumentCenterPage.tsx` | 2 个 | `/instruments` |
| `web/src/pages/LedgerPage.tsx` | 18 个 | `/instruments/${encodeURIComponent(code)}`, `/ledger/attribution`, `/ledger/benchmarks`, `/ledger/benchmarks/${encodeURIComponent(benchmarkId)}`, `/ledger/cash`, `/ledger/cash/${encodeURIComponent(entryId)}`, `/ledger/corrections`, `/ledger/exposures` … |
| `web/src/pages/NewsPage.tsx` | 1 个 | `/news/health` |
| `web/src/pages/OverviewPage.tsx` | 11 个 | `/alerts/events`, `/analysis/tasks`, `/automation/alerts`, `/factor-research/attention`, `/incidents`, `/ledger/summary`, `/market/breadth`, `/research/runs` … |
| `web/src/pages/PortfolioPage.tsx` | 5 个 | `/portfolio/manage`, `/portfolio/manage/allocations`, `/portfolio/manage/allocations/${id}`, `/portfolio/manage/allocations/${id}/live`, `/strategies` |
| `web/src/pages/RadarPage.tsx` | 4 个 | `/market/quote`, `/market/watchlist`, `/research/runs`, `/signals` |
| `web/src/pages/ResearchWorkspacePage.tsx` | 12 个 | `/analysis/tasks`, `/analysis/tasks/${encodeURIComponent(id)}`, `/analysis/tasks/${encodeURIComponent(id)}/cancel`, `/analysis/tasks/${encodeURIComponent(id)}/retry`, `/instruments`, `/market/watchlist`, `/research/compare`, `/research/runs` … |
| `web/src/pages/SignalsPage.tsx` | 9 个 | `/research/runs/${encodeURIComponent(id)}`, `/signals`, `/signals/${encodeURIComponent(id)}`, `/signals/${encodeURIComponent(id)}/status`, `/signals/publish`, `/simulation/orders`, `/simulation/orders/${encodeURIComponent(id)}`, `/simulation/orders/preview` … |
| `web/src/pages/SimulationOrdersPage.tsx` | 6 个 | `/simulation/account`, `/simulation/orders`, `/simulation/orders/${encodeURIComponent(id)}/cancel`, `/simulation/orders/${encodeURIComponent(id)}/fills`, `/simulation/orders/${encodeURIComponent(orderId)}/executions/${encodeURIComponent(executionId)}/ledger-sync` |
| `web/src/pages/StockEvaluationStartPage.tsx` | 5 个 | `/analysis/tasks`, `/analysis/tasks/recent`, `/health`, `/instruments`, `/market/watchlist` |
| `web/src/pages/StrategiesPage.tsx` | 2 个 | `/strategies`, `/strategies/${encodeURIComponent(name)}/run` |
| `web/src/pages/StrategyDetailPage.tsx` | 5 个 | `/strategies`, `/strategies/${encodeURIComponent(name)}/backtest`, `/strategies/${encodeURIComponent(name)}/live`, `/strategies/${encodeURIComponent(name)}/live/tick`, `/strategies/${encodeURIComponent(name)}/run` |
| `web/src/pages/StrategyLabPage.tsx` | 19 个 | `/strategies`, `/strategy-lab/compare`, `/strategy-lab/definitions`, `/strategy-lab/definitions/${encodeURIComponent(definitionId)}/versions`, `/strategy-lab/definitions/${encodeURIComponent(id)}`, `/strategy-lab/definitions/${encodeURIComponent(id)}/archive`, `/strategy-lab/definitions/${encodeURIComponent(id)}/copy`, `/strategy-lab/experiments` … |

## 4. 后端已挂载路由

共 `187` 条。

| 路径 | 方法 | tags |
| --- | --- | --- |
| `/alerts/check` | POST | alerts |
| `/alerts/events` | GET | alerts |
| `/alerts/events/{event_id}/acknowledge` | POST | alerts |
| `/alerts/rules` | GET, POST | alerts |
| `/alerts/rules/{rule_id}` | DELETE, PATCH | alerts |
| `/alerts/rules/{rule_id}/check` | POST | alerts |
| `/analysis/tasks` | GET, POST | analysis-tasks |
| `/analysis/tasks/recent` | GET | analysis-tasks |
| `/analysis/tasks/{task_id}` | GET | analysis-tasks |
| `/analysis/tasks/{task_id}/cancel` | POST | analysis-tasks |
| `/analysis/tasks/{task_id}/retry` | POST | analysis-tasks |
| `/auth/audit` | GET | governance |
| `/auth/roles` | GET | governance |
| `/auth/session` | GET | governance |
| `/auth/tokens` | GET, POST | governance |
| `/auth/tokens/{token_id}` | DELETE | governance |
| `/auth/users` | GET, POST | governance |
| `/auth/users/{user_id}/roles` | PUT | governance |
| `/auth/users/{user_id}/status` | PATCH | governance |
| `/automation/alerts` | GET | automation |
| `/automation/audit` | GET | automation |
| `/automation/factor-research-jobs` | GET, POST | automation |
| `/automation/factor-research-jobs/{job_id}` | PATCH | automation |
| `/automation/jobs` | GET | automation |
| `/automation/jobs/{name}` | GET, PATCH | automation |
| `/automation/jobs/{name}/run` | POST | automation |
| `/automation/runs` | GET | automation |
| `/automation/runs/{run_id}` | GET | automation |
| `/automation/runs/{run_id}/acknowledge` | POST | automation |
| `/automation/runs/{run_id}/retry` | POST | automation |
| `/automation/status` | GET | automation |
| `/backups` | GET, POST | backups |
| `/backups/retention/apply` | POST | backups |
| `/backups/retention/preview` | POST | backups |
| `/backups/status` | GET | backups |
| `/backups/{name}/restore` | POST | backups |
| `/backups/{name}/verify` | POST | backups |
| `/config/apikey` | GET, POST | settings |
| `/config/llm` | GET, PUT | settings |
| `/config/llm/key` | DELETE | settings |
| `/config/llm/test` | POST | settings |
| `/config/notifications` | GET, PATCH | settings |
| `/config/notifications/{channel}` | PUT | settings |
| `/config/notifications/{channel}/test` | POST | settings |
| `/config/status` | GET | settings |
| `/data/kline` | GET | data |
| `/factor-research/ai-review` | POST | factor-research |
| `/factor-research/analyze` | POST | factor-research |
| `/factor-research/attention` | GET | factor-research |
| `/factor-research/candidate-validations` | POST | factor-research |
| `/factor-research/candidates/inbox` | POST | factor-research |
| `/factor-research/cross-sectional/analyze` | POST | factor-research |
| `/factor-research/cross-sectional/runs/{run_id}` | GET | factor-research |
| `/factor-research/cross-sectional/status/{factor_key}` | GET | factor-research |
| `/factor-research/definitions` | GET, POST | factor-research |
| `/factor-research/definitions/import-token-formulas` | POST | factor-research |
| `/factor-research/definitions/seed-builtins` | POST | factor-research |
| `/factor-research/definitions/{factor_key}/{version}` | GET | factor-research |
| `/factor-research/definitions/{factor_key}/{version}/lifecycle` | GET | factor-research |
| `/factor-research/definitions/{factor_key}/{version}/lifecycle/transitions` | POST | factor-research |
| `/factor-research/efficiency/compare` | POST | factor-research |
| `/factor-research/experiments` | GET, POST | factor-research |
| `/factor-research/experiments/{experiment_id}` | GET | factor-research |
| `/factor-research/experiments/{experiment_id}/events` | POST | factor-research |
| `/factor-research/lineage/{factor_key}/{version}` | POST | factor-research |
| `/factor-research/monitoring/drift` | POST | factor-research |
| `/factor-research/plans` | GET, POST | factor-research |
| `/factor-research/plans/{plan_id}` | GET | factor-research |
| `/factor-research/plans/{plan_id}/ai-proposal-context` | GET | factor-research |
| `/factor-research/plans/{plan_id}/ai-search-rounds` | GET, POST | factor-research |
| `/factor-research/plans/{plan_id}/confirmation-set` | GET | factor-research |
| `/factor-research/plans/{plan_id}/confirmation-set/open` | POST | factor-research |
| `/factor-research/plans/{plan_id}/multiple-testing` | GET | factor-research |
| `/factor-research/portfolio-constraints/validate` | POST | factor-research |
| `/factor-research/redundancy/analyze` | POST | factor-research |
| `/factor-research/retirement/impact-preview` | POST | factor-research |
| `/factor-research/robustness/analyze` | POST | factor-research |
| `/factor-research/runs` | GET | factor-research |
| `/factor-research/runs/{run_id}` | GET | factor-research |
| `/factor-research/simulation/attribute-gap` | POST | factor-research |
| `/factor-research/simulation/validate` | POST | factor-research |
| `/factor-research/status-matrix/{factor_key}` | GET | factor-research |
| `/factor-research/universes` | GET, POST | factor-research |
| `/factor-research/universes/{universe_id}/members` | GET, POST | factor-research |
| `/health` | GET | - |
| `/incidents` | GET | incidents |
| `/incidents/data-sources/check` | POST | incidents |
| `/incidents/data-sources/history` | GET | incidents |
| `/incidents/data-sources/{incident_id}/acknowledge` | POST | incidents |
| `/instruments` | GET, POST | instrument |
| `/instruments/search` | GET | instrument |
| `/instruments/{code}` | GET | instrument |
| `/ledger/attribution` | GET | ledger |
| `/ledger/benchmarks` | GET, POST | ledger |
| `/ledger/benchmarks/{benchmark_id}` | PATCH | ledger |
| `/ledger/cash` | GET, POST | ledger |
| `/ledger/cash/{entry_id}` | PATCH | ledger |
| `/ledger/corrections` | GET | ledger |
| `/ledger/exposures` | GET | ledger |
| `/ledger/performance` | GET | ledger |
| `/ledger/positions` | GET | ledger |
| `/ledger/positions/{instrument_id}` | GET | ledger |
| `/ledger/positions/{instrument_id}/decision-context` | GET | ledger |
| `/ledger/summary` | GET | ledger |
| `/ledger/timeline` | GET | ledger |
| `/ledger/trade-analytics` | GET | ledger |
| `/ledger/trades` | GET, POST | ledger |
| `/ledger/trades/{trade_id}` | PATCH | ledger |
| `/market-data/check` | POST | market-data |
| `/market-data/status` | GET | market-data |
| `/market/breadth` | GET | portfolio |
| `/market/quote` | GET | portfolio |
| `/market/watchlist` | GET, POST | portfolio |
| `/market/watchlist/reset` | POST | portfolio |
| `/market/watchlist/{watch_id}` | DELETE, PATCH | portfolio |
| `/news/analyze` | POST | news |
| `/news/events/research` | POST | news |
| `/news/events/validate` | POST | news |
| `/news/health` | GET | news |
| `/portfolio` | GET | portfolio |
| `/portfolio/holdings` | POST | portfolio |
| `/portfolio/holdings/reset` | POST | portfolio |
| `/portfolio/holdings/{holding_id}` | DELETE, PATCH | portfolio |
| `/portfolio/manage` | GET | portfolio |
| `/portfolio/manage/allocations` | POST | portfolio |
| `/portfolio/manage/allocations/{allocation_id}` | DELETE | portfolio |
| `/portfolio/manage/allocations/{allocation_id}/live` | POST | portfolio |
| `/predict/ensemble` | POST | ensemble |
| `/research/compare` | POST | research |
| `/research/runs` | GET, POST | research |
| `/research/runs/batch` | PATCH | research |
| `/research/runs/{run_id}` | GET, PATCH | research |
| `/research/runs/{run_id}/evidence` | POST | research |
| `/research/runs/{run_id}/export` | GET | research |
| `/research/runs/{run_id}/verify` | GET | research |
| `/search` | GET | search |
| `/signals` | GET | signals |
| `/signals/publish` | POST | signals |
| `/signals/{signal_id}` | DELETE | signals |
| `/signals/{signal_id}/status` | PATCH | signals |
| `/simulation/account` | GET | simulation |
| `/simulation/orders` | GET, POST | simulation |
| `/simulation/orders/preview` | POST | simulation |
| `/simulation/orders/{order_id}` | GET | simulation |
| `/simulation/orders/{order_id}/cancel` | POST | simulation |
| `/simulation/orders/{order_id}/executions/{execution_id}/ledger-sync` | POST | simulation |
| `/simulation/orders/{order_id}/fills` | POST | simulation |
| `/strategies` | GET | strategies |
| `/strategies/alphamaster/engine` | GET | strategies |
| `/strategies/pa_agent/analyze` | POST | strategies |
| `/strategies/presets` | GET | strategies |
| `/strategies/runs` | GET | strategies |
| `/strategies/{name}` | GET | strategies |
| `/strategies/{name}/backtest` | POST | strategies |
| `/strategies/{name}/live` | GET | strategies |
| `/strategies/{name}/live/tick` | POST | strategies |
| `/strategies/{name}/presets` | GET, POST | strategies |
| `/strategies/{name}/presets/{preset_id}` | DELETE | strategies |
| `/strategies/{name}/run` | POST | strategies |
| `/strategies/{name}/runs` | POST | strategies |
| `/strategy-lab/compare` | GET | strategy-lab |
| `/strategy-lab/definitions` | GET, POST | strategy-lab |
| `/strategy-lab/definitions/{definition_id}` | GET, PATCH | strategy-lab |
| `/strategy-lab/definitions/{definition_id}/archive` | POST | strategy-lab |
| `/strategy-lab/definitions/{definition_id}/copy` | POST | strategy-lab |
| `/strategy-lab/definitions/{definition_id}/versions` | POST | strategy-lab |
| `/strategy-lab/experiments` | GET, POST | strategy-lab |
| `/strategy-lab/experiments/{experiment_id}` | PATCH | strategy-lab |
| `/strategy-lab/experiments/{experiment_id}/archive` | POST | strategy-lab |
| `/strategy-lab/experiments/{experiment_id}/backtest` | POST | strategy-lab |
| `/strategy-lab/experiments/{experiment_id}/copy` | POST | strategy-lab |
| `/strategy-lab/experiments/{experiment_id}/runs` | GET | strategy-lab |
| `/strategy-lab/runs/{run_id}` | GET | strategy-lab |
| `/strategy-lab/versions/{version_id}` | PATCH | strategy-lab |
| `/strategy-lab/versions/{version_id}/archive` | POST | strategy-lab |
| `/strategy-lab/versions/{version_id}/copy` | POST | strategy-lab |
| `/trading/accounts/{account_id}` | GET | trading |
| `/trading/dashboard` | GET | trading |
| `/trading/health` | GET | trading |
| `/trading/orders` | POST | trading |
| `/trading/orders/{order_id}` | GET | trading |
| `/trading/orders/{order_id}/cancel` | POST | trading |
| `/trading/reconciliation/diffs/{diff_id}` | GET | trading |
| `/trading/reconciliation/diffs/{diff_id}/resolve` | POST | trading |
| `/trading/reconciliation/{account_id}` | POST | trading |
| `/trading/recovery/orders` | POST | trading |
| `/trading/risk/mode` | POST | trading |

## 5. 前端孤立文件（从 main.tsx 不可达，已排除测试文件）

- `web/src/components/CommandPalette/index.ts`
- `web/src/components/KpiCard.tsx`
- `web/src/components/StatusBar/index.ts`
- `web/src/components/WorkspaceHeader/index.ts`
- `web/src/components/ui/Badge/index.ts`
- `web/src/components/ui/Button/index.ts`
- `web/src/components/ui/Card/index.ts`
- `web/src/components/ui/EmptyState/index.ts`
- `web/src/components/ui/Field/index.ts`
- `web/src/components/ui/Icon/index.ts`
- `web/src/components/ui/IconButton/index.ts`
- `web/src/components/ui/Input/index.ts`
- `web/src/components/ui/Modal/index.ts`
- `web/src/components/ui/Panel/index.ts`
- `web/src/components/ui/SegmentedControl/index.ts`
- `web/src/components/ui/Select/index.ts`
- `web/src/components/ui/Skeleton/index.ts`
- `web/src/components/ui/Spinner/index.ts`
- `web/src/components/ui/Table/index.ts`
- `web/src/components/ui/Tag/index.ts`
- `web/src/components/ui/Textarea/index.ts`
- `web/src/components/ui/Toggle/index.ts`
- `web/src/components/ui/Tooltip/index.ts`
- `web/src/components/ui/index.ts`

## 6. 数据库

### `store`

- 路径：`apps/api/store.db`
- SHA-256：`fc865f9dd77675f5b2aa1b6588f9ec438824caa3764efdb4dd086dbebbb1e809`
- 大小：`4616192` 字节
- `integrity_check`：`ok`
- 表数：`49`，总行数：`982`

### `okx_runner_shadow`

- 路径：`data/okx_runner/runner-shadow.db`
- SHA-256：`d04c78f390b149302acd7d72a0ed0ba9f5e99aa5ad9074caa8ba43ff1d857c27`
- 大小：`106496` 字节
- `integrity_check`：`ok`
- 表数：`12`，总行数：`2`

## 7. 启动面

```json
{
  "web_npm_scripts": {
    "dev": "vite",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc -b",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "shell_scripts": [],
  "dockerfiles": [
    "Dockerfile",
    "docker/Dockerfile.okx-runner"
  ],
  "github_workflows": [
    ".github/workflows/ci.yml",
    ".github/workflows/okx-runner.yml",
    ".github/workflows/release.yml"
  ]
}
```

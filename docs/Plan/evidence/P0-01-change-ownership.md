# P0-01 变更归属清单（Change-Ownership Inventory）

- 生成时间：`2026-08-09T15:10:00+08:00`
- 分支：`codex/web-workbench-consolidation`
- 工作区未提交条目数：`79`（其中 staged 修改 `M` 前缀含 `MM`/`AM` 计为已修改；未跟踪 `??` 计为新增）
- 分类口径：
  - **保留**：纳入本次工作台收口目标，或仍被保留功能引用、不得删除。
  - **删除**：已从导航/构建/产物中移除的孤立或示例资产。
  - **待确认**：代码仍保留直链路由或目录，但按路线图「删除前必须用户裁决」原则，最终删除或恢复需负责人拍板。

> 依据：`git status --porcelain`（见下方逐条）。本清单与 `docs/Plan/2026-08-09-Web工作台与OKX实盘-可执行工作安排.md` 第 5 节任务表、路线图第 2 节「当前仓库结论」交叉对应。

## 1. 已修改（M / MM / AM）

| 文件 | 归属 | 说明 |
| --- | --- | --- |
| `README.md` | 保留 | M1-05：补充一键启动 Web+API+Runner 说明 |
| `apps/api/domains/factor_research/service.py` | 保留 | 仍被 Web 研究域使用，未下线 |
| `apps/api/domains/governance/auth.py` | 保留 | 治理/认证域，保留 |
| `apps/api/domains/strategies/service.py` | 保留 | 策略域，保留 |
| `apps/api/main.py` | 保留 | 挂载 `trading` 领域（M1-03） |
| `apps/api/store.py` | 保留 | 存储层，保留 |
| `core/data_feed/tencent_source.py` | 保留 | 行情源，保留 |
| `docs/README.md` | 保留 | 文档，保留 |
| `pyproject.toml` | 保留 | 依赖/构建配置，保留 |
| `strategies/__init__.py` | 保留 | 策略包，保留 |
| `strategies/a_shares/realtime_analyzer/strategy.py` | 保留 | 策略实现，保留 |
| `strategies/us_stocks/__init__.py` | 保留（新增目录） | 美股策略包骨架 |
| `strategies/us_stocks/realtime_analyzer/__init__.py` | 保留（新增目录） | 美股实时分析骨架 |
| `strategies/us_stocks/realtime_analyzer/pyproject.toml` | 保留（新增目录） | 子包构建配置 |
| `strategies/us_stocks/realtime_analyzer/strategy.py` | 保留（新增目录） | 美股实时分析策略 |
| `tools/start-quanthub.ps1` | 保留 | M1-05：新增 Runner 启动（8103/shadow 默认） |
| `tools/stop-quanthub.ps1` | 保留 | M1-05：新增 Runner 停止（先于 Web/API） |
| `uv.lock` | 保留 | 依赖锁，保留 |
| `web/src/api/client.ts` | 保留 | `getJSON<T>` 统一封装，保留 |
| `web/src/api/types.ts` | 保留 | API 类型，保留 |
| `web/src/components/DecisionPanel.tsx` | 保留 | 决策面板，保留 |
| `web/src/components/KlineCard.tsx` | 保留 | K 线卡片，保留 |
| `web/src/components/KpiCard.tsx` | **删除** | M2-02：孤立旧组件，页面改用 `ui/KpiCard` |
| `web/src/components/MarketBreadth.tsx` | 保留 | 宽度指标（真实口径改造待确认，见 M3-02） |
| `web/src/components/MobileNavigation.test.tsx` | 保留 | 移动导航测试，保留 |
| `web/src/components/MobileNavigation.tsx` | 保留 | 移动导航，保留 |
| `web/src/components/SignalStats.module.css` | **删除** | M2-02：孤立样式 |
| `web/src/components/SignalStats.tsx` | **删除** | M2-02：孤立组件 |
| `web/src/components/ui/KpiCard/KpiCard.tsx` | 保留 | 移除 `KpiCardLegacy` |
| `web/src/components/ui/KpiCard/index.ts` | 保留 | 导出收敛 |
| `web/src/components/ui/index.ts` | 保留 | 导出收敛 |
| `web/src/data/mock.ts` | **删除** | M3-02：生产硬编码 mock 数据源移除 |
| `web/src/lib/market.ts` | **删除** | M2-02/M3-02：生产硬编码市场数据移除 |
| `web/src/main.tsx` | 保留 | M2-01：六类导航骨架；`/__ui` 仅 dev 注册（生产 bundle 不含） |
| `web/src/navigation/workspaces.test.ts` | 保留 | 导航测试，保留 |
| `web/src/navigation/workspaces.tsx` | 保留 | M2-01：六类顶层导航（子项收敛待确认） |
| `web/src/pages/ConfigPage.module.css` | 保留 | 设置页样式，保留 |
| `web/src/pages/ConfigPage.tsx` | 保留 | M2-07：接入凭据入口迁移至此 |
| `web/src/pages/ExampleWorkspacePage.module.css` | **删除** | M2-03：示例工作区样式 |
| `web/src/pages/ExampleWorkspacePage.tsx` | **删除** | M2-03：示例工作区页 |
| `web/src/pages/GovernancePage.tsx` | **待确认** | 已从一级导航移除，路由保留（管理能力唯一界面，删除需裁决） |
| `web/src/pages/OverviewPage.tsx` | 保留 | 总览页，保留 |
| `web/src/pages/StockEvaluationStartPage.tsx` | 保留 | 标的研究入口，保留 |
| `web/src/pages/StrategiesPage.tsx` | 保留 | 策略运行页，保留 |
| `web/src/pages/StrategyDetailPage.tsx` | 保留 | 策略详情，保留 |
| `web/src/styles/app.css` | 保留 | 全局样式，保留 |

## 2. 已删除（D）

| 文件 | 归属 | 说明 |
| --- | --- | --- |
| `web/src/components/KpiCard.tsx` | **删除** | M2-02 孤立旧组件 |
| `web/src/components/SignalStats.module.css` | **删除** | M2-02 孤立样式 |
| `web/src/components/SignalStats.tsx` | **删除** | M2-02 孤立组件 |
| `web/src/data/mock.ts` | **删除** | M3-02 生产 mock 数据 |
| `web/src/lib/market.ts` | **删除** | M2-02/M3-02 生产硬编码市场数据 |
| `web/src/pages/ExampleWorkspacePage.module.css` | **删除** | M2-03 示例页样式 |
| `web/src/pages/ExampleWorkspacePage.tsx` | **删除** | M2-03 示例页 |

## 3. 新增未跟踪（??）

| 文件 / 目录 | 归属 | 说明 |
| --- | --- | --- |
| `.github/workflows/okx-runner.yml` | 保留 | Runner CI |
| `apps/api/contracts.py` | 保留 | M3-03 统一数据契约信封（status/source/observed_at/freshness/error_code） |
| `apps/api/domains/trading/` | 保留 | M1-02/M1-03 交易代理（11 路由 + 服务 + 配置 + 客户端 + 错误码） |
| `apps/okx_runner/` | 保留 | 无 UI 执行引擎（订单状态机/风控/对账/恢复） |
| `configs/okx-runner.env.example` | 保留 | Runner 环境变量样例 |
| `data/okx_runner/` | 保留 | Runner 影子库与运行数据 |
| `docker/` | 保留 | 仅保留 Runner Dockerfile（拆分产品 Docker 已删） |
| `docs/ENGINEERING_GUIDE.md` | 保留 | 工程指南 |
| `docs/FACTOR_RESEARCH_BASELINE.md` | 保留 | 因子研究基线 |
| `docs/OPERATIONS_GUIDE.md` | 保留 | 运维指南 |
| `docs/Plan/` | 保留 | 本路线图与工作安排文档 |
| `docs/TRADING_SAFETY.md` | 保留 | 交易安全说明 |
| `docs/okx_runner/` | 保留 | Runner 文档 |
| `docs/security/` | 保留 | 安全文档 |
| `packages/` | 保留 | 共享公共模块 |
| `tests/split/` | 保留 | 拆分测试 |
| `tests/test_trading_proxy.py` | 保留 | M1-03 交易代理契约测试 |
| `tools/check_fake_data.py` | 保留 | M3-01 假数据扫描门禁 |
| `tools/check_product_licenses.py` | 保留 | 许可证核查 |
| `tools/check_product_secrets.py` | 保留 | 密钥核查 |
| `tools/export_runtime_baseline.py` | 保留 | P0-03 基线导出 |
| `tools/migrate_product_data.py` | 保留（收窄） | 仅支持 OKX Runner 的数据迁移 |
| `tools/product_database.py` | 保留 | 产品数据库工具 |
| `tools/run_runner_shadow_acceptance.py` | 保留 | Runner shadow 验收 |
| `web/src/components/contract/` | 保留 | M3-03 契约状态组件 |
| `web/src/data/types.ts` | 保留 | M2-02 活类型（移除旧 dead 类型） |
| `web/src/navigation/keyFlows.test.ts` | 保留 | M2-08 关键流程可达性测试 |
| `web/src/navigation/keyFlows.ts` | 保留 | M2-08 关键流程可达性契约 |
| `web/src/pages/AccountRiskPage.tsx` | 保留 | M2-06 账户与风控工作区 |
| `web/src/pages/RadarPage.tsx` | 保留 | 信号雷达页 |
| `web/src/pages/TradingWorkspacePage.module.css` | 保留 | M2-05/M2-08 交易工作区样式 |
| `web/src/pages/TradingWorkspacePage.tsx` | 保留 | M2-05/M2-08 交易工作区（含 Runner 降级状态条） |
| `web/src/styles/research-matrix.css` | 保留 | 研究矩阵样式 |

## 4. 待用户裁决项（路线图「删除前必须用户裁决」）

| 项 | 现状 | 裁决选项 |
| --- | --- | --- |
| `/governance` 路由与 `GovernancePage` | 已移出一级导航，路由保留 | 整体下线 / 保留为高级设置入口 |
| `/strategy-lab` 与 `StrategyLabPage` | 已移出一级导航，路由保留（被 6 处入站引用） | 删除 / 并入策略工作区 |
| `/factor-research` 与 `FactorResearchPage` | 已移出一级导航，路由保留（路线图 3.B 暂停因子实验） | 删除 / 恢复为受控入口 |
| `/pa`、`/portfolio`、`/news` 等直链 | 通过 `workspaces.tsx` 收敛到六类，但直链仍可达 | 删除直链 / 保留为深链 |
| `MarketBreadth` 样本统计 | 仍可能含代表性样本口径 | 改为真实全市场口径 / 删除模块 |

> 以上项均不影响当前构建、测试与门禁；删除动作将作为独立 PR 在用户裁决后执行，且必须在专用分支通过构建/测试/回滚验证（路线图执行顺序红线）。

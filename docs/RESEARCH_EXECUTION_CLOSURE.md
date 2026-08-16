# 研究、风控、执行与归因闭环契约

本文记录 2026-08-16 闭环升级的稳定 API、持久化和兼容语义。功能归属仍以 `FUNCTION_BOUNDARIES.md` 为准。

## 研究决定

`ResearchDecision` 是报告与执行入口的唯一方向状态，字段包括 `direction`、`execution_eligible`、`module_opinions`、`conflicts`、`invalidation_conditions`、`reevaluate_triggers`、`decision_version`、`decided_at` 和 `input_fingerprint`。

- `conflicted`、`insufficient`、过期或缺失证据均失败关闭。
- `/research/compare` 返回保存快照的结构化方向、规则、指标和价位变化，不重新计算旧记录。
- 信号发布和模拟订单创建同时检查执行资格与订单方向。

## 模拟风险 API

| API | 语义 |
| --- | --- |
| `POST /simulation/orders/preview` | 读取当前服务端行情、账户、未完成订单、成本和研究决定，返回解释性风险预览 |
| `POST /simulation/orders` | 只接受订单意图，重新取数并持久化最终风险决定；不信任前端预览结论 |
| `GET /simulation/orders` | 返回订单、风险审计、成本快照与归因身份 |
| `GET /simulation/account` | 返回按模拟账本重建且已对账的账户快照 |

稳定阻断码包括行情缺失/过期/质量失败、账户过期/对账失败、成本档案不完整/市场不匹配、研究阻断/方向不一致、现金不足、敞口超限、只减仓违规、整手/数量步长/价格步长违规。每项返回 `actual`、`limit` 和 `reevaluate_action`。

因子工厂可通过 Python 服务边界传递可信闭合行情、锁定样本外研究决定和预注册限额。该能力不暴露在 HTTP schema 中。

## 成本档案 API

成本档案使用 `profile_id + version + content_hash` 标识。相同 ID 和版本不可覆盖不同内容。研究和风险快照保存完整不可变档案；市场完整性要求见 `TRADING_COST_SOURCES.md`。

旧 `commission_bps` 兼容记录返回 `compatibility_status=legacy_incomplete`，可以展示或用于探索，但不能被视为完整交易验证证据。

## 股票池版本 API

CSV/XLSX 导入先解析和校验，再生成新增、更新、失效、冲突与忽略项预览。应用批次使用幂等键并创建不可变版本；回滚只切换 `current_version_id`。按历史日期查询时仍从选定版本快照过滤，不读取可变成员表。

## 交易与 Runner

交易工作台支持市价/限价、只减仓、账户比例、结构化止损止盈、改单、撤单和快速平仓。Demo 环境的品种和规则来自 Runner preflight；Live 环境继续使用静态允许清单。Runner 使用最新标记价、账户和未完成订单重新风控，限价单必须有价格，保护价必须满足方向几何关系。

## 账本归因

账本身份字段独立保存 `strategy_id/version`、`factor_key/version`、`research_run_id`、`signal_id`、`simulation_order_id`、`execution_id` 和 `market_regime_id`。`source` 不再承担归因。

`GET /ledger/attribution` 支持按因子、因子版本、研究、策略、信号和市场状态分组，返回毛收益、费用、净收益、胜率、持仓时间、回撤和回链。`conservation.balanced` 必须证明分组净收益等于闭合交易净收益。无法恢复身份的历史记录只进入 `unknown_attribution`。

## 迁移与回滚

SQLite 迁移由 `store._init()` 幂等执行。升级前创建并验证数据库备份；升级后启动 API 完成迁移并运行全量测试。迁移只新增表、列、索引和显式兼容状态，不删除历史数据，不推断未知身份。

回滚代码版本时必须恢复与旧版本匹配的升级前数据库备份，不要手工删除新列或降低配置 schema。

## 发布证据

本次发布证据位于 `docs/Plan/evidence/research-risk-execution-attribution-closure-2026-08-16/`，包括完整测试结果摘要、三视口 Chromium 报告和九张关键状态截图。

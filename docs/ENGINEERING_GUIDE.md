# QuantHub 工程质量与发布门禁

> 目标：让代码可维护、可接手、可审计，并让每次发布具备可重复的验证和恢复路径。

## 1. 工程原则

- 依赖边界不可越界，公共契约不可绕过。
- 数据、配置和真实执行相关操作必须只读检查先行，并保留备份和审计记录。
- 外部网络、模型或可选依赖不可用时，应用应明确降级，不能阻断基础页面启动。
- 新目录遵守 [架构与功能边界](ARCHITECTURE.md) 和 [Web 工作台收口路线图](Plan/2026-08-09-Web工作台收口与OKX实盘路线图.md) 中的边界规则。

## 2. 当前分层与依赖

| 层 | 当前目录 | 职责 | 禁止 |
| --- | --- | --- | --- |
| 应用层 | `apps/` | API、调度、dispatcher 等常驻服务 | 在入口中复制策略和数据算法 |
| 策略层 | `strategies/` | 插件式策略，产出 `Signal` 或 `BacktestResult` | 导入其他策略内部模块 |
| 核心层 | `core/` | 数据、信号、LLM、回测和通用能力 | 反向依赖 `strategies/` 或 `apps/` |
| 配置层 | `configs/` | 市场和运行配置 | 保存密钥或在代码中硬编码开关 |

当前依赖方向为 `apps → strategies → core → 第三方`。主 API 与无 UI 的 OKX Runner 只能通过公开协议协作，不得互相导入内部实现。

## 3. 策略与回测契约

每个策略必须：

1. 继承 `StrategyBase`，使用 `@register_strategy(StrategyInfo(...))` 注册。
2. 实现 `produce(**kwargs) -> list[Signal]`；无网络或无模型密钥时返回明确的降级结果，不抛未捕获异常。
3. 让 `backtest()` 返回 `core.backtest.BacktestResult`；不支持时返回 `BacktestResult.empty(engine="none")`，不得抛 `NotImplementedError`。
4. 让 `live_tick()` 默认无操作，并保持全局与模块实盘开关关闭。
5. 提供全局唯一名称、市场、版本、实盘能力和说明等元数据。

回测指标统一由 `core.backtest.metrics.compute_metrics` 计算。策略不得自行维护另一套 Sharpe、回撤或收益定义。

新增策略使用脚手架：

```powershell
uv run python tools/scaffold_strategy.py --name myalpha --market a_shares --desc "示例 Alpha 因子"
```

## 4. 编码与审查规则

- 公共函数提供类型标注；重要公共接口说明参数、返回值和异常。
- 使用 `logging.getLogger(__name__)`，不用 `print` 充当运行日志。
- `torch`、`backtrader`、模型权重等重依赖只在实际执行路径中加载。
- `import` 包不得启动网络请求、模型加载、调度器或其他副作用。
- 阈值、Cron、标的池和开关进入配置，不在代码中散落硬编码。
- 外部错误进入日志前脱敏；API 不返回密钥、令牌或通知凭据。
- 修改数据库结构必须新增 Alembic revision，不使用未记录的生产手工 SQL。

代码审查清单：

- [ ] 依赖方向和产品所有权没有被破坏。
- [ ] 新公共协议具有版本、兼容策略和契约测试。
- [ ] 策略回测返回统一结果，离线和无密钥路径可以降级。
- [ ] 重依赖懒加载，模块导入没有副作用。
- [ ] 配置、密钥、阈值和业务数据没有硬编码或泄漏。
- [ ] 数据库和危险操作具备 dry-run、备份、确认和回滚路径。
- [ ] 相关单元、集成、契约和端到端测试已更新。

## 5. 数据质量规则

所有市场和财务数据至少检查：

- 标识、市场、时间区间、时区和频率是否明确。
- OHLC 是否为正、`high >= low`、成交量是否包含哨兵或非法值。
- 时间是否单调、是否重复、是否存在未来数据或可用时间倒置。
- 缺失、过期、冲突、修订和来源是否显式保存。
- 公司行为、财报重述、单位、币种和会计口径是否可追溯。
- 研究使用的数据快照、内容哈希和引擎版本是否可恢复。

修复数据时必须：

1. 先运行只读扫描并保存异常数量和样例。
2. 默认 dry-run，只有显式 `--apply` 才能写入。
3. 写入前创建带时间戳的备份并验证可读性。
4. 修复后重新扫描，并核对文件数、行数、哈希和异常数量。
5. 不确定损坏机制时保留原始数据，不以猜测值覆盖。

## 6. 自动化验证

基础验证：

```powershell
uv sync
uv run python -m compileall -q apps/api apps/dispatcher apps/scheduler core strategies
uv run python -c "from apps.api.main import app; assert app.title"
Set-Location web
npm.cmd ci
npm.cmd run typecheck
npm.cmd run build
```

变更应按风险增加测试：

| 变更 | 最低验证 |
| --- | --- |
| 文档或配置说明 | 链接检查、示例命令核对、`git diff --check` |
| 纯后端逻辑 | 相关单元测试、Python 编译、应用导入 |
| API 或数据库 | 单元测试、集成测试、迁移升级和回滚检查 |
| 前端 | TypeScript、组件测试、生产构建、目标视口检查 |
| API/Runner 协议 | 生产者/消费者契约测试和版本兼容检查 |
| 订单或对账 | 幂等、部分成交、未知状态、重启恢复和故障演练 |

## 7. 性能与恢复演练

`tools.quality_baseline` 使用隔离临时 SQLite 数据库，不读取业务库。当前参考门限：

- 10,000 条信号批量写入不超过 15,000 ms。
- 查询最新 200 条信号的 20 次采样 P95 不超过 250 ms。

该性能基线按需运行，不作为当前精简 CI 的固定门禁。

`tools.run_recovery_drill` 应在隔离目录验证：初始化 schema、事务一致备份、完整性检查、带安全备份的恢复，以及中断任务只恢复并提交一次。

## 8. 发布检查清单

- [ ] `live_trading=false`，除非本次发布单独通过真实执行评审。
- [ ] Alembic `current` 与 `head` 一致，升级路径在空库和旧库上均通过。
- [ ] Python 编译、应用导入、相关测试、前端类型检查和生产构建通过。
- [ ] 数据或数据库变更已执行备份、恢复或迁移演练。
- [ ] 局域网或 PostgreSQL 模式 CORS 不包含 `*`。
- [ ] 管理令牌不少于 32 个字符，业务用户使用独立令牌。
- [ ] 没有过期但仍有效的无人使用令牌。
- [ ] 日志、配置、构建产物和提交差异通过密钥与隐私检查。
- [ ] 发布说明列出版本、schema revision、兼容边界、回滚步骤和已知限制。
- [ ] `git diff --check` 和文档链接检查通过。

# QuantHub 团队代码质量规范（Senior Developer 定稿）

> 目的：把"能跑"升级为"团队可维护、可接手、可审计"。
> 本规范结合 QuantHub 实际分层，**不是通用八股**，新增/改动代码必须对照执行。
> 审查红线（CI / 人工 Review 卡点）见末尾。

---

## 0. 一句话原则

**分层边界不可越界；统一契约不可打折；危险操作必须备份 + 先问。**

---

## 1. 项目分层与边界（谁能动谁的依赖）

| 层 | 目录 | 职责 | 禁止 |
|---|---|---|---|
| 应用层 | `apps/` | 常驻服务：看板 / 调度 / API 网关 | 写策略逻辑、直连数据源 |
| 策略层 | `strategies/` | 插件式策略，**只产出 `Signal` 或 `BacktestResult`** | import 其他策略的内部模块（除本模块子包） |
| 核心层 | `core/` | 数据 / 信号 / LLM / 回测 / 可视化 | 反向依赖 `strategies/` 或 `apps/` |
| 归档层 | `vendored/` | 只读参考副本，**不可改、不可运行时依赖**（除 `alphamaster` 经 `sys.path` 注入） | 往里写、提交进 git |
| 配置层 | `configs/` | 每市场一份 yaml | 在代码里硬编码开关/密钥 |

**依赖方向**：`apps → strategies → core → 第三方`。反向 import 一律视为 bug。

---

## 2. 策略插件契约（硬性）

每个策略 = 一个包，必须：

1. 继承 `StrategyBase`，用 `@register_strategy(StrategyInfo(...))` 注册。
2. `produce(**kwargs) -> list[Signal]`：**必须实现**（抽象方法）。
   - 无网络/无 LLM key 时必须**优雅降级**（返回快照 / 空列表 / 降级研报），**禁止抛未捕获异常**。
3. `backtest(klines, **kwargs) -> BacktestResult`：**返回类型固定为 `core.backtest.BacktestResult`**。
   - 不支持回测 → `return BacktestResult.empty(engine="none")`。
   - **严禁 `raise NotImplementedError`**（会让统一的回测调用器因单点崩溃）。
   - 非空路径统一用 `EventEngine` / `GridBacktester` / `BacktraderEngine`，它们都返回 `BacktestResult`。
4. `live_tick(**kwargs)`：默认 no-op（`is_live()` 为 false 时直接 return）。
   - **实盘默认关闭**：双开关 = 全局 `live_trading=true` 且 `modules.<name>.live=true`。
5. 元数据：`StrategyInfo` 字段 `name/market/version/live_capable/description` 必填，`name` 全局唯一。

> 反例（已修复）：`realtime_analyzer.backtest()` 曾 `raise NotImplementedError`，
> 违反基类契约；7 个策略曾返回裸 `dict` 而非 `BacktestResult` —— 均已统一。

---

## 3. 回测统一契约

- **唯一结果类型**：`core.backtest.BacktestResult`（dataclass）。
- 字段：`equity_curve: DataFrame | trades: list[dict] | final_equity | total_return | max_drawdown | metrics: dict | engine | extra`。
- 辅助 API（直接用，别自己拼 dict）：
  - `BacktestResult.empty(engine="event")` —— 空数据 / 未实现。
  - `BacktestResult.from_dict(d)` —— 兼容历史裸 dict（容错）。
  - `GridResult.to_backtest_result()` —— 网格结果转统一类型。
  - `result.to_summary()` —— 给 API / 看板用的扁平 dict。
- 指标统一在 `core.backtest.metrics.compute_metrics`，**不要**在各策略里各算一套 Sharpe。

---

## 4. 编码规范（可读性即质量）

- **类型标注全开**：函数签名、返回类型（`-> BacktestResult` 而非裸 `-> dict`）。
- **docstring**：模块顶部写"从哪来、沉到哪、依赖什么"；公共方法写 `Args/Returns/Raises`。
- **命名**：策略内类名 `XxxStrategy`；模块级便捷函数 `run_*`；常量 `UPPER_SNAKE`。
- **日志**：用 `logging.getLogger(__name__)`，分级（debug 细节 / info 关键节点 / warning 降级 / error 真实失败）。禁止 `print` 做状态输出。
- **重依赖懒加载**：`torch` / `backtrader` / `model_core` 只能在 `produce/backtest/live` 路径内 import，`import strategies.xxx` 必须零副作用。
- **配置驱动**：阈值、cron、标的列表全走 `configs/*.yaml`，不写死在代码。

---

## 5. 测试红线（改动必带测试）

- 每个策略**至少 1 个测试**：注册成功 + `produce()` 离线可跑（mock 网络）+ `backtest()` 返回 `BacktestResult`（不 raise）。
- **单元测禁止真实网络**：数据源用本地 parquet / 合成 DataFrame；外部 API 用 `unittest.mock` 或 try/except 降级分支覆盖。
- 全量 `uv run pytest tests/ -q` **必须全绿**才能合入。当前基线 **52 passed**。
- 集成测试 `tests/test_integration.py` 的"期望策略集"随注册增减同步更新。

---

## 6. 危险操作协议（数据安全第一）

> 数据比代码贵。任何可能改 `.parquet` / `.zip` / 线上数据的动作，先走此流程。

1. **只读先行**：先只统计、不写盘（如 `tools/repair_indices_parquet.py` 默认 dry-run）。
2. **备份优先**：落盘前 `cp -r` 到 `_backup_<时间戳>/`，确认成功再动。
3. **先问后动**：破坏性 / 不可逆操作（删数据、改生产配置、开实盘）**必须**显式获得确认，禁止自作主张。
4. `vendored/` 视为只读；要改逻辑请提取到 `core/` 或 `strategies/`，不要直接编辑归档。

---

## 7. 新增策略 = 用脚手架（不要手搓）

```powershell
uv run python tools/scaffold_strategy.py --name myalpha --market a_shares --desc "示例Alpha因子"
```

脚手架会生成合规包（`strategy.py`/`__init__.py`/`pyproject.toml`）、
自动登记到 `strategies/__init__.py` 与 `configs/<market>.yaml`、
并提示补 `pyproject.toml` 的 workspace 成员。**手工新建策略视为违反规范。**

---

## 8. Review 卡点（Senior Developer 把关清单）

- [ ] 分层边界未被打破（无反向 import）
- [ ] `backtest()` 返回 `BacktestResult`，无 `raise NotImplementedError`
- [ ] `produce()` 离线 / 无 key 可降级，不崩
- [ ] 实盘默认关，双开关齐全
- [ ] 重依赖懒加载，`import` 包零副作用
- [ ] 类型标注 + docstring 完整
- [ ] 新增/改动带测试，全量 pytest 绿
- [ ] 危险操作已备份 + 已确认
- [ ] 配置未硬编码，阈值走 yaml

> 任一项不过 = 打回。质量不是锦上添花，是交付底线。

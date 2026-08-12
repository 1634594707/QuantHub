# QuantHub 升级与扩展指南

> 版本控制协议、扩展接口、升级路径、向后兼容策略

## 1. 版本控制协议

### 1.1 版本号

仓库版本：`pyproject.toml: version`（语义化版本 MAJOR.MINOR.PATCH）
- MAJOR：架构不兼容变更（如 Signal 字段重构）
- MINOR：新策略/新功能（向后兼容）
- PATCH：bug 修复

### 1.2 配置 schema 版本

`configs/base.yaml: schema_version`（整数，每次配置结构不兼容变更递增）

升级钩子在 `core/config.py: _migrate_schema(cfg, current_schema)`：
```python
def _migrate_schema(cfg, current_schema):
    if current_schema < 1:
        raise SchemaVersionError(...)
    # 未来:
    # if current_schema == 1:
    #     cfg = _migrate_v1_to_v2(cfg)  # 加新字段、重命名
    #     current_schema = 2
    return cfg
```

**升级流程**：用户旧配置 → `_migrate_schema` 逐版本向上迁移 → 当前 schema。无需手动改配置。

### 1.3 策略版本

每个策略的 `StrategyInfo.version` 独立版本号。策略接口变更需 bump。

## 2. 扩展接口

### 2.1 新增策略

1. 创建 `strategies/<market>/<name>/` 目录
2. 实现 `StrategyBase` 子类，用 `@register_strategy` 注册
3. 在 `pyproject.toml` 的 `[tool.uv.workspace] members` 添加路径
4. 如需定时调度，在 `configs/<market>.yaml: modules.<name>.cron` 配置，并在 `apps/scheduler/jobs.py: job_map` 添加映射

```python
@register_strategy(StrategyInfo(name="my_strat", market="a_shares", live_capable=False))
class MyStrategy(StrategyBase):
    def produce(self, **kwargs) -> list[Signal]:
        ...
```

### 2.2 新增数据源

实现 `DataSource` 子类，调用 `register_source(name, cls)` 注册：

```python
from core.data_feed.base import DataSource, Interval
from core.data_feed import register_source

class MySource(DataSource):
    name = "my_source"
    market = "a_shares"
    def get_kline(self, symbol, interval, ...):
        ...

register_source("my_source", MySource)
```

然后在 `configs/<market>.yaml: data_sources.primary` 或 `fallback` 引用。

### 2.3 新增告警通道

在 `core/alert/__init__.py: Notifier` 添加 `_send_<channel>` 方法，并在 `configs/base.yaml: alert.channels` 启用。

### 2.4 新增回测引擎

在 `core/backtest/` 添加引擎模块，返回 `BacktestResult` 统一结构。

## 3. 升级路径

### 3.1 升级 QuantHub 版本

```powershell
# 升级前先生成可验证的在线备份
uv run python -m tools.backup_store backup --output backups/store-pre-upgrade.db
uv run python -m tools.backup_store verify backups/store-pre-upgrade.db

# 拉取新版本后
uv sync --locked              # 按锁文件更新 Python 依赖
uv run python -m compileall -q apps/api apps/dispatcher apps/scheduler core strategies
Set-Location web
npm.cmd ci
npm.cmd run typecheck
npm.cmd run build
# _migrate_schema 自动迁移配置
```

建议至少保留最近 14 份数据库备份；清理命令默认 dry-run，检查候选文件后再加
`--apply`：

```powershell
uv run python -m tools.backup_store prune backups --keep 14
uv run python -m tools.backup_store prune backups --keep 14 --apply
```

### 3.2 配置 schema 升级（用户侧）

**无需手动操作**。`get_config()` 调用时自动检测 `schema_version` 并迁移。
如 schema_version 落后于当前版本，`_migrate_schema` 逐版本向上迁移。

### 3.3 策略接口升级

当 `StrategyBase` 接口变更时：
- 新增方法默认实现（向后兼容）
- 现有策略无需改动
- 废弃方法标注 `@deprecated`，保留一个 MINOR 周期后移除

### 3.4 数据源升级

`DataSource` 接口新增方法时，基类提供默认空实现，现有数据源无需改动。

## 4. 向后兼容策略

| 变更类型 | 兼容策略 |
|---|---|
| Signal 新增字段 | `meta: dict` 承载，不破坏 dataclass |
| 配置新增字段 | YAML 缺失字段用默认值，`_deep_merge` 兼容 |
| 策略新增方法 | `StrategyBase` 提供默认实现 |
| 数据源新增方法 | `DataSource` 基类默认空实现 |
| 缓存格式变更 | `CacheStore` schema 用 `CREATE TABLE IF NOT EXISTS`，旧表保留 |
| Python 版本 | 锁定 `>=3.11,<3.13`，升级需评估 torch/solana 兼容 |

## 5. 原项目迁移状态

原 6 个项目的业务逻辑已下沉为策略模块，算法保持不变。原项目目录保留作为参考：

| 原项目 | 迁移去向 | 算法保真度 |
|---|---|---|
| 市场情绪系统 | strategies/a_shares/sentiment | FinBERT2 降级链 + 阈值保持 |
| trading-master/01 | strategies/a_shares/news_scanner | LLM prompt 原样 |
| trading-master/03 | strategies/a_shares/morning_brief | 枢轴点+评分公式逐字移植 |
| trading-master/04 | strategies/a_shares/selector | 多因子公式保持 |
| trading-master/05 | strategies/a_shares/supertrend | ATR/band 更新逻辑保持 |
| 羊毛监控 | strategies/a_shares/perks_monitor | 27 关键词逐字搬运 |
| OKX Grid Master | strategies/crypto/okx_grid | 选币因子保持 |
| AlphaGPT | strategies/crypto/alphagpt | StackVM 12 指令集保持 |
| PA_Agent | strategies/ai_analysis/pa_agent | ATR/EMA + 两阶段编排 + 独立输出质量闸门 |

**替换的接入层**（原实现 → QuantHub 底座）：
- akshare/东财爬虫 → `core.data_feed`
- WeChatPusher → `core.alert.Notifier`
- deepseek_client → `core.llm.get_llm()`
- 自研回测 → `core.backtest`（网格/backtrader/事件驱动）

## 6. 发布前验证

```powershell
uv run python -m compileall -q apps/api apps/dispatcher apps/scheduler core strategies
uv run python -c "from apps.api.main import app; assert app.title"
Set-Location web
npm.cmd run typecheck
npm.cmd run build
```

## 7. 回滚

如升级后异常：
1. 使用 `tools/stop-quanthub.ps1` 停止 Web、API 和 Runner，并停止调度器、dispatcher
   等其他写入进程，避免恢复期间继续写 SQLite。
2. 切回已验证的旧代码版本并同步对应依赖。
3. 校验升级前备份：`uv run python -m tools.backup_store verify backups/store-pre-upgrade.db`。
4. 恢复数据库：`uv run python -m tools.backup_store restore backups/store-pre-upgrade.db --yes`。
5. 恢复命令会先自动备份当前数据库；保留输出中的 `safety_backup` 路径，便于反向恢复。
6. 使用 `tools/start-quanthub.ps1` 启动目标模式，检查 `/health`、
   `/market-data/status` 和 Runner 状态，再运行完整测试。

不要手工降低 `schema_version`。配置迁移和 SQLite 增量列迁移只保证向前兼容，数据库
回滚必须使用与旧代码版本匹配的升级前备份。

## 8. 后续工作入口

升级文档不维护容易漂移的功能 TODO。当前研究状态见
[AI 因子发现路线图](../AI_FACTOR_DISCOVERY_ROADMAP.md)，产品边界见
[功能边界](FUNCTION_BOUNDARIES.md)，交易前置条件见
[交易安全边界](TRADING_SAFETY.md)。路线图中的状态必须带日期和可核验证据。

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
# 拉取新版本后
uv sync --all-extras          # 更新依赖
python -m pytest tests/core/  # 验证底座
# _migrate_schema 自动迁移配置
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
| PA_Agent | strategies/ai_analysis/pa_agent | ATR/EMA + 两阶段编排保持 |

**替换的接入层**（原实现 → QuantHub 底座）：
- akshare/东财爬虫 → `core.data_feed`
- WeChatPusher → `core.alert.Notifier`
- deepseek_client → `core.llm.get_llm()`
- 自研回测 → `core.backtest`（网格/backtrader/事件驱动）

## 6. 测试

```powershell
# 底座单测（28 个）
python -m pytest tests/core/ -v

# 集成测试（策略注册 + 信号总线 + dispatcher）
python -m pytest tests/test_integration.py -v

# 全部
python -m pytest -v
```

## 7. 回滚

如升级后异常：
1. `git checkout <旧版本>` （如已纳入 git）
2. 配置回滚：手动改 `configs/base.yaml: schema_version`（_migrate_schema 向上兼容旧版）
3. 缓存清理：`CacheStore().clear()`

## 8. 后续 TODO

- [ ] A股数据源基本面数据接入（selector 的资金流/股票名称 TODO）
- [ ] PA_Agent 的完整 JsonValidator/语义检查（当前简化版）
- [ ] AlphaGPT Transformer 因子搜索（当前回退启发式公式）
- [ ] 看板 Web 勾选二次确认（当前 CLI）
- [ ] 看板登录鉴权（当前无）

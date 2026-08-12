# QuantHub 架构文档

> 当前架构基线：v0.4.x | schema_version 1 | 本地优先的分层单体仓库

## 1. 分层架构

```
┌─────────────────────────────────────────────────────────┐
│  应用层 apps/                                            │
│  ├─ api         (FastAPI 网页网关与领域接口)              │
│  ├─ okx_runner  (独立交易执行、恢复、对账与风险模式)       │
│  ├─ dispatcher  (遗留信号聚合与 dry-run 路由)             │
│  └─ scheduler   (网页自动化任务调度)                     │
├─────────────────────────────────────────────────────────┤
│  策略层 strategies/ (插件式，@register_strategy 挂载)     │
│  ├─ a_shares/   sentiment · news_scanner · selector ·   │
│  │              supertrend · morning_brief · perks_monitor│
│  ├─ crypto/     okx_grid · alphagpt                     │
│  └─ ai_analysis/ pa_agent                               │
├─────────────────────────────────────────────────────────┤
│  统一底座 core/ (只实现一次)                              │
│  ├─ data_feed  (多源行情/公告 + SQLite 缓存 + 退避重试)  │
│  ├─ signals    (Signal 数据类 + 轻量总线)                │
│  ├─ alert      (企微/Webhook/Telegram)                  │
│  ├─ llm        (DeepSeek/OpenAI 兼容客户端)             │
│  ├─ backtest   (网格 + backtrader + 事件驱动)           │
│  └─ config     (YAML 合并 + env 占位 + schema 迁移)     │
├─────────────────────────────────────────────────────────┤
│  configs/  base.yaml + a_shares.yaml + crypto.yaml      │
└─────────────────────────────────────────────────────────┘
```

## 2. 核心设计原则

1. **单一底座**：数据/信号/告警/LLM/回测只实现一次，消除原项目的重复实现。
2. **插件式策略**：每个策略实现 `StrategyBase`，通过 `@register_strategy` 注册，互不污染。
3. **实盘安全优先**：浏览器只访问统一 API；交易请求由 API 代理到独立 OKX Runner，
   `shadow` 默认只读，Demo 需要显式启动，live 还需要独立审批。
4. **渐进迁移**：原项目逻辑保持算法不变，仅替换数据/LLM/告警的接入层。

## 3. 组件交互

### 3.1 数据流（研究模式）

```
scheduler (cron) ──► strategy.produce()
                        │
                        ├─ core.data_feed.get_data_source(market)
                        │      ├─ akshare/eastmoney (A股)
                        │      └─ okx/ccxt (加密)
                        │      [SQLite 缓存 + 退避重试]
                        │
                        ├─ core.llm.get_llm() (可选)
                        ├─ 本地模型 (FinBERT2, 懒加载)
                        │
                        └─► Signal ──► SignalBus ──► 审核 / 模拟执行 / 研究账本
```

### 3.2 Signal 数据类

```python
@dataclass
class Signal:
    symbol: str           # 标的
    market: str           # a_shares | crypto
    timeframe: str        # daily / 1h / 4h
    direction: str        # buy | sell | hold
    score: float          # 0~1 方向强度
    confidence: float     # 0~1 模型置信度
    source: str           # 策略模块名
    tags: list[str]       # 标签
    ts: datetime          # 时间戳
    meta: dict            # 模块特有附加信息
```

构造时强校验 `score`/`confidence` ∈ [0,1]，`direction` ∈ {buy,sell,hold}。

### 3.3 信号总线

- 进程内、线程安全、同步派发
- 订阅可按 `source`/`market`/`direction` 过滤
- 订阅者异常隔离（不阻断总线）
- 保留最近 1000 条历史

### 3.4 dispatcher 聚合

按 `configs/base.yaml: signals.weights` 对多源信号加权：
- sentiment 0.25 / supertrend 0.30 / pa_agent 0.25 / selector 0.20
- 聚合窗口内同 symbol 的信号按 source 权重加权打分
- 综合分数超阈值（默认 0.6）→ 生成订单意图

## 4. 策略插件规范

### 4.1 实现 StrategyBase

```python
from strategies import StrategyBase, StrategyInfo, register_strategy
from core.signals import Signal

@register_strategy(StrategyInfo(
    name="my_strategy",
    market="a_shares",
    live_capable=False,
    description="我的策略"
))
class MyStrategy(StrategyBase):
    def produce(self, **kwargs) -> list[Signal]:
        # 1. 用 core.data_feed 取数据
        # 2. 计算信号
        sig = Signal(symbol="000001", market="a_shares", ...)
        self.publish(sig)   # 推入总线
        return [sig]

    def backtest(self, klines, **kwargs) -> dict:
        # 用 core.backtest 回测
        ...
```

### 4.2 策略执行边界

- `live_capable=True`
- 实现 `live_tick()`：实盘 tick 回调
- `is_live()` 与旧 dispatcher 路径只表示策略自身具备执行能力，不构成当前产品的
  live 授权。
- Web 产品的 OKX 执行只允许经过 `Web -> API /trading/* -> OKX Runner`，浏览器不能
  直接访问 Runner，也不能读取 Runner 令牌或 OKX 凭据。

## 5. 数据层抽象

```python
class DataSource(ABC):
    @abstractmethod
    def get_kline(self, symbol, interval, start, end, limit) -> DataFrame
    def get_news(self, symbol, limit) -> list[News]          # 默认空
    def get_announcements(self, symbol, limit) -> list[Announcement]  # 默认空
```

实现：`AkshareSource` / `EastmoneySource` / `OkxSource`，通过 `get_data_source(market)` 获取带缓存+fallback 的代理。

## 6. 实盘安全设计

### 模拟成交与账本同步

模拟执行和账本保持独立数据模型，但每一笔 `simulation_executions` 成交都会由模拟执行服务自动写入一笔 `ledger_trades` 成交：

```text
simulation_orders
  → simulation_executions
  → Instrument.instrument_id
  → ledger_trades
```

- `ledger_sync_status` 只使用 `pending`、`synced` 和 `failed`。
- `ledger_trade_id` 使用模拟成交编号稳定派生，重复同步不会生成重复账本流水。
- `ledger_sync_error` 保存同步失败原因，前端通过 `/simulation/orders/{order_id}/executions/{execution_id}/ledger-sync` 重试。
- 账本持仓支持多头和空头，反向成交先平仓，超出部分建立反向持仓。
- 当前同步只连接本地模拟执行与本地账本，不会调用真实券商或交易所。

### OKX Runner 执行边界

```text
Web 工作台
  -> 统一 API /trading/*
  -> 服务端范围校验与 Runner 认证
  -> OKX Runner (8103)
  -> 幂等订单状态机 / 风险模式 / 恢复 / 对账
  -> OKX Demo
```

- `shadow`：只读，不允许下单。
- `demo`：显式使用 `start-quanthub.ps1 -Demo`，凭据来自本地凭据仓库或部署密钥。
- `live`：除 live 环境外还必须设置 `QH_RUNNER_LIVE_APPROVED=1`，当前仓库不提供
  自动授权流程。
- Runner 仅监听本机地址；非本机或非 shadow 模式要求 `QH_RUNNER_AUTH_TOKEN`。
- 首期订单范围由统一 API 和 Runner 双重校验；未知订单先查询外部状态，禁止盲目重发。

## 7. 依赖管理

- **uv workspace**：成员列表以根目录 `pyproject.toml` 的 `[tool.uv.workspace].members` 为准，共享单一虚拟环境
- 可选依赖组：`a_shares` / `crypto` / `ai` / `backtest` / `heavy-torch` / `heavy-solana`
- 重依赖（torch/solana）懒加载，未安装时策略降级而非崩溃

## 8. 已注册策略清单

| 策略 | 市场 | 实盘 | 来源 |
|---|---|---|---|
| sentiment | a_shares | 否 | FinBERT2 情绪系统 |
| news_scanner | a_shares | 否 | trading-master 01 |
| selector | a_shares | 否 | trading-master 04 选股神器 |
| supertrend | a_shares | 否 | trading-master 05 |
| morning_brief | a_shares | 否 | trading-master 03 晨会简报 |
| perks_monitor | a_shares | 否 | 羊毛监控 |
| news_analyzer | a_shares | 否 | 新闻结构化分析 |
| realtime_analyzer | a_shares | 否 | 实时行情分析 |
| realtime_analyzer_us | us_stocks | 否 | 美股实时行情分析 |
| okx_grid | crypto | 是(默认关) | OKX Grid Master |
| alphagpt | crypto | 是(默认关) | AlphaGPT |
| pa_agent | ai_analysis | 否 | PA_Agent |
| alphamaster | mt5 | 是(默认关) | AlphaMaster |

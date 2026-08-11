# OKX 公共行情与 Alpha 参数手册

本文说明 QuantHub 因子研究使用的 OKX 合约目录、公共 K 线字段和手写 Alpha 参数。

## 1. 研究标的

因子工厂只接受 OKX 当前公共目录中真实存在、状态为 active 的线性 USDT 永续合约。

标准代码格式：

```text
{BASE}-USDT-SWAP
```

示例：

```text
BTC-USDT-SWAP
ETH-USDT-SWAP
SOL-USDT-SWAP
```

页面中的“合约目录”来自：

```text
GET /instruments/okx-swaps
```

底层公共市场目录直接来自 OKX 原生公共 REST API，不需要 API Key。目录结果包含：

| 参数 | 含义 | Alpha 用途 |
| --- | --- | --- |
| `code` | OKX `instId` | 数据、回测和模拟账户的统一标的标识 |
| `base` | 基础资产 | 资产分类和搜索 |
| `quote` | 报价资产，当前筛选为 USDT | 统一收益计价 |
| `settle` | 结算资产 | 模拟账户资金和手续费归属 |
| `contract_size` | 单张合约面值 | 容量、名义敞口和下单数量换算 |
| `price_precision` | 价格精度或最小价格步长 | 理论价、滑点和限价单取整 |
| `amount_precision` | 数量精度或数量步长 | 模拟下单数量取整 |
| `minimum_amount` | 最小下单数量 | 候选因子的可交易性门禁 |
| `linear` | 是否线性合约 | 当前只接受线性 USDT 合约 |
| `verified` | 是否命中 OKX 当前目录 | 未验证代码不能启动自动研究 |

中文搜索只是目录检索辅助，最终必须命中真实 `instId`。例如输入“黄金”会搜索 `XAUT`、`PAXG`、`GOLD` 等可能代码，但只有 OKX 当前确实存在的永续合约才会显示。石油和股票类名称遵循同一规则。

## 2. OKX 公共 K 线请求参数

QuantHub 页面统一调用：

```text
GET /data/kline?symbol=BTC-USDT-SWAP&market=crypto&interval=4h&limit=240
```

底层对应 OKX 公共 K 线能力。主要参数：

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `symbol` | `BTC-USDT-SWAP` | 必须来自已验证合约目录 |
| `market` | `crypto` | 使用 OKX 公共数据源 |
| `interval` | `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w` | K 线周期 |
| `limit` | `240` | 返回根数；API 层最大 5000，单次交易所请求会分页 |
| `start` | ISO 时间 | 研究快照可选起点 |
| `end` | ISO 时间 | 研究快照可选终点 |
| `use_cache` | `true` | 命中相同参数快照时复用，保证回测可复现 |

其中 `symbol`、`market`、`interval`、`limit` 是图表接口参数；`start`、`end`、`use_cache` 是因子研究快照内部参数，不直接传给 `/data/kline`。

OKX 原始 candles 接口常见请求参数为 `instId`、`bar`、`after`、`before`、`limit`。单次请求数量有限，QuantHub 会分页并生成本地快照指纹。

## 3. K 线返回字段

OKX 原始 K 线通常包含：

```text
ts, open, high, low, close, volume, volumeCurrency, volumeQuote, confirm
```

QuantHub 统一为：

| 字段 | Alpha 名称 | 含义 |
| --- | --- | --- |
| `t` | `datetime` | K 线时间 |
| `o` | `open` | 开盘价 |
| `h` | `high` | 最高价 |
| `l` | `low` | 最低价 |
| `c` | `close` | 收盘价 |
| `v` | `volume` | 成交量 |

当前手写 Alpha 表达式开放以下 5 个字段：

```text
open, high, low, close, volume
```

生成或回测 Alpha 时应使用已经收盘的 K 线。OKX 原始字段 `confirm=0` 表示当前 K 线尚未完成，不应作为已知最终收盘值参与历史标签或因子确认。

## 4. Alpha DSL 参数

### 4.1 通用参数

| 参数 | 范围 | 含义 |
| --- | --- | --- |
| `value` | 字段、常量或嵌套表达式 | 算子的输入序列 |
| `left`, `right` | 两个表达式 | 二元算子的左右输入 |
| `periods` | 整数 `1..500` | 收益回看、差分或滞后 K 线数 |
| `window` | 整数 `1..500` | 滚动统计窗口 |
| `lower`, `upper` | `0 <= lower < upper <= 1` | 缩尾分位数 |
| `condition` | 布尔表达式 | `where` 的选择条件 |
| `then`, `else` | 单位一致的表达式 | 条件成立和不成立时的结果 |

复杂度限制：

```text
最大表达式深度: 10
最大算子数量: 30
最大参数组合数: 100
```

### 4.2 白名单算子

```text
add(left, right)
sub(left, right)
mul(left, right)
div(left, right)
gt(left, right)
lt(left, right)
neg(value)
abs(value)
lag(value, periods)
diff(value, periods)
pct_change(value, periods)
rolling_mean(value, window)
rolling_std(value, window)
rolling_min(value, window)
rolling_max(value, window)
rolling_sum(value, window)
rolling_zscore(value, window)
rolling_winsorize(value, window)
rolling_winsorize(value, window, lower, upper)
rank(value, window)
where(condition, then, else)
```

手写表达式只允许位置参数，不允许 Python 代码、关键字参数、导入、未来数据或负数滞后。

## 5. Alpha 示例

短周期动量：

```text
rolling_zscore(pct_change(close, 3), 20)
```

短周期反转：

```text
neg(rolling_zscore(pct_change(close, 3), 20))
```

量价共振：

```text
mul(rolling_zscore(pct_change(close, 3), 20), rank(volume, 20))
```

波动率调整动量：

```text
div(pct_change(close, 20), rolling_std(pct_change(close, 1), 20))
```

突破条件信号：

```text
where(gt(close, lag(rolling_max(high, 20), 1)), rank(volume, 20), 0)
```

缩尾后的反转：

```text
neg(rolling_zscore(rolling_winsorize(pct_change(close, 1), 20, 0.01, 0.99), 20))
```

## 6. 与行情分析工作台复用

OKX 公共 K 线已经接入共享 `/data/kline` 接口和共享 K 线组件，因此可以在原行情分析页面选择“OKX 合约”并输入完整 `instId` 查看。

可以复用的分析：

- K 线、成交量、均线、价格波动和技术因子。
- 统一的 OHLCV 清洗、缓存、质量检查和时间周期处理。
- 因子研究、固定回测和模拟盘观察。

不能混同的内容：

- `AVGO-USDT-SWAP` 等合约行情不是纳斯达克 AVGO 现货逐笔行情。
- OKX 合约行情不包含股票财报、公司行动、拆股、分红和交易所现货盘口。
- 黄金、石油或股票类标的只有在 OKX 合约目录真实存在时才能使用。
- 使用 OKX 合约 K 线做技术行情分析是可行的，但基本面分析仍应使用对应证券市场数据源。

## 7. AI 生成 Alpha 时建议提供的上下文

```json
{
  "market": "crypto",
  "exchange": "okx",
  "instrument": "BTC-USDT-SWAP",
  "interval": "4h",
  "fields": ["open", "high", "low", "close", "volume"],
  "maximum_window": 500,
  "maximum_operators": 30,
  "causal_only": true,
  "after_cost": true,
  "paper_observation_days": 7
}
```

AI 只负责提出候选表达式。最终是否进入模拟盘仍由滚动验证、锁定确认、回撤、交易成本、成交率和至少 7 个真实自然日模拟观察共同决定。

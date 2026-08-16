# 交易成本来源与录入边界

本项目以版本化、不可变的 `TradingCostProfile` 作为研究、验证、模拟和执行的成本真值。API 使用 `cost_profile_id + cost_profile_version` 或完整快照；孤立的 `transaction_cost_bps` / `commission_bps` 只用于读取旧记录，并标记为 `legacy_incomplete`，不得进入交易验证状态。

进入交易验证的成本档案必须同时保存：原始数值、单位、`normalized_bps`、`charge_basis`、`source_url`、`source_captured_at`、`effective_from`、`effective_to`、`market`，以及适用的 `symbol` 或 `account_scope`。档案还必须提供市场所需的执行约束和 `participation_rate`。

## 当前参考档案

| 市场 | 档案 | 必需成本组件 | 必需执行约束 |
| --- | --- | --- | --- |
| A 股 | `a-shares-reference@1.0.0` | 佣金、印花税、过户费 | 涨停、跌停、停牌、整手 |
| 美股 | `us-stocks-reference@1.0.0` | 点差、佣金、SEC、FINRA TAF | 公司行为已复权 |
| OKX | `okx-reference@1.0.0` | 费率等级、资金费率、点差、滑点 | 数量步长、价格步长 |

参考档案用于可重复研究和本地演示，不声称替代账户实际费率。账户或标的专属档案应使用新版本或不同 `profile_id`，不得覆盖已存在版本；相同 ID 和版本但内容哈希不同会被拒绝。

## 已核验的官方入口

| 市场 | 成本或约束 | 精确来源 | 当前用途 |
| --- | --- | --- | --- |
| A 股 | 证券交易印花税 | https://www.gov.cn/zhengce/zhengceku/202308/content_6900443.htm | 卖出侧印花税规则；页面已核验包含 2023-08-28 生效信息 |
| A 股 | 过户费、登记结算收费 | https://www.chinaclear.cn/zdjs/fbzx/fee.shtml | 中国结算费用标准入口；费率按生效区间读取，不能在代码中写死 |
| 美股 | Section 31 等监管成交费 | https://www.sec.gov/rules-regulations/fee-rate-advisories | SEC 费率公告入口；按成交日期读取 |
| 美股 | Trading Activity Fee | https://www.finra.org/rules-guidance/guidance/trading-activity-fee | FINRA TAF 规则和费率入口 |
| 美股 | 会员监管费用 | https://www.finra.org/rules-guidance/rulebooks/corporate-organization/section-1-member-regulatory-fees | FINRA 会员监管费入口 |
| 加密资产 | 账户费率、资金费率、行情盘口 | https://www.okx.com/docs-v5/en/#rest-api-account-get-fee-rates；https://www.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate-history；https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-ticker | 项目配置和数据源明确使用 OKX；费率必须按账户、产品和时间取得 |
| MT5 | 点值、合约乘数、点差、隔夜利息 | https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py；https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants | 从经纪商终端 `symbol_info` 实际字段读取；不能使用固定合约参数 |

## 不能从源码推导的数值

- A 股佣金由券商和账户协议决定；涨跌停、停牌和整手规则由标的和交易所状态决定。
- 美股佣金、点差和公司行为处理依赖券商、账户和成交时间；Yahoo 的 `adjclose` 只能作为公司行为数据源，不能替代成交费用。
- OKX 费率等级、资金费率和盘口价差随账户、产品和时间变化。
- MT5 的 `trade_tick_value`、`trade_contract_size`、`spread`、隔夜利息和最小交易量必须从当前经纪商终端取得。

无法取得正文或当前账户数据的官方入口只能记录为待接入来源，不能被标记为已核验费率。`core/trading_costs.py` 中的成本档案模型因此要求每个组件提供来源和抓取时间，并拒绝缺少来源、时间范围冲突或无法换算为 `normalized_bps` 的档案进入交易验证。

## 维护流程

1. 从官方入口或账户接口取得原始值，保留抓取时间和生效区间。
2. 将每个组件归一为单边 bp，并明确 `per_fill` 或 `per_bar`。
3. 补全市场执行约束和参与率，运行完整性检查。
4. 以新版本保存；禁止修改已存在版本的内容。
5. 运行 A 股、美股和 OKX 成本契约测试及全量后端测试。

历史研究保存档案内容哈希。当前档案更新不会重算或改写旧研究；旧记录缺少完整组件时显示为不完整兼容状态。

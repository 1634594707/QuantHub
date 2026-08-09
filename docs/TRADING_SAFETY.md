# QuantHub 交易成本与真实执行安全边界

> 当前结论：不接入新的真实券商或交易所适配器，`live_trading` 继续保持 `false`。研究中的成本参数是有来源的情景输入，不是默认真实费率。

## 1. 当前执行边界

- `apps/dispatcher/router.py` 在 dry-run 下只输出订单意图。
- 现有 OKX 策略仍存在直连交易所实现，没有统一订单回执和持久化状态机。
- Solana 路径只记录委托日志，没有可验证提交结果。
- A 股和 MT5 没有当前可验收的真实报单通道。
- 策略实时接口明确返回 `mode="paper"`。
- 本地风险计算尚未与外部余额、冻结资金、未完成订单和真实持仓持续对账。

因此，当前模拟执行、账本和研究结果均不得表述为真实账户执行能力。

## 2. 成本档案契约

研究接受 `transaction_cost_bps` 作为明确的单边情景参数。进入交易验证的成本档案必须保存：

- 原始数值、单位和 `normalized_bps`。
- `source_url`、`source_captured_at`、`effective_from`、`effective_to`。
- `market`、适用 `symbol` 或 `account_scope`。
- 手续费、税费、资金费率、点差、滑点和容量假设的独立组件。

缺少来源、时间区间冲突或无法标准化的档案不得进入 `trading_validated` 门禁。

## 3. 官方来源入口

| 市场 | 成本或约束 | 官方入口 | 使用规则 |
| --- | --- | --- | --- |
| A 股 | 证券交易印花税 | https://www.gov.cn/zhengce/zhengceku/202308/content_6900443.htm | 按卖出侧规则和生效日期读取 |
| A 股 | 过户费与登记结算收费 | https://www.chinaclear.cn/zdjs/fbzx/fee.shtml | 按生效区间读取，不在代码中写死 |
| 美股 | Section 31 等监管成交费 | https://www.sec.gov/rules-regulations/fee-rate-advisories | 按成交日期读取 |
| 美股 | Trading Activity Fee | https://www.finra.org/rules-guidance/guidance/trading-activity-fee | 保存规则版本和适用范围 |
| 美股 | 会员监管费用 | https://www.finra.org/rules-guidance/rulebooks/corporate-organization/section-1-member-regulatory-fees | 不代替券商佣金和点差 |
| OKX | 账户费率、资金费率和盘口 | https://www.okx.com/docs-v5/en/ | 按账户、产品和时间获取 |
| MT5 | 点值、乘数、点差和隔夜利息 | https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py | 从当前经纪商终端读取 |

## 4. 禁止推断的成本

- A 股佣金取决于券商和账户协议；涨跌停、停牌和整手规则取决于标的与交易所状态。
- 美股佣金、点差和公司行为处理取决于券商、账户和成交时间；Yahoo `adjclose` 不能替代费用。
- OKX 费率等级、资金费率和盘口价差随账户、产品和时间变化。
- MT5 的点值、合约乘数、点差、隔夜利息和最小交易量必须从当前终端读取。
- 无法访问正文或当前账户数据的来源只能标为待接入，不能标记为已核验费率。

## 5. Runner 实盘前置能力

- [ ] 定义独立交易适配器协议，返回外部订单号、接收时间、状态、成交数量、均价、费用和错误码。
- [ ] 使用稳定客户端订单号保证提交幂等。
- [ ] 持久化 `submitted`、`accepted`、`partially_filled`、`filled`、`cancelled`、`rejected` 和 `unknown` 及每次转换。
- [ ] 超时进入 `unknown` 后先查询外部状态，禁止直接重复报单。
- [ ] 建立启动对账和定时对账，比较订单、成交、余额、持仓和本地账本。
- [ ] 支持撤单、部分成交、费用币种、最小量、精度、杠杆和交易时段约束。
- [ ] 密钥只来自部署密钥管理，不进入 API、前端、发布包、日志或审计前后值。
- [ ] 支持全局停机、单账户停机和只撤单模式。
- [ ] 在 OKX Demo/Sandbox 完成断网、限流、拒单、部分成交、重复请求、重启和恢复演练。

## 6. 实盘评审材料

只有全部前置能力完成后，才能评审单一执行通道。材料必须包含：

- 适配器协议和订单状态机。
- 幂等策略和未知订单恢复方案。
- 账户与本地账本对账报告。
- 故障演练结果和恢复时间。
- 权限、密钥、停机和人工值守矩阵。
- 部署、回滚和数据隔离步骤。

材料齐全前，不修改 `live_trading=false` 默认值，也不同时接入多个真实市场。

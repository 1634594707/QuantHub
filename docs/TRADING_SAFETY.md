# QuantHub 交易成本与真实执行安全边界

> 当前结论：只保留独立 OKX Runner 作为候选执行通道，不接入新的真实券商或交易所
> 适配器；`live_trading` 继续保持 `false`。研究中的成本参数是有来源的情景输入，
> 不是默认真实费率。

## 1. 当前执行边界

- Web 产品的 OKX 请求只经 `Web -> API /trading/* -> OKX Runner`，浏览器不直接访问
  Runner，也不读取凭据或服务令牌。
- Runner 已实现稳定客户端订单号、订单状态持久化、恢复、撤单、风险模式和四类对账。
- 旧 dispatcher 和策略直连代码不作为当前 Web 产品执行入口。
- Solana 路径只记录委托日志，没有可验证提交结果。
- A 股和 MT5 没有当前可验收的真实报单通道。
- 策略实时接口明确返回 `mode="paper"`。
- 外部 OKX Demo 的连续观察、差异闭环、私有通道稳定性和独立 live 审批仍未完成。

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

- [x] 独立 Runner 返回外部订单状态并持久化状态转换。
- [x] 使用稳定客户端订单号保证提交幂等，未知订单恢复前禁止盲目重发。
- [x] 提供启动恢复、撤单、风险模式和订单/成交/余额/持仓对账能力。
- [x] 凭据位于 Runner 进程边界，本地桌面凭据存储在仓库之外且前端不可回读。
- [ ] 在 OKX Demo 完成连续观察，覆盖部分成交、费用、最小量、精度、杠杆与重启恢复。
- [ ] 清零全部对账差异并留存可审计证据。
- [ ] 完成私有通道断线、断网、限流、拒单、时钟偏差和凭据异常演练。
- [ ] 验证 `cancel_only`、`halted` 与恢复 normal 的人工授权和轮值流程。
- [ ] 独立安全评审批准小额试点；批准前保持 `live_trading=false`。

## 6. 实盘评审材料

只有全部前置能力完成后，才能评审单一执行通道。材料必须包含：

- 适配器协议和订单状态机。
- 幂等策略和未知订单恢复方案。
- 账户与本地账本对账报告。
- 故障演练结果和恢复时间。
- 权限、密钥、停机和人工值守矩阵。
- 部署、回滚和数据隔离步骤。

材料齐全前，不修改 `live_trading=false` 默认值，也不同时接入多个真实市场。

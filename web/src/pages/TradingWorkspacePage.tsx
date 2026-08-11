import { useEffect, useMemo, useState } from 'react'
import { Activity, ListRestart, Plus, RefreshCw, Search, ShieldAlert, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type {
  ContractEnvelope,
  TradingDashboard,
  TradingHealth,
  TradingOrderDetail,
  TradingOrderIntent,
} from '../api/types'
import { useApi } from '../api/useApi'
import { ContractStatusBar } from '../components/contract/ContractStatusBar'
import { WORKSPACE_QUICK_LINKS } from '../navigation/keyFlows'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { Badge } from '../components/ui/Badge/Badge'
import { Button } from '../components/ui/Button/Button'
import { EmptyState } from '../components/ui/EmptyState/EmptyState'
import { Field } from '../components/ui/Field/Field'
import { Input } from '../components/ui/Input/Input'
import { Panel } from '../components/ui/Panel/Panel'
import { Select } from '../components/ui/Select/Select'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import s from './TradingWorkspacePage.module.css'

const FIRST_PHASE_SYMBOLS = ['BTC-USDT-SWAP']
const ENVIRONMENT_LABELS: Record<string, string> = {
  shadow: '影子（只读）',
  demo: 'OKX 模拟盘',
  live: 'OKX 实盘',
}
const OPEN_ORDER_STATUSES = new Set(['PENDING_SUBMIT', 'SUBMITTED', 'PARTIALLY_FILLED', 'UNKNOWN'])

interface OrderForm {
  accountId: string
  strategyId: string
  strategyVersion: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: string
  price: string
  leverage: string
}

const EMPTY_FORM: OrderForm = {
  accountId: 'okx-demo-account',
  strategyId: '',
  strategyVersion: '',
  symbol: FIRST_PHASE_SYMBOLS[0],
  side: 'buy',
  quantity: '',
  price: '',
  leverage: '1',
}

function newIntentId(): string {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  return `web-${random}`
}

function strategyKey(strategyId: string, version: string): string {
  return `${strategyId}::${version}`
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function pnlClass(value: number | null | undefined): string {
  return value !== null && value !== undefined && value >= 0 ? s.pnlPositive : s.pnlNegative
}

function statusVariant(status: string): 'neutral' | 'up' | 'down' | 'warn' | 'info' {
  if (status === 'FILLED' || status === 'CANCELLED') return 'up'
  if (status === 'REJECTED') return 'down'
  if (status === 'UNKNOWN' || status === 'PARTIALLY_FILLED') return 'warn'
  return status === 'SUBMITTED' ? 'info' : 'neutral'
}

export default function TradingWorkspacePage() {
  const health = useApi(() => api.tradingHealth(), [], { retry: false, pollInterval: 20000 })
  const preflight = useApi(() => api.tradingPreflight(), [], { retry: false, pollInterval: 60000 })
  const dashboard = useApi(() => api.tradingDashboard(), [], { retry: false, pollInterval: 15000 })

  const [form, setForm] = useState<OrderForm>(EMPTY_FORM)
  const [intentId, setIntentId] = useState(newIntentId)
  const [receipt, setReceipt] = useState<ContractEnvelope<TradingOrderDetail> | null>(null)
  const [receiptError, setReceiptError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [orderLookupId, setOrderLookupId] = useState('')
  const [lookup, setLookup] = useState<ContractEnvelope<TradingOrderDetail> | null>(null)
  const [lookupError, setLookupError] = useState('')
  const [operationMessage, setOperationMessage] = useState('')
  const [operationError, setOperationError] = useState('')
  const [operationLoading, setOperationLoading] = useState(false)

  const healthData: TradingHealth | null = health.data?.data ?? null
  const dashboardData: TradingDashboard | null = dashboard.data?.data ?? null
  const environment = healthData?.environment ?? null
  const configured = Boolean(healthData?.configured)
  const reachable = Boolean(healthData?.reachable)
  const tradingEnabled = Boolean(healthData?.trading_enabled)
  const instrument = preflight.data?.data?.instruments.find((item) => item.symbol === form.symbol) ?? null
  const globalRisk = dashboardData?.risk_states.find((item) => item.scope === 'global') ?? null
  const openDiffs = dashboardData?.reconciliation_diffs.filter((item) => item.status === 'open') ?? []
  const recentOrders = dashboardData?.orders.slice(0, 20) ?? []
  const accountSummary = dashboardData?.account_summary?.accounts.find((item) => item.account_id === form.accountId)
    ?? null
  const accountBalances = (dashboardData?.balances ?? []).filter(
    (item, index, items) => item.account_id === accountSummary?.account_id
      && items.findIndex((candidate) => candidate.account_id === item.account_id && candidate.currency === item.currency) === index,
  )
  const accountPositions = (dashboardData?.positions ?? []).filter(
    (item, index, items) => item.account_id === accountSummary?.account_id
      && items.findIndex((candidate) => candidate.account_id === item.account_id && candidate.symbol === item.symbol) === index,
  )

  useEffect(() => {
    if (!instrument || form.quantity) return
    setForm((previous) => ({ ...previous, quantity: String(instrument.minimum_quantity) }))
  }, [form.quantity, instrument])

  useEffect(() => {
    const strategies = dashboardData?.strategies ?? []
    if (!strategies.length || form.strategyId) return
    const selected = strategies[0]
    setForm((previous) => ({
      ...previous,
      strategyId: selected.strategy_id,
      strategyVersion: selected.version,
    }))
  }, [dashboardData?.strategies, form.strategyId])

  const disabledReason = useMemo(() => {
    if (health.loading && !health.data) return '正在读取交易服务状态。'
    if (!configured) return 'Runner 尚未配置。'
    if (!reachable) return 'OKX Runner 不可达。'
    if (environment === 'shadow') return '影子环境只读，禁止下单。'
    if (environment === 'live' && !healthData?.live_approved) return '实盘环境未获独立批准。'
    if (!tradingEnabled) return '服务端交易开关未打开。'
    if (globalRisk && globalRisk.mode !== 'normal') return `风险模式为 ${globalRisk.mode}，当前只允许查询和撤单。`
    return ''
  }, [configured, environment, globalRisk, health.data, health.loading, healthData?.live_approved, reachable, tradingEnabled])

  const formError = useMemo(() => {
    if (!form.accountId.trim()) return '请填写本地账户账本 ID'
    if (!form.strategyId.trim() || !form.strategyVersion.trim()) return '请选择已导入的策略版本'
    const quantity = Number(form.quantity)
    if (!Number.isFinite(quantity) || quantity <= 0) return '数量必须为正数'
    if (instrument && quantity < instrument.minimum_quantity) return `数量不得低于 ${instrument.minimum_quantity}`
    const price = Number(form.price)
    if (!Number.isFinite(price) || price <= 0) return '限价必须为正数'
    const leverage = Number(form.leverage)
    if (!Number.isFinite(leverage) || leverage <= 0) return '杠杆必须为正数'
    return ''
  }, [form, instrument])

  const notionalHint = useMemo(() => {
    const quantity = Number(form.quantity)
    const price = Number(form.price)
    if (!Number.isFinite(quantity) || !Number.isFinite(price) || quantity <= 0 || price <= 0) return ''
    const multiplier = instrument?.contract_size ?? 1
    return `估算名义价值 ${(quantity * price * multiplier).toLocaleString('zh-CN', { maximumFractionDigits: 4 })} USDT · 合约乘数 ${multiplier}`
  }, [form.price, form.quantity, instrument?.contract_size])

  function setProtectivePrice() {
    if (!instrument?.reference_price) return
    const tick = instrument.price_tick || 0.1
    const raw = instrument.reference_price * (form.side === 'buy' ? 0.95 : 1.05)
    const rounded = Math.round(raw / tick) * tick
    setForm((previous) => ({ ...previous, price: rounded.toFixed(Math.max(0, String(tick).split('.')[1]?.length ?? 0)) }))
  }

  async function submitOrder() {
    setSubmitting(true)
    setReceiptError('')
    const payload: TradingOrderIntent = {
      strategy_id: form.strategyId.trim(),
      strategy_version: form.strategyVersion.trim(),
      intent_id: intentId,
      account_id: form.accountId.trim(),
      symbol: form.symbol,
      side: form.side,
      order_type: 'limit',
      quantity: Number(form.quantity),
      price: Number(form.price),
      leverage: Number(form.leverage),
    }
    try {
      const response = await api.tradingSubmitOrder(payload)
      setReceipt(response)
      if (response.data?.order_id) setOrderLookupId(response.data.order_id)
      dashboard.refetch()
    } catch (reason) {
      setReceipt(null)
      setReceiptError(reason instanceof Error ? reason.message : String(reason))
      throw reason
    } finally {
      setSubmitting(false)
    }
  }

  async function lookupOrder() {
    if (!orderLookupId.trim()) return
    setLookupError('')
    try {
      setLookup(await api.tradingOrder(orderLookupId.trim()))
    } catch (reason) {
      setLookup(null)
      setLookupError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  async function cancelOrder(orderId: string) {
    setLookupError('')
    try {
      const response = await api.tradingCancelOrder(orderId)
      setLookup(response)
      setOrderLookupId(orderId)
      dashboard.refetch()
    } catch (reason) {
      setLookupError(reason instanceof Error ? reason.message : String(reason))
      throw reason
    }
  }

  async function runOperation(kind: 'recover' | 'reconcile') {
    setOperationLoading(true)
    setOperationError('')
    setOperationMessage('')
    try {
      if (kind === 'recover') {
        const response = await api.tradingRecoverOrders()
        const count = Array.isArray(response.data) ? response.data.length : 0
        setOperationMessage(`订单恢复完成，共检查 ${count} 笔未决订单。`)
      } else {
        const response = await api.tradingReconcile(form.accountId.trim())
        const differenceIds = (response.data as { difference_ids?: string[] } | null)?.difference_ids ?? []
        setOperationMessage(differenceIds.length ? `对账完成，发现 ${differenceIds.length} 项差异。` : '对账完成，未发现新差异。')
      }
      dashboard.refetch()
    } catch (reason) {
      setOperationError(reason instanceof Error ? reason.message : String(reason))
      throw reason
    } finally {
      setOperationLoading(false)
    }
  }

  const selectedStrategyKey = strategyKey(form.strategyId, form.strategyVersion)
  const selectedStrategy = dashboardData?.strategies.find(
    (item) => strategyKey(item.strategy_id, item.version) === selectedStrategyKey,
  ) ?? null

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="交易"
        title="Demo 交易台"
        description="策略版本、订单与 OKX 状态"
        metrics={[
          { label: '环境', value: <Badge variant={environment === 'live' ? 'down' : environment === 'demo' ? 'warn' : 'neutral'} dot>{ENVIRONMENT_LABELS[environment ?? ''] ?? '未知'}</Badge> },
          { label: '风险', value: <Badge variant={globalRisk?.mode === 'normal' ? 'up' : 'warn'} dot>{globalRisk?.mode ?? '未知'}</Badge> },
          { label: '策略版本', value: dashboardData?.strategies.length ?? 0 },
          { label: '开放差异', value: openDiffs.length },
        ]}
      />

      <nav className={s.crossLinks} aria-label="交易工作区快捷入口">
        {(WORKSPACE_QUICK_LINKS['/trading'] ?? []).map((link) => <Link key={link.to} to={link.to}>{link.label}</Link>)}
      </nav>

      <div className={s.statusStack}>
        <ContractStatusBar envelope={health.data ?? null} transportError={health.error} label="交易服务" />
        <ContractStatusBar envelope={preflight.data ?? null} transportError={preflight.error} label="OKX 预检" />
      </div>

      <section className={s.operationStrip} aria-label="Demo 交易状态">
        <div><span>连接</span><strong>{reachable ? 'Runner 在线' : '不可达'}</strong><small>{dashboardData?.account_status.connected ? '账户快照已同步' : '等待账户快照'}</small></div>
        <div><span>合约规则</span><strong>{instrument ? `${instrument.minimum_quantity} 张起` : '读取中'}</strong><small>{instrument ? `步长 ${instrument.quantity_step} · tick ${instrument.price_tick}` : '来自 OKX'}</small></div>
        <div><span>时间偏差</span><strong>{preflight.data?.data?.clock.absolute_drift_ms ?? '—'} ms</strong><small>{preflight.data?.data?.clock.within_tolerance ? '签名时间正常' : '需要校时'}</small></div>
        <div><span>IP 白名单</span><strong>{preflight.data?.data?.ip_whitelist.status === 'configured' ? '已配置' : 'Demo 未配置'}</strong><small>实盘前必须配置</small></div>
      </section>

      {disabledReason ? <div className={s.blocked} role="alert"><ShieldAlert size={17} /><strong>新订单已锁定</strong><span>{disabledReason}</span></div> : null}
      {openDiffs.length ? <div className={s.diffAlert} role="alert"><ShieldAlert size={17} /><span>存在 {openDiffs.length} 项未解决对账差异，已阻止继续下单。</span><Link to="/account-risk">去账户风控处理</Link></div> : null}

      <Panel
        title="账户权益、收益与持仓"
        subtitle={accountSummary ? `账户 ${accountSummary.account_id} · 快照 ${formatTime(accountSummary.observed_at)}` : '尚未同步 OKX 账户快照'}
        actions={<Button variant="ghost" size="sm" icon={<RefreshCw size={15} />} onClick={() => void runOperation('reconcile')} loading={operationLoading} disabled={!configured || !form.accountId.trim()}>同步账户</Button>}
      >
        {accountSummary ? (
          <>
            <div className={s.accountMetrics}>
              <div><span>账户权益（USD 等值）</span><strong>{formatNumber(accountSummary.equity)} {accountSummary.equity_currency ?? 'USD'}</strong></div>
              <div><span>总收益</span><strong className={pnlClass(accountSummary.total_pnl)}>{formatNumber(accountSummary.total_pnl)} {accountSummary.equity_currency ?? 'USD'}</strong></div>
              <div><span>已实现盈亏</span><strong className={pnlClass(accountSummary.realized_pnl)}>{formatNumber(accountSummary.realized_pnl)} {accountSummary.equity_currency ?? 'USD'}</strong></div>
              <div><span>未实现盈亏</span><strong className={pnlClass(accountSummary.unrealized_pnl)}>{formatNumber(accountSummary.unrealized_pnl)} {accountSummary.equity_currency ?? 'USD'}</strong></div>
              <div><span>最大回撤</span><strong className={pnlClass(accountSummary.max_drawdown)}>{formatNumber(accountSummary.max_drawdown * 100)}%</strong></div>
            </div>
            <div className={s.accountTables}>
              <div>
                <h3>余额</h3>
                {accountBalances.length ? <div className={s.tableWrap}><table className={s.ordersTable}><thead><tr><th>币种</th><th>总额</th><th>可用</th><th>时间</th></tr></thead><tbody>{accountBalances.map((balance) => <tr key={`${balance.account_id}-${balance.currency}-${balance.observed_at}`}><td>{balance.currency}</td><td>{formatNumber(balance.total, 6)}</td><td>{formatNumber(balance.available, 6)}</td><td>{formatTime(balance.observed_at)}</td></tr>)}</tbody></table></div> : <EmptyState variant="no-data" title="暂无余额快照" desc="点击同步账户从 OKX 读取余额。" />}
              </div>
              <div>
                <h3>持仓</h3>
                {accountPositions.length ? <div className={s.tableWrap}><table className={s.ordersTable}><thead><tr><th>品种</th><th>方向</th><th>数量</th><th>开仓价</th><th>标记价</th><th>未实现盈亏</th></tr></thead><tbody>{accountPositions.map((position) => <tr key={`${position.account_id}-${position.symbol}-${position.observed_at}`}><td>{position.symbol}</td><td>{position.position_side === 'short' || position.quantity < 0 ? '空' : '多'}</td><td>{formatNumber(Math.abs(position.quantity), 4)}</td><td>{formatNumber(position.entry_price, 4)}</td><td>{formatNumber(position.mark_price, 4)}</td><td className={pnlClass(position.unrealized_pnl)}>{formatNumber(position.unrealized_pnl)} USD</td></tr>)}</tbody></table></div> : <EmptyState variant="no-data" title="暂无持仓" desc="当前账户没有持仓，或尚未完成账户同步。" />}
              </div>
            </div>
          </>
        ) : <EmptyState variant="no-data" title="暂无账户快照" desc="点击右上角“同步账户”读取余额、持仓和收益。" />}
      </Panel>

      <Panel title="创建 Demo 限价单" subtitle="同一 intent 重复提交只会返回同一笔订单；点击“新意图”后才会生成新订单。">
        <div className={s.orderFormGroups}>
          <section className={s.orderFormGroup} aria-labelledby="order-account-title">
            <header><h3 id="order-account-title">账户与策略</h3><p>选择本地账本和 Runner 已导入的不可变策略版本。</p></header>
            <div className={s.formGrid}>
              <Field label="本地账户账本" required hint="用于 Runner 追溯，不是 OKX 登录名">
                <Input value={form.accountId} onChange={(event) => setForm((previous) => ({ ...previous, accountId: event.target.value }))} />
              </Field>
              <Field label="策略版本" required hint="只显示 Runner 已导入的不可变版本">
                <Select
                  value={selectedStrategyKey}
                  options={(dashboardData?.strategies ?? []).map((item) => ({ value: strategyKey(item.strategy_id, item.version), label: `${item.strategy_id} · v${item.version}` }))}
                  onChange={(event) => {
                    const [strategyId, version] = event.target.value.split('::')
                    setForm((previous) => ({ ...previous, strategyId, strategyVersion: version }))
                  }}
                />
              </Field>
            </div>
          </section>
          <section className={s.orderFormGroup} aria-labelledby="order-contract-title">
            <header><h3 id="order-contract-title">合约与方向</h3><p>合约规则来自 OKX 预检结果。</p></header>
            <div className={s.formGrid}>
              <Field label="品种" required>
                <Select value={form.symbol} options={FIRST_PHASE_SYMBOLS.map((symbol) => ({ value: symbol, label: symbol }))} onChange={(event) => setForm((previous) => ({ ...previous, symbol: event.target.value }))} />
              </Field>
              <Field label="方向" required>
                <Select value={form.side} options={[{ value: 'buy', label: '买入 / 开多' }, { value: 'sell', label: '卖出 / 开空' }]} onChange={(event) => setForm((previous) => ({ ...previous, side: event.target.value as 'buy' | 'sell' }))} />
              </Field>
              <Field label="杠杆" required>
                <Input type="number" min="1" step="1" value={form.leverage} onChange={(event) => setForm((previous) => ({ ...previous, leverage: event.target.value }))} />
              </Field>
            </div>
          </section>
          <section className={s.orderFormGroup} aria-labelledby="order-size-title">
            <header><h3 id="order-size-title">数量与价格</h3><p>提交前核对最小数量、步长、价格精度和名义价值。</p></header>
            <div className={s.formGrid}>
              <Field label="数量（张）" required hint={instrument ? `最小 ${instrument.minimum_quantity}，步长 ${instrument.quantity_step}` : undefined}>
                <Input type="number" min={instrument?.minimum_quantity ?? 0} step={instrument?.quantity_step ?? 'any'} value={form.quantity} onChange={(event) => setForm((previous) => ({ ...previous, quantity: event.target.value }))} />
              </Field>
              <Field label="限价（USDT）" required hint={instrument?.reference_price ? `参考 ${instrument.reference_price}` : '以 OKX 行情为准'}>
                <div className={s.priceField}>
                  <Input type="number" min="0" step={instrument?.price_tick ?? 'any'} value={form.price} onChange={(event) => setForm((previous) => ({ ...previous, price: event.target.value }))} />
                  <Button type="button" variant="ghost" size="sm" onClick={setProtectivePrice} disabled={!instrument?.reference_price}>设置测试价</Button>
                </div>
              </Field>
            </div>
          </section>
        </div>

        <details className={s.traceDetails}>
          <summary>追溯详情</summary>
          <div>
            <Field label="订单意图" hint="保留此值可验证幂等重试">
              <Input value={intentId} readOnly />
            </Field>
          </div>
        </details>

        <section className={s.orderReview} aria-labelledby="order-review-title">
          <header><h3 id="order-review-title">提交复核</h3><p>确认策略约束、名义价值与当前环境后再提交。</p></header>
          {selectedStrategy ? <div className={s.strategyLine}><Activity size={16} /><span>{selectedStrategy.package.signal_frequency ?? '—'} 信号</span><span>{selectedStrategy.package.rebalance_frequency ?? '—'} 调仓</span><span>策略杠杆上限 {selectedStrategy.package.risk_limits?.max_leverage ?? '—'}x</span></div> : null}
          {notionalHint ? <p className={s.notional}>{notionalHint}</p> : null}
          {formError ? <p className={s.formError} role="alert">{formError}</p> : null}

          <div className={s.actions}>
            <ConfirmActionButton
              label={receipt?.data?.idempotent_replay ? '再次验证幂等' : '提交 Demo 订单'}
              variant="danger"
              title={`确认在【${ENVIRONMENT_LABELS[environment ?? ''] ?? '未知环境'}】提交订单`}
              description={`策略：${form.strategyId}@${form.strategyVersion}\n品种：${form.symbol}\n方向：${form.side}\n数量：${form.quantity || '未填'}\n价格：${form.price || '未填'}\n意图：${intentId}`}
              confirmLabel="确认提交"
              disabled={Boolean(disabledReason) || Boolean(formError) || submitting}
              onConfirm={submitOrder}
            />
            <Button variant="secondary" icon={<Plus size={16} />} onClick={() => { setIntentId(newIntentId()); setReceipt(null); setReceiptError('') }}>新意图</Button>
            <Button variant="ghost" icon={<RefreshCw size={16} />} onClick={() => { preflight.refetch(); dashboard.refetch() }}>刷新规则</Button>
          </div>
        </section>

        {receiptError ? <p className={s.formError} role="alert">提交失败：{receiptError}</p> : null}
        {receipt?.data ? (
          <div className={s.orderReceipt}>
            <div><span>状态</span><Badge variant={statusVariant(receipt.data.status)} dot>{receipt.data.status}</Badge></div>
            <div><span>内部订单</span><strong>{receipt.data.order_id}</strong></div>
            <div><span>OKX 订单</span><strong>{receipt.data.external_order_id ?? '待确认'}</strong></div>
            <div><span>幂等结果</span><strong>{receipt.data.idempotent_replay ? '命中原订单，未重复下单' : '首次创建'}</strong></div>
          </div>
        ) : null}
      </Panel>

      <Panel
        title="订单与执行"
        subtitle="开放订单可直接撤销；恢复和对账会向 OKX 读取真实状态。"
        actions={<Button variant="ghost" size="sm" icon={<RefreshCw size={15} />} onClick={dashboard.refetch} loading={dashboard.loading}>刷新</Button>}
      >
        <div className={s.executionActions}>
          <ConfirmActionButton label="恢复未决订单" variant="secondary" title="从 OKX 恢复未决订单" description="重新查询 PENDING、SUBMITTED、PARTIALLY_FILLED 和 UNKNOWN 订单，不会创建新订单。" confirmLabel="开始恢复" disabled={!configured || operationLoading} onConfirm={() => runOperation('recover')} />
          <ConfirmActionButton label="立即对账" variant="secondary" title="核对 Demo 账户" description={`账户：${form.accountId}\n核对订单、成交、余额和持仓。`} confirmLabel="开始对账" disabled={!configured || !form.accountId.trim() || operationLoading} onConfirm={() => runOperation('reconcile')} />
        </div>
        {operationMessage ? <p className={s.successMessage}>{operationMessage}</p> : null}
        {operationError ? <p className={s.formError} role="alert">{operationError}</p> : null}

        {recentOrders.length ? (
          <div className={s.tableWrap}>
            <table className={s.ordersTable}>
              <thead><tr><th>状态</th><th>策略</th><th>方向</th><th>数量 / 限价</th><th>更新时间</th><th><span className="sr-only">操作</span></th></tr></thead>
              <tbody>{recentOrders.map((order) => (
                <tr key={order.order_id}>
                  <td><Badge variant={statusVariant(order.status)} dot>{order.status}</Badge></td>
                  <td><strong>{order.strategy_id}</strong><small>v{order.strategy_version}</small></td>
                  <td>{order.side === 'buy' ? '买入' : '卖出'}</td>
                  <td>{order.quantity} / {order.price ?? '市价'}</td>
                  <td>{formatTime(order.updated_at)}</td>
                  <td className={s.rowActions}>
                    <Button variant="ghost" size="sm" icon={<Search size={15} />} title="查询订单" aria-label={`查询订单 ${order.order_id}`} onClick={() => { setOrderLookupId(order.order_id); void api.tradingOrder(order.order_id).then(setLookup) }} />
                    {OPEN_ORDER_STATUSES.has(order.status) ? <ConfirmActionButton label="撤单" title="确认撤销 Demo 订单" description={`订单：${order.order_id}\n当前状态：${order.status}`} confirmLabel="确认撤单" onConfirm={() => cancelOrder(order.order_id)} /> : null}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <EmptyState variant="no-data" title="暂无 Runner 订单" desc="选择策略版本并创建第一笔 Demo 订单。" />}

        <div className={s.lookupRow}>
          <Input value={orderLookupId} placeholder="内部订单 ID" onChange={(event) => setOrderLookupId(event.target.value)} />
          <Button variant="secondary" icon={<Search size={16} />} onClick={lookupOrder} disabled={!orderLookupId.trim()}>查询</Button>
          {orderLookupId && lookup?.data && OPEN_ORDER_STATUSES.has(lookup.data.status) ? <ConfirmActionButton label="撤单" title="确认撤销 Demo 订单" description={`订单：${orderLookupId}`} confirmLabel="确认撤单" onConfirm={() => cancelOrder(orderLookupId)} /> : null}
        </div>
        {lookupError ? <p className={s.formError} role="alert">{lookupError}</p> : null}
        {lookup?.data ? (
          <div className={s.lookupResult}>
            <div><span>订单</span><strong>{lookup.data.order_id}</strong></div>
            <div><span>状态</span><Badge variant={statusVariant(lookup.data.status)} dot>{lookup.data.status}</Badge></div>
            <div><span>OKX</span><strong>{lookup.data.external_order_id ?? '—'}</strong></div>
            <div><span>状态事件</span><strong>{lookup.data.events?.map((event) => event.to_status).join(' → ') || '—'}</strong></div>
          </div>
        ) : null}
      </Panel>

      <div className={s.footerActions}>
        <Link to="/account-risk"><ShieldAlert size={16} />账户风控与差异处理</Link>
        <Link to="/strategies"><ListRestart size={16} />策略与版本</Link>
        <Link to="/config"><XCircle size={16} />OKX 连接设置</Link>
      </div>
    </div>
  )
}

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { ContractEnvelope, TradingHealth, TradingOrderIntent } from '../api/types'
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

/**
 * 交易工作台（M2-05）。
 *
 * 边界（路线图 3.D）：
 *   - 浏览器只与 `/api/trading/*` 通信，永远不知道 Runner 地址与令牌。
 *   - 首期范围固定为 OKX 永续 SWAP + 限价单；服务端会再校验一次，前端只做提示。
 *   - 成交状态只以服务端返回为准，本页不缓存任何"已成交"的本地推断。
 */

const FIRST_PHASE_SYMBOLS = ['BTC-USDT-SWAP']
const ENVIRONMENT_LABELS: Record<string, string> = {
  shadow: '影子（只读，不下单）',
  demo: 'OKX 模拟盘 demo',
  live: 'OKX 实盘 live',
}

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
  accountId: '',
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

function envelopeError(envelope: ContractEnvelope<unknown> | null): string {
  if (!envelope?.error_code) return ''
  return `${envelope.error_code}${envelope.message ? ' · ' + envelope.message : ''}`
}

export default function TradingWorkspacePage() {
  const health = useApi(() => api.tradingHealth(), [], { retry: false, pollInterval: 20000 })
  const [dashboard, setDashboard] = useState<ContractEnvelope<Record<string, unknown>> | null>(null)
  const [dashboardError, setDashboardError] = useState('')
  const [dashboardLoading, setDashboardLoading] = useState(false)

  const [form, setForm] = useState<OrderForm>(EMPTY_FORM)
  const [intentId, setIntentId] = useState(newIntentId)
  const [receipt, setReceipt] = useState<ContractEnvelope<Record<string, unknown>> | null>(null)
  const [receiptError, setReceiptError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const [orderLookupId, setOrderLookupId] = useState('')
  const [lookup, setLookup] = useState<ContractEnvelope<Record<string, unknown>> | null>(null)
  const [lookupError, setLookupError] = useState('')

  const healthData: TradingHealth | null = health.data?.data ?? null
  const environment = healthData?.environment ?? null
  const tradingEnabled = Boolean(healthData?.trading_enabled)
  const reachable = Boolean(healthData?.reachable)
  const configured = Boolean(healthData?.configured)

  // 禁用原因必须可读：路线图 3.D「所有危险按钮提供禁用原因」。
  const disabledReason = useMemo(() => {
    if (health.loading && !health.data) return '正在读取交易服务状态…'
    if (!configured) return '未配置 Runner 地址（QH_RUNNER_BASE_URL），交易通道不可用。'
    if (!reachable) return '交易服务不可达，请先恢复 OKX Runner。'
    if (environment === 'shadow') return '当前为影子环境，只读，禁止下单。'
    if (environment === 'live' && !healthData?.live_approved) return '实盘环境未获批准（QH_RUNNER_LIVE_APPROVED 未置位）。'
    if (!tradingEnabled) return '服务端交易开关未打开。'
    return ''
  }, [configured, environment, health.data, health.loading, healthData?.live_approved, reachable, tradingEnabled])

  const formError = useMemo(() => {
    if (!form.accountId.trim()) return '请填写账户 ID'
    if (!form.strategyId.trim()) return '请填写策略 ID'
    if (!form.strategyVersion.trim()) return '请填写策略版本（必须是不可变版本号）'
    const quantity = Number(form.quantity)
    if (!Number.isFinite(quantity) || quantity <= 0) return '数量必须为正数'
    const price = Number(form.price)
    if (!Number.isFinite(price) || price <= 0) return '首期只支持限价单，价格必须为正数'
    const leverage = Number(form.leverage)
    if (!Number.isFinite(leverage) || leverage <= 0) return '杠杆必须为正数'
    return ''
  }, [form])

  const notionalHint = useMemo(() => {
    const quantity = Number(form.quantity)
    const price = Number(form.price)
    if (!Number.isFinite(quantity) || !Number.isFinite(price) || quantity <= 0 || price <= 0) return ''
    return `名义金额 ≈ ${(quantity * price).toLocaleString('zh-CN', { maximumFractionDigits: 4 })} USDT（不含手续费；实际费用以 OKX 回报为准）`
  }, [form.price, form.quantity])

  async function loadDashboard() {
    setDashboardLoading(true)
    setDashboardError('')
    try {
      setDashboard(await api.tradingDashboard())
    } catch (reason) {
      setDashboard(null)
      setDashboardError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setDashboardLoading(false)
    }
  }

  async function submitOrder() {
    setSubmitting(true)
    setReceiptError('')
    const intent: TradingOrderIntent = {
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
      const response = await api.tradingSubmitOrder(intent)
      setReceipt(response)
      // 提交成功后立即换新的幂等键，避免误把下一单当成重放。
      if (!response.error_code) setIntentId(newIntentId())
    } catch (reason) {
      setReceipt(null)
      setReceiptError(reason instanceof Error ? reason.message : String(reason))
      throw reason
    } finally {
      setSubmitting(false)
    }
  }

  async function lookupOrder() {
    setLookupError('')
    if (!orderLookupId.trim()) {
      setLookupError('请填写订单 ID 或 client_order_id')
      return
    }
    try {
      setLookup(await api.tradingOrder(orderLookupId.trim()))
    } catch (reason) {
      setLookup(null)
      setLookupError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  async function cancelOrder() {
    setLookupError('')
    try {
      setLookup(await api.tradingCancelOrder(orderLookupId.trim()))
    } catch (reason) {
      setLookupError(reason instanceof Error ? reason.message : String(reason))
      throw reason
    }
  }

  const environmentBadge = environment
    ? <Badge variant={environment === 'live' ? 'down' : environment === 'demo' ? 'warn' : 'neutral'} dot>
        {ENVIRONMENT_LABELS[environment] ?? environment}
      </Badge>
    : <Badge variant="neutral" dot>环境未知</Badge>

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="交易"
        title="交易工作台"
        description="下单、查询与撤单"
        metrics={[
          { label: '环境', value: environmentBadge },
          { label: '通道', value: reachable ? '已连接' : configured ? '不可达' : '未配置' },
          { label: '范围', value: '永续 SWAP · 限价' },
        ]}
      />

      {/*
        M2-08：移动端底部导航只有「总览/研究/交易/更多」四个直达入口，
        因此交易工作区内的兄弟页面必须在本页给出页内入口，
        保证「审信号 / 停机 / 对账」这些核心操作在两次点击内到达。
      */}
      <nav className={s.crossLinks} aria-label="交易工作区快捷入口">
        {(WORKSPACE_QUICK_LINKS['/trading'] ?? []).map((link) => (
          <Link key={link.to} to={link.to}>{link.label}</Link>
        ))}
      </nav>

      <ContractStatusBar
        envelope={health.data ?? null}
        transportError={health.error}
        label="交易服务健康"
      />

      {disabledReason ? (
        <div className={s.blocked} role="alert">
          <strong>当前不可下单</strong>
          <span>{disabledReason}</span>
        </div>
      ) : null}

      <Panel
        title="下单（限价 · 永续）"
        subtitle="提交前请确认账户、环境、品种、方向、数量与价格。风控结论以服务端与 Runner 为准。"
      >
        <div className={s.formGrid}>
          <Field label="账户 ID" required>
            <Input
              value={form.accountId}
              placeholder="OKX 子账户映射 ID"
              onChange={(event) => setForm((prev) => ({ ...prev, accountId: event.target.value }))}
            />
          </Field>
          <Field label="策略 ID" required>
            <Input
              value={form.strategyId}
              onChange={(event) => setForm((prev) => ({ ...prev, strategyId: event.target.value }))}
            />
          </Field>
          <Field label="策略版本" required hint="必须是已冻结的不可变版本号">
            <Input
              value={form.strategyVersion}
              onChange={(event) => setForm((prev) => ({ ...prev, strategyVersion: event.target.value }))}
            />
          </Field>
          <Field label="品种" required hint="首期仅开放永续 SWAP 白名单">
            <Select
              value={form.symbol}
              options={FIRST_PHASE_SYMBOLS.map((symbol) => ({ value: symbol, label: symbol }))}
              onChange={(event) => setForm((prev) => ({ ...prev, symbol: event.target.value }))}
            />
          </Field>
          <Field label="方向" required>
            <Select
              value={form.side}
              options={[{ value: 'buy', label: '买入 / 开多' }, { value: 'sell', label: '卖出 / 开空' }]}
              onChange={(event) => setForm((prev) => ({ ...prev, side: event.target.value as 'buy' | 'sell' }))}
            />
          </Field>
          <Field label="订单类型" hint="首期只支持限价单，市价单由服务端拒绝">
            <Input value="限价单 limit" readOnly />
          </Field>
          <Field label="数量" required>
            <Input
              type="number"
              min="0"
              step="any"
              value={form.quantity}
              onChange={(event) => setForm((prev) => ({ ...prev, quantity: event.target.value }))}
            />
          </Field>
          <Field label="价格" required>
            <Input
              type="number"
              min="0"
              step="any"
              value={form.price}
              onChange={(event) => setForm((prev) => ({ ...prev, price: event.target.value }))}
            />
          </Field>
          <Field label="杠杆" required>
            <Input
              type="number"
              min="0"
              step="any"
              value={form.leverage}
              onChange={(event) => setForm((prev) => ({ ...prev, leverage: event.target.value }))}
            />
          </Field>
          <Field label="幂等键 intent_id" hint="重复提交同一键必须返回同一笔订单">
            <Input value={intentId} readOnly />
          </Field>
        </div>

        {notionalHint ? <p className={s.notional}>{notionalHint}</p> : null}
        {formError ? <p className={s.formError} role="alert">{formError}</p> : null}

        <div className={s.actions}>
          <ConfirmActionButton
            label="提交订单"
            variant="danger"
            size="md"
            title={`确认在【${ENVIRONMENT_LABELS[environment ?? ''] ?? '未知环境'}】提交订单`}
            description={[
              `环境：${environment ?? '未知'}`,
              `账户：${form.accountId || '(未填)'}`,
              `品种：${form.symbol}`,
              `方向：${form.side === 'buy' ? '买入/开多' : '卖出/开空'}`,
              `类型：限价单`,
              `数量：${form.quantity || '(未填)'}`,
              `价格：${form.price || '(未填)'}`,
              `杠杆：${form.leverage}x`,
              `幂等键：${intentId}`,
              notionalHint,
            ].filter(Boolean).join('\n')}
            confirmLabel="确认提交"
            disabled={Boolean(disabledReason) || Boolean(formError) || submitting}
            onConfirm={submitOrder}
          />
          <Button variant="ghost" onClick={() => { setForm(EMPTY_FORM); setIntentId(newIntentId()); setReceipt(null); setReceiptError('') }}>
            重置表单
          </Button>
        </div>

        {receiptError ? <p className={s.formError} role="alert">提交失败：{receiptError}</p> : null}
        {receipt ? (
          <div className={s.receipt}>
            <ContractStatusBar envelope={receipt} label="下单回执" />
            {receipt.error_code ? (
              <p className={s.formError} role="alert">被拒绝：{envelopeError(receipt)}</p>
            ) : (
              <pre className={s.json}>{JSON.stringify(receipt.data, null, 2)}</pre>
            )}
          </div>
        ) : null}
      </Panel>

      <Panel
        title="订单查询与撤单"
        subtitle="订单与成交状态只以服务端返回为准，本页不做任何本地推断。"
      >
        <div className={s.lookupRow}>
          <Input
            value={orderLookupId}
            placeholder="订单 ID 或 client_order_id"
            onChange={(event) => setOrderLookupId(event.target.value)}
          />
          <Button variant="secondary" onClick={lookupOrder} disabled={!configured}>查询</Button>
          <ConfirmActionButton
            label="撤单"
            title={`确认在【${ENVIRONMENT_LABELS[environment ?? ''] ?? '未知环境'}】撤销订单`}
            description={`环境：${environment ?? '未知'}\n订单：${orderLookupId || '(未填)'}\n撤单结果以 OKX 回报为准。`}
            confirmLabel="确认撤单"
            disabled={Boolean(disabledReason) || !orderLookupId.trim()}
            onConfirm={cancelOrder}
          />
        </div>
        {lookupError ? <p className={s.formError} role="alert">{lookupError}</p> : null}
        {lookup ? (
          <div className={s.receipt}>
            <ContractStatusBar envelope={lookup} label="订单状态" />
            {lookup.data ? <pre className={s.json}>{JSON.stringify(lookup.data, null, 2)}</pre> : null}
          </div>
        ) : (
          <EmptyState variant="no-data" title="尚未查询订单" desc="输入订单 ID 后点击查询；无数据时不会显示任何占位订单。" />
        )}
      </Panel>

      <Panel
        title="Runner 交易看板"
        subtitle="来自 OKX Runner 的原始运行视图，仅在服务可达时可读。"
        actions={<Button variant="ghost" size="sm" loading={dashboardLoading} onClick={loadDashboard} disabled={!configured}>读取</Button>}
      >
        {dashboardError ? <p className={s.formError} role="alert">{dashboardError}</p> : null}
        {dashboard ? (
          <div className={s.receipt}>
            <ContractStatusBar envelope={dashboard} label="Runner 看板" />
            {dashboard.data ? <pre className={s.json}>{JSON.stringify(dashboard.data, null, 2)}</pre> : null}
          </div>
        ) : (
          <EmptyState variant="no-data" title="尚未读取看板" desc="点击「读取」按需拉取；不可达时显示真实错误，不降级到示例数据。" />
        )}
      </Panel>
    </div>
  )
}

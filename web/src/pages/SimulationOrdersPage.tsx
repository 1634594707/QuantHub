import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type {
  SimulationExecution,
  SimulationLedgerSyncStatus,
  SimulationOrder,
  SimulationOrderStatus,
} from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { ResponsiveDetails } from '../components/ui/ResponsiveDetails/ResponsiveDetails'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import '../styles/simulation.css'
import { useRecordNavigation } from '../hooks/useRecordNavigation'

const STATUS_META: Record<SimulationOrderStatus, string> = {
  pending: '待成交',
  partially_filled: '部分成交',
  filled: '已成交',
  cancelled: '已取消',
}

const LEDGER_SYNC_META: Record<SimulationLedgerSyncStatus, string> = {
  pending: '待同步',
  synced: '已同步',
  failed: '同步失败',
}

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

function remaining(order: SimulationOrder) {
  return Math.max(0, order.quantity - order.filled_quantity)
}

function formatQuantity(value: number) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 6 })
}

function ledgerSyncSummary(executions: SimulationExecution[]) {
  if (!executions.length) return null
  const failed = executions.filter((execution) => execution.ledger_sync_status === 'failed')
  const pending = executions.filter((execution) => execution.ledger_sync_status === 'pending')
  const synced = executions.filter((execution) => execution.ledger_sync_status === 'synced')
  const status: SimulationLedgerSyncStatus = failed.length ? 'failed' : pending.length ? 'pending' : 'synced'
  const latestSynced = [...synced].reverse().find((execution) => execution.ledger_trade_id)
  return {
    status,
    label: LEDGER_SYNC_META[status],
    detail: failed[0]?.ledger_sync_error || `${synced.length}/${executions.length} 笔账本流水`,
    latestTradeId: latestSynced?.ledger_trade_id ?? null,
  }
}

function isOrderStatus(value: string | null): value is SimulationOrderStatus {
  return Boolean(value && Object.prototype.hasOwnProperty.call(STATUS_META, value))
}

export default function SimulationOrdersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedOrderId = searchParams.get('order_id') || ''
  const requestedQuery = searchParams.get('q') || requestedOrderId
  const requestedStatus = searchParams.get('status')
  const requestedSymbol = searchParams.get('symbol') || ''
  const requestedMarket = searchParams.get('market') || 'a_shares'
  const requestedSide = searchParams.get('side')
  const [tick, setTick] = useState(0)
  const [status, setStatus] = useState<SimulationOrderStatus | ''>(() => isOrderStatus(requestedStatus) ? requestedStatus : '')
  const [query, setQuery] = useState(requestedQuery)
  const [selectedOrderId, setSelectedOrderId] = useState(requestedOrderId)
  const [actionId, setActionId] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [fillInputs, setFillInputs] = useState<Record<string, { price: string; quantity: string }>>({})
  const [form, setForm] = useState({
    symbol: requestedSymbol,
    market: requestedMarket,
    side: requestedSide === 'sell' ? 'sell' as const : 'buy' as const,
    quantity: 100,
  })
  const [creating, setCreating] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const orders = useApi(
    () => api.simulationOrders(status || undefined, undefined, 200),
    [tick, status],
    { retry: false, resetKey: status },
  )
  const account = useApi(() => api.simulationAccount(), [tick], { retry: false })
  const rows = orders.data?.orders ?? []

  async function loadMoreOrders() {
    const cursor = orders.data?.next_cursor
    if (!cursor || loadingMore) return
    setLoadingMore(true)
    setError('')
    try {
      const next = await api.simulationOrders(status || undefined, undefined, 200, cursor)
      orders.setData((previous) => {
        const existing = new Set(previous.orders.map((item) => item.id))
        return {
          ...next,
          count: previous.count + next.count,
          orders: [...previous.orders, ...next.orders.filter((item) => !existing.has(item.id))],
        }
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '继续加载模拟订单失败')
    } finally {
      setLoadingMore(false)
    }
  }

  useEffect(() => {
    setQuery(requestedQuery)
    setStatus(isOrderStatus(requestedStatus) ? requestedStatus : '')
    setSelectedOrderId(requestedOrderId)
  }, [requestedOrderId, requestedQuery, requestedStatus])

  function updateListState(key: 'q' | 'status', value: string): void {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key === 'q') next.delete('order_id')
    setSearchParams(next, { replace: true })
  }

  const filtered = useMemo(() => {
    const normalized = query.trim().toUpperCase()
    return rows.filter((order) => {
      if (status && order.status !== status) return false
      return !normalized || order.symbol.includes(normalized) || order.id.includes(normalized)
    })
  }, [query, rows, status])

  const activeCount = useMemo(
    () => rows.filter((order) => ['pending', 'partially_filled'].includes(order.status)).length,
    [rows],
  )
  const selectOrder = (orderId: string) => {
    setSelectedOrderId(orderId)
    const next = new URLSearchParams(searchParams)
    next.set('order_id', orderId)
    setSearchParams(next, { replace: true })
  }
  const handleOrderKeyDown = useRecordNavigation({
    keys: filtered.map((order) => order.id),
    activeKey: selectedOrderId || null,
    onSelect: selectOrder,
  })

  async function createOrder(event: React.FormEvent) {
    event.preventDefault()
    const symbol = form.symbol.trim().toUpperCase()
    if (!symbol) return
    setCreating(true)
    setError('')
    try {
      await api.createSimulationOrder({ ...form, symbol })
      setForm((current) => ({ ...current, symbol: '' }))
      setTick((value) => value + 1)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '模拟订单创建失败')
    } finally {
      setCreating(false)
    }
  }

  async function fill(order: SimulationOrder) {
    const input = fillInputs[order.id]
    const price = Number(input?.price)
    const quantity = input?.quantity ? Number(input.quantity) : remaining(order)
    if (!(price > 0) || !(quantity > 0)) {
      setError('成交价格和数量必须大于 0')
      return
    }
    setActionId(order.id)
    setError('')
    try {
      await api.fillSimulationOrder(order.id, { price, quantity })
      setTick((value) => value + 1)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '模拟成交失败')
    } finally {
      setActionId('')
    }
  }

  async function cancel(order: SimulationOrder) {
    setActionId(order.id)
    setError('')
    setMessage('')
    try {
      await api.cancelSimulationOrder(order.id)
      setTick((value) => value + 1)
      setMessage(`模拟订单 ${order.id} 已取消`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '取消订单失败')
      throw caught
    } finally {
      setActionId('')
    }
  }

  async function retryLedgerSync(order: SimulationOrder) {
    const failedExecutions = order.executions.filter(
      (execution) => execution.ledger_sync_status === 'failed',
    )
    if (!failedExecutions.length) return
    setActionId(`ledger:${order.id}`)
    setError('')
    try {
      for (const execution of failedExecutions) {
        await api.retrySimulationLedgerSync(order.id, execution.id)
      }
      setTick((value) => value + 1)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '账本同步重试失败')
    } finally {
      setActionId('')
    }
  }

  return (
    <div className="simulation-page">
      <WorkspaceHeader
        context="执行 / 模拟交易"
        title="模拟交易"
        description="本地订单与成交记录，不连接真实券商"
        metrics={[
          { label: '账户权益', value: `¥${account.data?.equity.toLocaleString('zh-CN') ?? '—'}` },
          { label: '可用现金', value: `¥${account.data?.cash.toLocaleString('zh-CN') ?? '—'}` },
          { label: '活动订单', value: activeCount },
          { label: '未实现盈亏', value: account.data?.unrealized_pnl.toLocaleString('zh-CN') ?? '—' },
        ]}
      />

      <AsyncStateBoundary
        loading={account.loading}
        error={account.error}
        reconnecting={account.reconnecting}
        hasData={account.data !== null}
        isEmpty={false}
        onRetry={account.refetch}
        loadingTitle="正在核对订单与成交…"
        emptyTitle="暂无账户数据"
      >
        <div className={`simulation-reconcile ${account.data ? (account.data.reconciled ? 'ok' : 'warn') : ''}`}>
          <span>{account.data?.reconciled ? '订单与成交已对账' : '存在订单对账差异'}</span>
          <span>成交 {account.data?.execution_count ?? 0} 笔</span>
          <span>持仓 {account.data?.positions.length ?? 0} 项</span>
          <span>累计费用 ¥{account.data?.total_fees.toLocaleString('zh-CN') ?? '—'}</span>
        </div>
      </AsyncStateBoundary>

      <form className="simulation-create" onSubmit={createOrder}>
        <label>标的代码<input value={form.symbol} onChange={(event) => setForm((current) => ({ ...current, symbol: event.target.value }))} placeholder="如 600519" /></label>
        <label>市场<select value={form.market} onChange={(event) => setForm((current) => ({ ...current, market: event.target.value }))}><option value="a_shares">A股</option><option value="us_stocks">美股</option><option value="crypto">加密</option></select></label>
        <label>方向<select value={form.side} onChange={(event) => setForm((current) => ({ ...current, side: event.target.value as 'buy' | 'sell' }))}><option value="buy">买入</option><option value="sell">卖出</option></select></label>
        <label>数量<input type="number" min="0.000001" step={form.market === 'a_shares' ? 100 : 0.01} value={form.quantity} onChange={(event) => setForm((current) => ({ ...current, quantity: Number(event.target.value) || 0 }))} /></label>
        <button type="submit" disabled={creating || !form.symbol.trim() || form.quantity <= 0}>{creating ? '创建中…' : '创建模拟订单'}</button>
      </form>

      <div className="simulation-toolbar">
        <input value={query} onChange={(event) => {
          setQuery(event.target.value)
          updateListState('q', event.target.value)
        }} placeholder="搜索标的或订单号" aria-label="搜索模拟订单" />
        <select value={status} onChange={(event) => {
          setStatus(event.target.value as SimulationOrderStatus | '')
          updateListState('status', event.target.value)
        }} aria-label="筛选订单状态">
          <option value="">全部状态</option>
          {(Object.entries(STATUS_META) as [SimulationOrderStatus, string][]).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </select>
        <RefreshControl onRefresh={orders.refetch} refreshing={orders.loading || orders.reconnecting} updatedAt={orders.updatedAt} />
        {error && <span role="alert">{error}</span>}
      </div>
      {message && <div className="simulation-notice success" role="status">{message}</div>}

      <div className="simulation-table" tabIndex={0} onKeyDown={handleOrderKeyDown} aria-label="可用方向键选择模拟订单">
        <div className="simulation-row head"><span>状态</span><span>订单 / 标的</span><span>方向</span><span>委托 / 成交</span><span>均价</span><span>来源</span><span>时间</span><span>成交操作</span></div>
        <AsyncStateBoundary
          loading={orders.loading}
          error={orders.error}
          reconnecting={orders.reconnecting}
          hasData={orders.data !== null}
          isEmpty={rows.length === 0}
          onRetry={orders.refetch}
          loadingTitle="正在读取模拟订单…"
          emptyTitle="暂无模拟订单"
        >
          {filtered.length ? filtered.map((order) => {
            const active = order.status === 'pending' || order.status === 'partially_filled'
            const input = fillInputs[order.id] ?? { price: '', quantity: String(remaining(order)) }
            const sync = ledgerSyncSummary(order.executions)
            return (
              <div className={`simulation-row ${selectedOrderId === order.id ? 'selected' : ''}`} key={order.id} onClick={() => selectOrder(order.id)}>
              <span><b className={`simulation-status ${order.status}`}>{STATUS_META[order.status]}</b></span>
              <span><b className="mono-num">{order.symbol}</b><small>{order.id}</small></span>
              <span><b className={order.side}>{order.side === 'buy' ? '买入' : '卖出'}</b><small>{order.market}</small></span>
              <ResponsiveDetails className="simulation-row-details" compactAt={820} summary="查看成交与账本详情">
                <span><b className="mono-num">{formatQuantity(order.quantity)}</b><small>已成交 {formatQuantity(order.filled_quantity)} · 剩余 {formatQuantity(remaining(order))}</small></span>
                <span><b className="mono-num">{order.average_price?.toFixed(3) ?? '—'}</b><small>{order.order_type === 'market' ? '市价' : `限价 ${order.limit_price}`}</small></span>
                <span>
                  <b>{order.signal_id ? '信号转单' : '手工模拟'}</b>
                  <small>{order.signal_id ?? order.account_id}</small>
                  {sync && <>
                    <b className={`simulation-ledger-sync ${sync.status}`}>{sync.label}</b>
                    <small title={sync.detail}>{sync.detail}</small>
                    {sync.latestTradeId && (
                      <Link
                        className="simulation-ledger-link"
                        to={`/ledger?tab=trades&trade_id=${encodeURIComponent(sync.latestTradeId)}`}
                        onClick={(event) => event.stopPropagation()}
                      >
                        查看账本成交
                      </Link>
                    )}
                  </>}
                </span>
                <span><b>{formatTime(order.created_at)}</b><small>{order.executions.length ? `${order.executions.length} 笔成交` : '尚未成交'}</small></span>
                <span className="simulation-actions">
                  {active && <>
                    <input type="number" min="0.000001" step="0.01" value={input.price} placeholder="成交价" aria-label={`${order.symbol} 成交价格`} onChange={(event) => setFillInputs((current) => ({ ...current, [order.id]: { ...input, price: event.target.value } }))} />
                    <input type="number" min="0.000001" max={remaining(order)} step="0.01" value={input.quantity} aria-label={`${order.symbol} 成交数量`} onChange={(event) => setFillInputs((current) => ({ ...current, [order.id]: { ...input, quantity: event.target.value } }))} />
                    <button type="button" disabled={Boolean(actionId)} onClick={() => void fill(order)}>{actionId === order.id ? '处理中' : '成交'}</button>
                    <ConfirmActionButton
                      label="取消"
                      title="确认取消模拟订单"
                      description={`取消后订单 ${order.id} 不再接受新的模拟成交；已有成交与账本流水保持不变。`}
                      confirmLabel="确认取消"
                      disabled={Boolean(actionId)}
                      onConfirm={() => cancel(order)}
                    />
                  </>}
                  {sync?.status === 'failed' && (
                    <button
                      type="button"
                      className="ledger-retry"
                      disabled={Boolean(actionId)}
                      onClick={() => void retryLedgerSync(order)}
                    >
                      {actionId === `ledger:${order.id}` ? '重试中' : '重试账本'}
                    </button>
                  )}
                </span>
              </ResponsiveDetails>
              </div>
            )
          }) : <div className="simulation-empty">当前筛选条件下没有模拟订单。</div>}
        </AsyncStateBoundary>
        {orders.data?.next_cursor && (
          <button type="button" className="simulation-load-more" disabled={loadingMore} onClick={() => void loadMoreOrders()}>
            {loadingMore ? '加载中…' : `继续加载 · 已显示 ${rows.length} / ${orders.data.total}`}
          </button>
        )}
      </div>
    </div>
  )
}

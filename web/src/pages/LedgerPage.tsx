import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { LedgerBenchmark, LedgerCashEntry, LedgerPosition, LedgerTrade } from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import { Table, type Column } from '../components/ui/Table/Table'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { TradeAnalyticsPanel } from '../components/ledger/TradeAnalyticsPanel'
import s from './OperationsPages.module.css'

type LedgerTab = 'positions' | 'trades' | 'cash' | 'performance'

function isLedgerTab(value: string | null): value is LedgerTab {
  return value === 'positions' || value === 'trades' || value === 'cash' || value === 'performance'
}

const MARKETS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'crypto', label: '加密' },
  { value: 'us_stocks', label: '美股' },
  { value: 'mt5', label: 'MT5' },
]

function money(value: number | undefined): string {
  return typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—'
}

function time(value: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}

export default function LedgerPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const focusedTradeId = searchParams.get('trade_id')?.trim() ?? ''
  const focusedInstrumentId = searchParams.get('instrument_id')?.trim() ?? ''
  const focusedTradeMode = Boolean(focusedTradeId)
  const [tick, setTick] = useState(0)
  const [tab, setTab] = useState<LedgerTab>(() => (isLedgerTab(requestedTab) ? requestedTab : 'positions'))
  const summary = useApi(() => api.ledgerSummary(), [tick], { enabled: !focusedTradeMode, retry: false })
  const positions = useApi(() => api.ledgerPositions(), [tick], { enabled: !focusedTradeMode, retry: false })
  const trades = useApi(() => api.ledgerTrades(undefined, 100), [tick], { retry: false })
  const cash = useApi(() => api.ledgerCash(100), [tick], { enabled: !focusedTradeMode, retry: false })
  const performance = useApi(() => api.ledgerPerformance(), [tick], { enabled: !focusedTradeMode, retry: false })
  const tradeAnalytics = useApi(() => api.ledgerTradeAnalytics(), [tick], { enabled: !focusedTradeMode, retry: false })
  const attribution = useApi(() => api.ledgerAttribution('month'), [tick], { enabled: !focusedTradeMode, retry: false })
  const exposures = useApi(() => api.ledgerExposures(), [tick], { enabled: !focusedTradeMode, retry: false })
  const benchmarks = useApi(() => api.ledgerBenchmarks(), [tick], { enabled: !focusedTradeMode, retry: false })
  const corrections = useApi(() => api.ledgerCorrections(undefined, undefined, 50), [tick], { enabled: !focusedTradeMode, retry: false })
  const [actionError, setActionError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [savingTrade, setSavingTrade] = useState(false)
  const [savingCash, setSavingCash] = useState(false)
  const [savingBenchmark, setSavingBenchmark] = useState(false)
  const [loadingMoreTrades, setLoadingMoreTrades] = useState(false)
  const [loadingMoreCash, setLoadingMoreCash] = useState(false)
  const [entryMode, setEntryMode] = useState<'trade' | 'cash' | null>(null)
  const [tradeCorrectionId, setTradeCorrectionId] = useState('')
  const [cashCorrectionId, setCashCorrectionId] = useState('')
  const [benchmarkCorrectionId, setBenchmarkCorrectionId] = useState('')
  const [correctionReason, setCorrectionReason] = useState('')
  const [reviewInstrumentId, setReviewInstrumentId] = useState('')
  const decisionContext = useApi(
    () => api.ledgerPositionDecisionContext(reviewInstrumentId),
    [reviewInstrumentId, tick],
    { enabled: Boolean(reviewInstrumentId), retry: false, resetKey: reviewInstrumentId },
  )
  const [tradeForm, setTradeForm] = useState({
    code: '', market: 'a_shares', direction: 'buy' as 'buy' | 'sell', quantity: 100,
    price: 0, fee: 0, source: 'manual', note: '',
  })
  const [cashForm, setCashForm] = useState({
    direction: 'in' as 'in' | 'out', amount: 0, currency: 'CNY', source: 'manual', note: '',
  })
  const [benchmarkForm, setBenchmarkForm] = useState({
    name: '', code: '', market: 'a_shares',
  })
  const [benchmarkPoints, setBenchmarkPoints] = useState([{ t: '', equity: '' }])
  const [benchmarkMetrics, setBenchmarkMetrics] = useState([{ key: '', value: '' }])

  const metrics = summary.data?.summary

  function refresh(message = '') {
    setActionMessage(message)
    setTick((value) => value + 1)
  }

  function refetchPerformance() {
    void performance.refetch()
    void tradeAnalytics.refetch()
    void exposures.refetch()
  }

  async function loadMoreTrades() {
    const cursor = trades.data?.next_cursor
    if (!cursor || loadingMoreTrades) return
    setLoadingMoreTrades(true)
    setActionError('')
    try {
      const page = await api.ledgerTrades(undefined, 100, cursor)
      trades.setData((current) => {
        const ids = new Set(current.trades.map((trade) => trade.id))
        return {
          ...current,
          trades: [...current.trades, ...page.trades.filter((trade) => !ids.has(trade.id))],
          count: current.trades.length + page.trades.filter((trade) => !ids.has(trade.id)).length,
          total: page.total,
          next_cursor: page.next_cursor,
        }
      })
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '继续加载成交流水失败')
    } finally {
      setLoadingMoreTrades(false)
    }
  }

  async function loadMoreCash() {
    const cursor = cash.data?.next_cursor
    if (!cursor || loadingMoreCash) return
    setLoadingMoreCash(true)
    setActionError('')
    try {
      const page = await api.ledgerCash(100, cursor)
      cash.setData((current) => {
        const ids = new Set(current.entries.map((entry) => entry.id))
        return {
          ...current,
          entries: [...current.entries, ...page.entries.filter((entry) => !ids.has(entry.id))],
          count: current.entries.length + page.entries.filter((entry) => !ids.has(entry.id)).length,
          total: page.total,
          next_cursor: page.next_cursor,
        }
      })
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '继续加载现金流水失败')
    } finally {
      setLoadingMoreCash(false)
    }
  }

  async function recordTrade(event: React.FormEvent) {
    event.preventDefault()
    const code = tradeForm.code.trim().toUpperCase()
    if (!code || tradeForm.quantity <= 0 || tradeForm.price <= 0 || (tradeCorrectionId && !correctionReason.trim())) return
    setSavingTrade(true)
    setActionError('')
    setActionMessage('')
    try {
      const resolved = await api.resolveInstrument(code, tradeForm.market)
      const instrument = resolved.instrument
      const payload = {
        instrument_id: instrument.instrument_id,
        code: instrument.code,
        market: instrument.market,
        direction: tradeForm.direction,
        quantity: tradeForm.quantity,
        price: tradeForm.price,
        fee: tradeForm.fee,
        source: tradeForm.source,
        note: tradeForm.note.trim(),
      }
      if (tradeCorrectionId) {
        await api.correctLedgerTrade(tradeCorrectionId, { ...payload, reason: correctionReason.trim() })
      } else {
        await api.recordLedgerTrade(payload)
      }
      setTradeForm((current) => ({ ...current, code: '', price: 0, fee: 0, note: '' }))
      setTradeCorrectionId('')
      setCorrectionReason('')
      setEntryMode(null)
      refresh(tradeCorrectionId ? '成交流水已更正并保留前后值' : `成交已写入 ${instrument.instrument_id}`)
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '成交流水保存失败')
    } finally {
      setSavingTrade(false)
    }
  }

  async function recordCash(event: React.FormEvent) {
    event.preventDefault()
    if (cashForm.amount <= 0 || (cashCorrectionId && !correctionReason.trim())) return
    setSavingCash(true)
    setActionError('')
    setActionMessage('')
    try {
      const payload = { ...cashForm, note: cashForm.note.trim() }
      if (cashCorrectionId) {
        await api.correctLedgerCash(cashCorrectionId, { ...payload, reason: correctionReason.trim() })
      } else {
        await api.recordLedgerCash(payload)
      }
      setCashForm((current) => ({ ...current, amount: 0, note: '' }))
      setCashCorrectionId('')
      setCorrectionReason('')
      setEntryMode(null)
      refresh(cashCorrectionId ? '现金流水已更正并保留前后值' : '现金流水已写入账本')
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '现金流水保存失败')
    } finally {
      setSavingCash(false)
    }
  }

  async function registerBenchmark(event: React.FormEvent) {
    event.preventDefault()
    if (!benchmarkForm.name.trim() || !benchmarkForm.code.trim() || (benchmarkCorrectionId && !correctionReason.trim())) return
    setSavingBenchmark(true)
    setActionError('')
    setActionMessage('')
    try {
      const equityCurve = benchmarkPoints
        .filter((point) => point.t.trim() || point.equity.trim())
        .map((point) => {
          const equity = Number(point.equity)
          if (!point.t.trim() || !Number.isFinite(equity)) throw new Error('每个权益点都需要有效时间和权益值')
          return { t: point.t.trim(), equity }
        })
      const metrics = Object.fromEntries(benchmarkMetrics
        .filter((metric) => metric.key.trim())
        .map((metric) => {
          const normalized = metric.value.trim()
          const numeric = Number(normalized)
          return [metric.key.trim(), normalized !== '' && Number.isFinite(numeric) ? numeric : normalized]
        }))
      const payload = {
        name: benchmarkForm.name.trim(), code: benchmarkForm.code.trim().toUpperCase(),
        market: benchmarkForm.market, equity_curve: equityCurve, metrics,
      }
      if (benchmarkCorrectionId) {
        await api.correctLedgerBenchmark(benchmarkCorrectionId, { ...payload, reason: correctionReason.trim() })
      } else {
        await api.registerLedgerBenchmark(payload)
      }
      setBenchmarkCorrectionId('')
      setCorrectionReason('')
      refresh(benchmarkCorrectionId ? '基准已更正并保留前后值' : '基准已经登记')
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '基准登记失败')
    } finally {
      setSavingBenchmark(false)
    }
  }

  function beginTradeCorrection(row: LedgerTrade) {
    setCashCorrectionId('')
    setBenchmarkCorrectionId('')
    setTradeCorrectionId(row.id)
    setCorrectionReason('')
    setTradeForm({
      code: row.code, market: row.market, direction: row.direction, quantity: row.quantity,
      price: row.price, fee: row.fee, source: row.source, note: row.note,
    })
    setEntryMode('trade')
  }

  function beginCashCorrection(row: LedgerCashEntry) {
    setTradeCorrectionId('')
    setBenchmarkCorrectionId('')
    setCashCorrectionId(row.id)
    setCorrectionReason('')
    setCashForm({
      direction: row.direction, amount: row.amount, currency: row.currency,
      source: row.source, note: row.note,
    })
    setEntryMode('cash')
  }

  function beginBenchmarkCorrection(row: LedgerBenchmark) {
    setTradeCorrectionId('')
    setCashCorrectionId('')
    setBenchmarkCorrectionId(row.id)
    setCorrectionReason('')
    setBenchmarkForm({ name: row.name, code: row.code, market: row.market })
    setBenchmarkPoints(row.equity_curve.length
      ? row.equity_curve.map((point) => ({ t: String(point.t ?? ''), equity: String(point.equity ?? '') }))
      : [{ t: '', equity: '' }])
    setBenchmarkMetrics(Object.keys(row.metrics).length
      ? Object.entries(row.metrics).map(([key, value]) => ({ key, value: String(value ?? '') }))
      : [{ key: '', value: '' }])
  }

  const positionColumns: Column<LedgerPosition>[] = [
    { key: 'code', header: '标的', render: (row) => <><b className={s.code}>{row.code}</b><div className={s.meta}>{row.market}</div></> },
    { key: 'quantity', header: '数量', align: 'right', render: (row) => <span className={s.code}>{row.quantity}</span> },
    { key: 'average_cost', header: '均价', align: 'right', render: (row) => <span className={s.code}>{money(row.average_cost)}</span> },
    { key: 'last_price', header: '最新价', align: 'right', render: (row) => <span className={s.code}>{money(row.last_price)}</span> },
    { key: 'market_value', header: '市值', align: 'right', render: (row) => <span className={s.code}>{money(row.market_value)}</span> },
    { key: 'realized_pnl', header: '已实现', align: 'right', render: (row) => <span className={row.realized_pnl >= 0 ? s.positive : s.negative}>{money(row.realized_pnl)}</span> },
    { key: 'unrealized_pnl', header: '未实现', align: 'right', render: (row) => <span className={row.unrealized_pnl >= 0 ? s.positive : s.negative}>{money(row.unrealized_pnl)}</span> },
    { key: 'actions', header: '下钻', render: (row) => <span className={s.rowActions}><Button variant="link" size="sm" onClick={() => openInstrumentTrades(row.instrument_id)}>成交</Button><Link to={`/research/${encodeURIComponent(row.code)}?market=${encodeURIComponent(row.market)}&view=history`}>研究</Link><Button variant="link" size="sm" onClick={() => setReviewInstrumentId(row.instrument_id)}>{row.unrealized_pnl < 0 ? '亏损复盘' : '决策复盘'}</Button></span> },
  ]
  const tradeColumns: Column<LedgerTrade>[] = [
    { key: 'ts', header: '时间', render: (row) => time(row.ts) },
    { key: 'code', header: '标的', render: (row) => <><b className={s.code}>{row.code}</b><div className={s.meta}>{row.instrument_id}</div></> },
    { key: 'direction', header: '方向', render: (row) => <span className={row.direction === 'buy' ? s.positive : s.negative}>{row.direction === 'buy' ? '买入' : '卖出'}</span> },
    { key: 'quantity', header: '数量', align: 'right', render: (row) => <span className={s.code}>{row.quantity}</span> },
    { key: 'price', header: '价格', align: 'right', render: (row) => <span className={s.code}>{money(row.price)}</span> },
    { key: 'fee', header: '费用', align: 'right', render: (row) => <span className={s.code}>{money(row.fee)}</span> },
    { key: 'source', header: '来源', render: (row) => row.source },
    { key: 'note', header: '备注', render: (row) => row.note || '—' },
    { key: 'actions', header: '操作', render: (row) => <Button variant="link" size="sm" onClick={() => beginTradeCorrection(row)}>更正</Button> },
  ]
  const cashColumns: Column<LedgerCashEntry>[] = [
    { key: 'ts', header: '时间', render: (row) => time(row.ts) },
    { key: 'direction', header: '方向', render: (row) => <span className={row.direction === 'in' ? s.positive : s.negative}>{row.direction === 'in' ? '入金' : '出金'}</span> },
    { key: 'amount', header: '金额', align: 'right', render: (row) => <span className={s.code}>{money(row.amount)} {row.currency}</span> },
    { key: 'source', header: '来源', render: (row) => row.source },
    { key: 'note', header: '备注', render: (row) => row.note || '—' },
    { key: 'actions', header: '操作', render: (row) => <Button variant="link" size="sm" onClick={() => beginCashCorrection(row)}>更正</Button> },
  ]

  const marketExposure = useMemo(() => Object.entries(exposures.data?.by_market ?? {}), [exposures.data?.by_market])
  const visibleTrades = useMemo(
    () => focusedTradeId
      ? (trades.data?.trades ?? []).filter((trade) => trade.id === focusedTradeId)
      : focusedInstrumentId
        ? (trades.data?.trades ?? []).filter((trade) => trade.instrument_id === focusedInstrumentId)
        : (trades.data?.trades ?? []),
    [focusedInstrumentId, focusedTradeId, trades.data?.trades],
  )

  const recentEntries = useMemo(() => [
    ...(trades.data?.trades ?? []).slice(0, 4).map((trade) => ({
      id: trade.id, ts: trade.ts, kind: '成交', primary: `${trade.code} ${trade.direction === 'buy' ? '买入' : '卖出'}`,
      secondary: `${trade.quantity.toLocaleString('zh-CN')} @ ${money(trade.price)}`,
    })),
    ...(cash.data?.entries ?? []).slice(0, 4).map((entry) => ({
      id: entry.id, ts: entry.ts, kind: '现金', primary: entry.direction === 'in' ? '入金' : '出金',
      secondary: `${money(entry.amount)} ${entry.currency}`,
    })),
  ].sort((left, right) => right.ts - left.ts).slice(0, 5), [cash.data?.entries, trades.data?.trades])

  const detailState = tab === 'positions'
    ? {
      loading: positions.loading,
      error: positions.error,
      reconnecting: positions.reconnecting,
      hasData: positions.data !== null,
      isEmpty: (positions.data?.positions.length ?? 0) === 0,
      refetch: positions.refetch,
      emptyTitle: '暂无持仓',
    }
    : tab === 'trades'
      ? {
        loading: trades.loading,
        error: trades.error,
        reconnecting: trades.reconnecting,
        hasData: trades.data !== null,
        isEmpty: visibleTrades.length === 0,
        refetch: trades.refetch,
        emptyTitle: focusedTradeId ? '未找到指定成交' : '暂无成交',
      }
      : tab === 'cash'
        ? {
          loading: cash.loading,
          error: cash.error,
          reconnecting: cash.reconnecting,
          hasData: cash.data !== null,
          isEmpty: (cash.data?.entries.length ?? 0) === 0,
          refetch: cash.refetch,
          emptyTitle: '暂无现金流水',
        }
        : {
          loading: performance.loading || tradeAnalytics.loading || exposures.loading,
          error: performance.error || tradeAnalytics.error || exposures.error,
          reconnecting: performance.reconnecting || tradeAnalytics.reconnecting || exposures.reconnecting,
          hasData: performance.data !== null && tradeAnalytics.data !== null && exposures.data !== null,
          isEmpty: false,
          refetch: refetchPerformance,
          emptyTitle: '暂无绩效数据',
        }
  const refreshing = summary.loading || positions.loading || trades.loading || cash.loading
    || performance.loading || tradeAnalytics.loading || exposures.loading || benchmarks.loading

  function clearTradeFocus() {
    const next = new URLSearchParams(searchParams)
    next.delete('trade_id')
    next.set('tab', 'trades')
    setSearchParams(next, { replace: true })
  }

  function openInstrumentTrades(instrumentId: string) {
    const next = new URLSearchParams(searchParams)
    next.delete('trade_id')
    next.set('instrument_id', instrumentId)
    next.set('tab', 'trades')
    setTab('trades')
    setSearchParams(next, { replace: true })
  }

  function clearInstrumentFocus() {
    const next = new URLSearchParams(searchParams)
    next.delete('instrument_id')
    next.set('tab', 'trades')
    setSearchParams(next, { replace: true })
  }

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="执行 / 账户账本"
        title="流水驱动的组合账户"
        metrics={[
          { label: 'NAV', value: `¥${money(metrics?.nav)}` },
          { label: '现金', value: `¥${money(metrics?.cash)}` },
          { label: '持仓数', value: metrics?.n_positions ?? 0 },
          { label: '总收益率', value: `${metrics?.return_pct ?? 0}%` },
        ]}
      />

      <AsyncStateBoundary
        loading={summary.loading}
        error={summary.error}
        reconnecting={summary.reconnecting}
        hasData={summary.data !== null || focusedTradeMode}
        isEmpty={false}
        onRetry={summary.refetch}
        loadingTitle="正在读取账户汇总…"
        emptyTitle="暂无账户汇总"
      >
        <div className={s.metrics}>
          <div className={s.metric}><span>持仓市值</span><b>¥{money(metrics?.market_value)}</b></div>
          <div className={s.metric}><span>已实现盈亏</span><b className={(metrics?.realized_pnl ?? 0) >= 0 ? s.positive : s.negative}>¥{money(metrics?.realized_pnl)}</b></div>
          <div className={s.metric}><span>未实现盈亏</span><b className={(metrics?.unrealized_pnl ?? 0) >= 0 ? s.positive : s.negative}>¥{money(metrics?.unrealized_pnl)}</b></div>
          <div className={s.metric}><span>最大回撤</span><b>{performance.data?.max_drawdown.max_drawdown_pct ?? 0}%</b></div>
        </div>
      </AsyncStateBoundary>

      <section className={`${s.section} ${s.recentSection}`}>
        <div className={s.sectionHead}><div><h2>最近流水</h2><span>成交与现金按时间合并</span></div></div>
        <div className={s.recentList}>
          {recentEntries.map((entry) => (
            <div key={`${entry.kind}:${entry.id}`}>
              <span>{entry.kind}</span><b>{entry.primary}</b><strong className={s.code}>{entry.secondary}</strong><time>{time(entry.ts)}</time>
            </div>
          ))}
          {!recentEntries.length && <div className={s.empty}>暂无流水</div>}
        </div>
      </section>

      {actionError && <div className={s.error}>{actionError}</div>}
      {actionMessage && <div className={s.success}>{actionMessage}</div>}
      {focusedTradeId && tab === 'trades' && (
        <div className={s.contextNotice}>
          <span>正在查看模拟执行同步的账本成交 <b className={s.code}>{focusedTradeId}</b></span>
          <Button variant="link" size="sm" onClick={clearTradeFocus}>显示全部成交</Button>
        </div>
      )}
      {focusedInstrumentId && tab === 'trades' && (
        <div className={s.contextNotice}>
          <span>正在查看标的 <b className={s.code}>{focusedInstrumentId}</b> 的组成成交</span>
          <Button variant="link" size="sm" onClick={clearInstrumentFocus}>显示全部成交</Button>
        </div>
      )}

      <div className={s.entryLauncher}>
        <span>{tradeCorrectionId || cashCorrectionId ? '更正流水' : '录入流水'}</span>
        <Button size="sm" variant={entryMode === 'trade' ? 'primary' : 'secondary'} onClick={() => { setTradeCorrectionId(''); setCorrectionReason(''); setEntryMode(entryMode === 'trade' ? null : 'trade') }}>成交</Button>
        <Button size="sm" variant={entryMode === 'cash' ? 'primary' : 'secondary'} onClick={() => { setCashCorrectionId(''); setCorrectionReason(''); setEntryMode(entryMode === 'cash' ? null : 'cash') }}>现金</Button>
      </div>

      {entryMode && <div className={`${s.grid2} ${s.entryGrid}`}>
        {entryMode === 'trade' && (
        <form className={s.section} onSubmit={recordTrade}>
          <div className={s.sectionHead}><div><h2>录入成交</h2><span>先解析 Instrument，再写入成交流水</span></div></div>
          <div className={s.formGrid}>
            {tradeCorrectionId && <label className={s.grow}>更正原因<Input value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} /></label>}
            <label>标的代码<Input value={tradeForm.code} onChange={(event) => setTradeForm({ ...tradeForm, code: event.target.value })} placeholder="600519" /></label>
            <label>市场<Select options={MARKETS} value={tradeForm.market} onChange={(event) => setTradeForm({ ...tradeForm, market: event.target.value })} /></label>
            <label>方向<Select options={[{ value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]} value={tradeForm.direction} onChange={(event) => setTradeForm({ ...tradeForm, direction: event.target.value as 'buy' | 'sell' })} /></label>
            <label>数量<Input type="number" min="0.000001" step="any" value={tradeForm.quantity} onChange={(event) => setTradeForm({ ...tradeForm, quantity: Number(event.target.value) })} /></label>
            <label>价格<Input type="number" min="0.000001" step="any" value={tradeForm.price} onChange={(event) => setTradeForm({ ...tradeForm, price: Number(event.target.value) })} /></label>
            <label>费用<Input type="number" min="0" step="0.01" value={tradeForm.fee} onChange={(event) => setTradeForm({ ...tradeForm, fee: Number(event.target.value) })} /></label>
            <label>来源<Input value={tradeForm.source} onChange={(event) => setTradeForm({ ...tradeForm, source: event.target.value })} /></label>
            <label>备注<Input value={tradeForm.note} onChange={(event) => setTradeForm({ ...tradeForm, note: event.target.value })} /></label>
          </div>
          <div className={s.formActions}><Button type="submit" variant="primary" loading={savingTrade}>{tradeCorrectionId ? '提交成交更正' : '写入成交'}</Button></div>
        </form>
        )}

        {entryMode === 'cash' && (
        <form className={s.section} onSubmit={recordCash}>
          <div className={s.sectionHead}><div><h2>录入现金流水</h2><span>现金余额由现金与成交现金流共同计算</span></div></div>
          <div className={s.formGrid}>
            {cashCorrectionId && <label className={s.grow}>更正原因<Input value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} /></label>}
            <label>方向<Select options={[{ value: 'in', label: '入金' }, { value: 'out', label: '出金' }]} value={cashForm.direction} onChange={(event) => setCashForm({ ...cashForm, direction: event.target.value as 'in' | 'out' })} /></label>
            <label>金额<Input type="number" min="0.01" step="0.01" value={cashForm.amount} onChange={(event) => setCashForm({ ...cashForm, amount: Number(event.target.value) })} /></label>
            <label>币种<Input value={cashForm.currency} onChange={(event) => setCashForm({ ...cashForm, currency: event.target.value })} /></label>
            <label>来源<Input value={cashForm.source} onChange={(event) => setCashForm({ ...cashForm, source: event.target.value })} /></label>
            <label className={s.grow}>备注<Input value={cashForm.note} onChange={(event) => setCashForm({ ...cashForm, note: event.target.value })} /></label>
          </div>
          <div className={s.formActions}><Button type="submit" variant="primary" loading={savingCash}>{cashCorrectionId ? '提交现金更正' : '写入现金流水'}</Button></div>
        </form>
        )}
      </div>}

      <section className={s.section}>
        <div className={s.sectionHead}>
          <div><h2>账本明细</h2><span>研究持仓、模拟账户和本账本保持独立</span></div>
          <RefreshControl onRefresh={() => refresh()} refreshing={refreshing} updatedAt={detailState.hasData ? (tab === 'positions' ? positions.updatedAt : tab === 'trades' ? trades.updatedAt : tab === 'cash' ? cash.updatedAt : performance.updatedAt) : null} />
        </div>
        <div className={s.tabs}>
          {([
            ['positions', `持仓 ${positions.data?.count ?? 0}`],
            ['trades', `成交 ${trades.data?.total ?? 0}`],
            ['cash', `现金 ${cash.data?.total ?? 0}`],
            ['performance', '绩效与敞口'],
          ] as Array<[LedgerTab, string]>).map(([value, label]) => (
            <button type="button" key={value} className={`${s.tab} ${tab === value ? s.tabActive : ''}`} onClick={() => setTab(value)}>{label}</button>
          ))}
        </div>
        <AsyncStateBoundary
          loading={detailState.loading}
          error={detailState.error}
          reconnecting={detailState.reconnecting}
          hasData={detailState.hasData}
          isEmpty={detailState.isEmpty}
          onRetry={detailState.refetch}
          loadingTitle="正在读取账本明细…"
          emptyTitle={detailState.emptyTitle}
        >
          {tab === 'positions' && <>
            <Table className={s.desktopLedgerTable} columns={positionColumns} rows={positions.data?.positions ?? []} rowKey={(row) => row.instrument_id} density="compact" />
            <div className={s.mobileLedgerRecords}>{(positions.data?.positions ?? []).map((row) => <details key={row.instrument_id}><summary><b className={s.code}>{row.code}</b><span>{row.quantity.toLocaleString('zh-CN')} 股</span><strong className={row.unrealized_pnl >= 0 ? s.positive : s.negative}>{money(row.unrealized_pnl)}</strong></summary><div><span>市场 {row.market}</span><span>均价 {money(row.average_cost)}</span><span>最新价 {money(row.last_price)}</span><span>市值 {money(row.market_value)}</span></div><footer><Button variant="link" size="sm" onClick={() => openInstrumentTrades(row.instrument_id)}>查看组成成交</Button><Link to={`/research/${encodeURIComponent(row.code)}?market=${encodeURIComponent(row.market)}&view=history`}>研究历史</Link><Button variant="link" size="sm" onClick={() => setReviewInstrumentId(row.instrument_id)}>{row.unrealized_pnl < 0 ? '亏损复盘' : '决策复盘'}</Button></footer></details>)}</div>
          </>}
          {tab === 'trades' && <>
            <Table className={s.desktopLedgerTable} columns={tradeColumns} rows={visibleTrades} rowKey={(row) => row.id} density="compact" />
            <div className={s.mobileLedgerRecords}>{visibleTrades.map((row) => <details key={row.id}><summary><b className={s.code}>{row.code}</b><span className={row.direction === 'buy' ? s.positive : s.negative}>{row.direction === 'buy' ? '买入' : '卖出'}</span><strong>{money(row.quantity)} @ {money(row.price)}</strong></summary><div><span>时间 {time(row.ts)}</span><span>费用 {money(row.fee)}</span><span>来源 {row.source || '—'}</span><span>备注 {row.note || '—'}</span></div><footer><Button variant="link" size="sm" onClick={() => beginTradeCorrection(row)}>更正成交</Button></footer></details>)}</div>
            {trades.data?.next_cursor && <div className={s.formActions}><Button variant="secondary" loading={loadingMoreTrades} onClick={() => void loadMoreTrades()}>继续加载 · 已显示 {trades.data.trades.length} / {trades.data.total}</Button></div>}
          </>}
          {tab === 'cash' && <>
            <Table className={s.desktopLedgerTable} columns={cashColumns} rows={cash.data?.entries ?? []} rowKey={(row) => row.id} density="compact" />
            <div className={s.mobileLedgerRecords}>{(cash.data?.entries ?? []).map((row) => <details key={row.id}><summary><b className={row.direction === 'in' ? s.positive : s.negative}>{row.direction === 'in' ? '入金' : '出金'}</b><span>{row.currency}</span><strong>{money(row.amount)}</strong></summary><div><span>时间 {time(row.ts)}</span><span>来源 {row.source || '—'}</span><span>备注 {row.note || '—'}</span></div><footer><Button variant="link" size="sm" onClick={() => beginCashCorrection(row)}>更正现金</Button></footer></details>)}</div>
            {cash.data?.next_cursor && <div className={s.formActions}><Button variant="secondary" loading={loadingMoreCash} onClick={() => void loadMoreCash()}>继续加载 · 已显示 {cash.data.entries.length} / {cash.data.total}</Button></div>}
          </>}
          {tab === 'performance' && (
            <>
            <TradeAnalyticsPanel data={tradeAnalytics.data} />
            <div className={s.grid2}>
              <div className={s.subsection}>
                <div className={s.sectionHead}><h3>绩效</h3></div>
                <div className={s.metrics}>
                  <div className={s.metric}><span>TWR</span><b>{performance.data?.twr_pct ?? 0}%</b></div>
                  <div className={s.metric}><span>权益点</span><b>{performance.data?.equity_curve.length ?? 0}</b></div>
                  <div className={s.metric}><span>基准超额</span><b>{performance.data?.benchmark_excess?.excess_return_pct ?? '—'}{performance.data?.benchmark_excess ? '%' : ''}</b></div>
                  <div className={s.metric}><span>基准</span><b>{performance.data?.benchmark_excess?.benchmark_code ?? '—'}</b></div>
                </div>
                <div className={s.formActions}><Button size="sm" onClick={() => setTab('trades')}>查看组成成交</Button><Button size="sm" onClick={() => setTab('cash')}>查看现金流水</Button></div>
              </div>
              <div className={s.subsection}>
                <div className={s.sectionHead}><h3>市场敞口</h3><span>总市值 ¥{money(exposures.data?.total_market_value)}</span></div>
                {marketExposure.length ? marketExposure.map(([market, value]) => (
                  <div key={market} className={s.statusLine}>{market}<b className="mono-num"> ¥{money(value)}</b></div>
                )) : <div className={s.empty}>暂无市场敞口</div>}
              </div>
              <div className={s.subsection}>
                <div className={s.sectionHead}><h3>来源策略归因</h3><span>按月</span></div>
                {(attribution.data?.by_strategy ?? []).map((item) => <div className={s.statusLine} key={item.key}><span>{item.key} · {item.trade_count} 笔</span><b className={item.cash_flow >= 0 ? s.positive : s.negative}>{money(item.cash_flow)}</b></div>)}
              </div>
              <div className={s.subsection}>
                <div className={s.sectionHead}><h3>方向与时间归因</h3></div>
                {[...(attribution.data?.by_direction ?? []), ...(attribution.data?.by_period ?? [])].map((item) => <div className={s.statusLine} key={`${item.key}:${item.trade_count}`}><span>{item.key} · {item.trade_count} 笔</span><b>{money(item.notional)}</b></div>)}
              </div>
            </div>
            </>
          )}
        </AsyncStateBoundary>
      </section>

      {reviewInstrumentId && (
        <section className={s.section}>
          <div className={s.sectionHead}><div><h2>决策复盘时间线</h2><span>{reviewInstrumentId}</span></div><Button size="sm" variant="link" onClick={() => setReviewInstrumentId('')}>关闭</Button></div>
          <AsyncStateBoundary loading={decisionContext.loading} error={decisionContext.error} reconnecting={decisionContext.reconnecting} hasData={decisionContext.data !== null} isEmpty={(decisionContext.data?.timeline.count ?? 0) === 0} onRetry={decisionContext.refetch} loadingTitle="正在读取决策时间线…" emptyTitle="当前标的没有关联记录">
            <div className={s.timeline}>
              {(decisionContext.data?.timeline.events ?? []).map((event) => {
                const researchRunId = event.links.research_run_id
                const signalId = event.links.signal_id
                const orderId = event.links.order_id
                const ledgerTradeId = event.links.ledger_trade_id
                const href = researchRunId ? `/research/${encodeURIComponent(decisionContext.data?.position.code ?? '')}?market=${encodeURIComponent(decisionContext.data?.position.market ?? '')}&view=history&run_id=${encodeURIComponent(researchRunId)}` : signalId ? `/signals?signal_id=${encodeURIComponent(signalId)}` : orderId ? `/simulation?order_id=${encodeURIComponent(orderId)}` : ledgerTradeId ? `/ledger?tab=trades&trade_id=${encodeURIComponent(ledgerTradeId)}` : ''
                return <div key={`${event.kind}:${event.id}`}><time>{time(event.ts)}</time><b>{event.label}</b><span>{event.status}{event.note ? ` · ${event.note}` : ''}</span>{href && <Link to={href}>打开记录</Link>}</div>
              })}
            </div>
          </AsyncStateBoundary>
        </section>
      )}

      <section className={s.section}>
        <div className={s.sectionHead}><div><h2>基准管理</h2><span>当前登记 {benchmarks.data?.count ?? 0} 条</span></div></div>
        <AsyncStateBoundary
          loading={benchmarks.loading}
          error={benchmarks.error}
          reconnecting={benchmarks.reconnecting}
          hasData={benchmarks.data !== null}
          isEmpty={false}
          onRetry={benchmarks.refetch}
          loadingTitle="正在读取基准记录…"
          emptyTitle="暂无基准记录"
        >
          <form onSubmit={registerBenchmark}>
            <div className={s.formGrid}>
              {benchmarkCorrectionId && <label className={s.grow}>更正原因<Input value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} /></label>}
              <label>名称<Input value={benchmarkForm.name} onChange={(event) => setBenchmarkForm({ ...benchmarkForm, name: event.target.value })} /></label>
              <label>代码<Input value={benchmarkForm.code} onChange={(event) => setBenchmarkForm({ ...benchmarkForm, code: event.target.value })} /></label>
              <label>市场<Select options={MARKETS} value={benchmarkForm.market} onChange={(event) => setBenchmarkForm({ ...benchmarkForm, market: event.target.value })} /></label>
              <label>已登记基准<Input readOnly value={(benchmarks.data?.benchmarks ?? []).map((row) => row.code).join(' / ')} /></label>
              <fieldset className={s.controlledRows}>
                <legend>权益曲线</legend>
                {benchmarkPoints.map((point, index) => <div key={index}><Input aria-label={`权益点 ${index + 1} 时间`} placeholder="时间" value={point.t} onChange={(event) => setBenchmarkPoints((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, t: event.target.value } : row))} /><Input aria-label={`权益点 ${index + 1} 权益`} type="number" step="any" placeholder="权益" value={point.equity} onChange={(event) => setBenchmarkPoints((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, equity: event.target.value } : row))} />{benchmarkPoints.length > 1 && <Button type="button" variant="link" size="sm" onClick={() => setBenchmarkPoints((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}>移除</Button>}</div>)}
                <Button type="button" variant="link" size="sm" onClick={() => setBenchmarkPoints((rows) => [...rows, { t: '', equity: '' }])}>增加权益点</Button>
              </fieldset>
              <fieldset className={s.controlledRows}>
                <legend>指标</legend>
                {benchmarkMetrics.map((metric, index) => <div key={index}><Input aria-label={`指标 ${index + 1} 名称`} placeholder="名称" value={metric.key} onChange={(event) => setBenchmarkMetrics((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, key: event.target.value } : row))} /><Input aria-label={`指标 ${index + 1} 值`} placeholder="值" value={metric.value} onChange={(event) => setBenchmarkMetrics((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, value: event.target.value } : row))} />{benchmarkMetrics.length > 1 && <Button type="button" variant="link" size="sm" onClick={() => setBenchmarkMetrics((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}>移除</Button>}</div>)}
                <Button type="button" variant="link" size="sm" onClick={() => setBenchmarkMetrics((rows) => [...rows, { key: '', value: '' }])}>增加指标</Button>
              </fieldset>
            </div>
            <div className={s.formActions}><Button type="submit" variant="primary" loading={savingBenchmark}>{benchmarkCorrectionId ? '提交基准更正' : '登记基准'}</Button></div>
          </form>
          <div className={s.recentList}>
            {(benchmarks.data?.benchmarks ?? []).map((row) => <div key={row.id}><span>基准</span><b>{row.name}</b><strong className={s.code}>{row.code}</strong><Button variant="link" size="sm" onClick={() => beginBenchmarkCorrection(row)}>更正</Button></div>)}
          </div>
        </AsyncStateBoundary>
      </section>

      <section className={s.section}>
        <div className={s.sectionHead}><div><h2>更正记录</h2><span>保留原因与前后值</span></div></div>
        <div className={s.recentList}>
          {(corrections.data?.corrections ?? []).map((row) => <div key={row.id}><span>{row.entity_type}</span><b>{row.reason}</b><strong className={s.code}>{row.entity_id.slice(0, 12)}</strong><time>{time(row.created_at)}</time></div>)}
          {!corrections.data?.corrections.length && <div className={s.empty}>暂无更正记录</div>}
        </div>
      </section>
    </div>
  )
}

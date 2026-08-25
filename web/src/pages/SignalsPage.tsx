import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type {
  PublishSignalReq,
  ResearchRun,
  SignalLifecycleStatus,
  SignalResp,
  SimulationOrder,
  SimulationOrderPreview,
} from '../api/types'
import { useApi } from '../api/useApi'
import { DirectionDonut, ScoreHistogram, SourceBars } from '../components/SignalViz'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { EmptyState } from '../components/ui/EmptyState/EmptyState'
import { Input } from '../components/ui/Input/Input'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { Select } from '../components/ui/Select/Select'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { useRecordNavigation } from '../hooks/useRecordNavigation'
import { dirBucket, dirLabel, matchDir } from '../lib/signal-utils'
import s from './SignalsPage.module.css'
import { researchRunHref } from '../lib/researchResults'

type Dir = 'all' | 'buy' | 'sell' | 'hold'
type StatusFilter = 'all' | SignalLifecycleStatus

const STATUS_META: Record<SignalLifecycleStatus, { label: string; hint: string }> = {
  new: { label: '待审核', hint: '等待人工复核' },
  accepted: { label: '已接受', hint: '可转为模拟订单' },
  rejected: { label: '已拒绝', hint: '审核已终止' },
  expired: { label: '已过期', hint: '信号已超过有效期' },
  converted: { label: '已转订单', hint: '已关联模拟订单' },
}

const DIR_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'buy', label: '做多' },
  { value: 'sell', label: '做空' },
  { value: 'hold', label: '观望' },
]

const PUBLISH_MARKET_OPTIONS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '加密货币' },
]

const PUBLISH_DIRECTION_OPTIONS = [
  { value: 'buy', label: '做多' },
  { value: 'sell', label: '做空' },
  { value: 'hold', label: '观望' },
]

function signalStatus(signal: SignalResp): SignalLifecycleStatus {
  return signal.status ?? 'new'
}

function isSignalStatus(value: string | null): value is SignalLifecycleStatus {
  return Boolean(value && Object.prototype.hasOwnProperty.call(STATUS_META, value))
}

function isDirectionFilter(value: string | null): value is Dir {
  return value === 'all' || value === 'buy' || value === 'sell' || value === 'hold'
}

function signalKey(signal: SignalResp): string {
  return signal.id ?? `${signal.symbol}:${signal.market}:${signal.ts ?? ''}`
}

function fmtEpoch(epoch?: number | null): string {
  return epoch ? new Date(epoch * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function fmtTs(ts: string | null): string {
  if (!ts) return '—'
  const parsed = new Date(ts)
  if (Number.isNaN(parsed.getTime())) return ts
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

function dirClass(direction: string): 'long' | 'short' | 'hold' {
  const bucket = dirBucket(direction)
  return bucket === 'buy' ? 'long' : bucket === 'sell' ? 'short' : 'hold'
}

function formatNumber(value: number | null, maximumFractionDigits = 2): string {
  if (value == null) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits }).format(value)
}

function formatStructured(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

function formatRiskValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number') return formatNumber(value, 4)
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function csvEscape(value: string | number): string {
  const normalized = String(value)
  return /[",\n]/.test(normalized)
    ? `"${normalized.replace(/"/g, '""')}"`
    : normalized
}

function exportCsv(rows: SignalResp[]): void {
  const headers = ['标的', '方向', '状态', '得分', '置信度', '周期', '市场', '来源', '标签', '时间']
  const lines = rows.map((signal) => [
    signal.symbol,
    dirLabel(signal.direction),
    STATUS_META[signalStatus(signal)].label,
    signal.score.toFixed(2),
    `${(signal.confidence * 100).toFixed(1)}%`,
    signal.timeframe,
    signal.market,
    signal.source,
    signal.tags.join('|'),
    signal.ts ?? '',
  ].map(csvEscape).join(','))
  const blob = new Blob(['﻿' + [headers.join(','), ...lines].join('\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `signals_${Date.now()}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

export default function SignalsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedSignalId = searchParams.get('signal_id') || ''
  const requestedStatus = searchParams.get('status')
  const requestedQuery = searchParams.get('q') || ''
  const requestedDirection = searchParams.get('direction')
  const requestedMarket = searchParams.get('market') || 'all'
  const requestedSource = searchParams.get('source') || 'all'
  const [loadingMore, setLoadingMore] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [query, setQuery] = useState(requestedQuery)
  const [direction, setDirection] = useState<Dir>(() => isDirectionFilter(requestedDirection) ? requestedDirection : 'all')
  const [market, setMarket] = useState(requestedMarket)
  const [source, setSource] = useState(requestedSource)
  const [status, setStatus] = useState<StatusFilter>(() => isSignalStatus(requestedStatus) ? requestedStatus : 'all')
  const signals = useApi(
    () => api.signals(
      200,
      source === 'all' ? undefined : source,
      status === 'all' ? undefined : status,
      market === 'all' ? undefined : market,
    ),
    [source, status, market],
    { resetKey: `${source}|${status}|${market}` },
  )
  const rows = signals.data?.signals ?? []
  const [selectedKey, setSelectedKey] = useState(requestedSignalId)
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({})
  const [orderQuantities, setOrderQuantities] = useState<Record<string, number>>({})
  const [actionId, setActionId] = useState('')
  const [actionError, setActionError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [showPublish, setShowPublish] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [filling, setFilling] = useState(false)
  const [research, setResearch] = useState<ResearchRun | null>(null)
  const [researchLoading, setResearchLoading] = useState(false)
  const [researchError, setResearchError] = useState('')
  const [preview, setPreview] = useState<SimulationOrderPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [relatedOrder, setRelatedOrder] = useState<SimulationOrder | null>(null)
  const [relatedOrderLoading, setRelatedOrderLoading] = useState(false)
  const [relatedOrderError, setRelatedOrderError] = useState('')
  const researchRequest = useRef(0)
  const previewRequest = useRef(0)
  const orderRequest = useRef(0)
  const internalSearchesRef = useRef(new Set<string>())
  const [publishForm, setPublishForm] = useState<PublishSignalReq>({
    symbol: '',
    market: 'a_shares',
    direction: 'hold',
    score: 0.5,
    confidence: 0.5,
    source: 'manual',
    timeframe: 'realtime',
    tags: [],
  })

  async function loadMoreSignals() {
    const cursor = signals.data?.next_cursor
    if (!cursor || loadingMore) return
    setLoadingMore(true)
    setActionError('')
    try {
      const next = await api.signals(
        200,
        source === 'all' ? undefined : source,
        status === 'all' ? undefined : status,
        market === 'all' ? undefined : market,
        cursor,
      )
      signals.setData((previous) => {
        const existing = new Set(previous.signals.map((item) => item.id))
        return {
          ...next,
          count: previous.count + next.count,
          signals: [...previous.signals, ...next.signals.filter((item) => !existing.has(item.id))],
        }
      })
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '继续加载信号失败')
    } finally {
      setLoadingMore(false)
    }
  }
  const [publishTags, setPublishTags] = useState('')

  useEffect(() => {
    const currentSearch = searchParams.toString()
    if (internalSearchesRef.current.delete(currentSearch)) {
      return
    }
    setQuery(requestedQuery)
    setDirection(isDirectionFilter(requestedDirection) ? requestedDirection : 'all')
    setMarket(requestedMarket)
    setSource(requestedSource)
    setStatus(isSignalStatus(requestedStatus) ? requestedStatus : 'all')
    setSelectedKey(requestedSignalId)
  }, [requestedDirection, requestedMarket, requestedQuery, requestedSignalId, requestedSource, requestedStatus])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = window.setInterval(() => signals.refetch(), 5000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh])

  const markets = useMemo(
    () => Array.from(new Set(rows.map((row) => row.market))).sort(),
    [rows],
  )
  const sources = useMemo(
    () => Array.from(new Set(rows.map((row) => row.source))).sort(),
    [rows],
  )
  const marketOptions = useMemo(
    () => [{ value: 'all', label: '全部市场' }, ...markets.map((value) => ({ value, label: value }))],
    [markets],
  )
  const sourceOptions = useMemo(
    () => [{ value: 'all', label: '全部来源' }, ...sources.map((value) => ({ value, label: value }))],
    [sources],
  )
  const statusOptions = useMemo(
    () => [
      { value: 'all', label: '全部状态' },
      ...(Object.entries(STATUS_META) as Array<[SignalLifecycleStatus, { label: string }]>).map(
        ([value, meta]) => ({ value, label: meta.label }),
      ),
    ],
    [],
  )

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return rows.filter((signal) => {
      if (!matchDir(signal.direction, direction)) return false
      if (market !== 'all' && signal.market !== market) return false
      if (source !== 'all' && signal.source !== source) return false
      if (status !== 'all' && signalStatus(signal) !== status) return false
      if (!keyword) return true
      const searchable = `${signal.symbol} ${signal.tags.join(' ')} ${signal.source}`.toLowerCase()
      return searchable.includes(keyword)
    })
  }, [rows, query, direction, market, source, status])

  const selectedSignal = useMemo(
    () => filtered.find((signal) => signalKey(signal) === selectedKey) ?? filtered[0] ?? null,
    [filtered, selectedKey],
  )
  const queueKeys = useMemo(() => filtered.map(signalKey), [filtered])
  const handleQueueKeyDown = useRecordNavigation({
    keys: queueKeys,
    activeKey: selectedSignal ? signalKey(selectedSignal) : null,
    onSelect: setSelectedKey,
  })

  useEffect(() => {
    if (selectedSignal && selectedKey !== signalKey(selectedSignal)) {
      setSelectedKey(signalKey(selectedSignal))
    } else if (!selectedSignal && selectedKey && !signals.loading && rows.length > 0) {
      setSelectedKey('')
    }
  }, [rows.length, selectedSignal, selectedKey, signals.loading])

  useEffect(() => {
    const selectedId = selectedSignal?.id ?? ''
    if (selectedId === requestedSignalId) return
    const next = new URLSearchParams(searchParams)
    if (selectedId) next.set('signal_id', selectedId)
    else next.delete('signal_id')
    internalSearchesRef.current.add(next.toString())
    setSearchParams(next, { replace: true })
  }, [requestedSignalId, searchParams, selectedSignal?.id, setSearchParams])

  const researchRunId = selectedSignal && typeof selectedSignal.meta.research_run_id === 'string'
    ? selectedSignal.meta.research_run_id
    : ''

  useEffect(() => {
    const requestId = ++researchRequest.current
    setResearch(null)
    setResearchError('')
    if (!researchRunId) {
      setResearchLoading(false)
      return
    }
    setResearchLoading(true)
    api.researchRun(researchRunId)
      .then((response) => {
        if (researchRequest.current === requestId) setResearch(response.run)
      })
      .catch((error: unknown) => {
        if (researchRequest.current === requestId) {
          setResearchError(error instanceof Error ? error.message : '研究记录读取失败')
        }
      })
      .finally(() => {
        if (researchRequest.current === requestId) setResearchLoading(false)
      })
  }, [researchRunId])

  const selectedId = selectedSignal?.id ?? ''
  const selectedStatus = selectedSignal ? signalStatus(selectedSignal) : null
  const selectedQuantity = selectedId ? (orderQuantities[selectedId] ?? 100) : 100
  const selectedOrderId = selectedSignal?.order_id ?? ''

  useEffect(() => {
    const requestId = ++previewRequest.current
    setPreview(null)
    setPreviewError('')
    if (!selectedId || selectedStatus !== 'accepted') {
      setPreviewLoading(false)
      return
    }
    setPreviewLoading(true)
    const timer = window.setTimeout(() => {
      api.previewSimulationOrder({ signal_id: selectedId, quantity: selectedQuantity })
        .then((response) => {
          if (previewRequest.current === requestId) setPreview(response.preview)
        })
        .catch((error: unknown) => {
          if (previewRequest.current === requestId) {
            setPreviewError(error instanceof Error ? error.message : '订单影响评估失败')
          }
        })
        .finally(() => {
          if (previewRequest.current === requestId) setPreviewLoading(false)
        })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [selectedId, selectedStatus, selectedQuantity])

  useEffect(() => {
    const requestId = ++orderRequest.current
    setRelatedOrder(null)
    setRelatedOrderError('')
    if (!selectedOrderId) {
      setRelatedOrderLoading(false)
      return
    }
    setRelatedOrderLoading(true)
    api.simulationOrder(selectedOrderId)
      .then((response) => {
        if (orderRequest.current === requestId) setRelatedOrder(response.order)
      })
      .catch((error: unknown) => {
        if (orderRequest.current === requestId) {
          setRelatedOrderError(error instanceof Error ? error.message : '关联模拟订单读取失败')
        }
      })
      .finally(() => {
        if (orderRequest.current === requestId) setRelatedOrderLoading(false)
      })
  }, [selectedOrderId])

  const aggregate = useMemo(() => {
    const buy = filtered.filter((signal) => dirClass(signal.direction) === 'long').length
    const sell = filtered.filter((signal) => dirClass(signal.direction) === 'short').length
    const pending = filtered.filter((signal) => signalStatus(signal) === 'new').length
    const accepted = filtered.filter((signal) => signalStatus(signal) === 'accepted').length
    return { buy, sell, pending, accepted }
  }, [filtered])

  const hasFilters = query.trim() || direction !== 'all' || market !== 'all' || source !== 'all' || status !== 'all'

  function updateFilterParam(key: string, value: string, emptyValue: string): void {
    const next = new URLSearchParams(searchParams)
    if (!value || value === emptyValue) next.delete(key)
    else next.set(key, value)
    internalSearchesRef.current.add(next.toString())
    setSearchParams(next, { replace: true })
  }

  function clearFilters(): void {
    setQuery('')
    setDirection('all')
    setMarket('all')
    setSource('all')
    setStatus('all')
    const next = new URLSearchParams(searchParams)
    for (const key of ['q', 'direction', 'market', 'source', 'status']) next.delete(key)
    internalSearchesRef.current.add(next.toString())
    setSearchParams(next, { replace: true })
  }

  function selectNextPending(current: SignalResp): void {
    const next = filtered.find(
      (signal) => signalKey(signal) !== signalKey(current) && signalStatus(signal) === 'new',
    )
    if (next) setSelectedKey(signalKey(next))
  }

  async function runDefaultScan(): Promise<void> {
    setFilling(true)
    try {
      await api.runStrategy('supertrend', {})
    } finally {
      await signals.refetch()
      setFilling(false)
    }
  }

  async function handlePublish(): Promise<void> {
    if (!publishForm.symbol.trim()) return
    setPublishing(true)
    setActionError('')
    try {
      const tags = publishTags.split(/[,，\s]+/).map((tag) => tag.trim()).filter(Boolean)
      await api.publishSignal({ ...publishForm, symbol: publishForm.symbol.trim(), tags })
      setShowPublish(false)
      setPublishTags('')
      setPublishForm({
        symbol: '', market: 'a_shares', direction: 'hold', score: 0.5,
        confidence: 0.5, source: 'manual', timeframe: 'realtime', tags: [],
      })
      await signals.refetch()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '信号发布失败')
    } finally {
      setPublishing(false)
    }
  }

  async function handleDelete(signal: SignalResp): Promise<void> {
    if (!signal.id) return
    const next = filtered.find((item) => signalKey(item) !== signalKey(signal))
    setActionId(`${signal.id}:delete`)
    setActionError('')
    setActionMessage('')
    try {
      await api.deleteSignal(signal.id)
      signals.setData((previous) => ({
        ...previous,
        signals: previous.signals.filter((item) => item.id !== signal.id),
      }))
      setSelectedKey(next ? signalKey(next) : '')
      setActionMessage(`信号 ${signal.id} 已删除`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '信号删除失败')
      await signals.refetch()
      throw error
    } finally {
      setActionId('')
    }
  }

  async function handleStatus(signal: SignalResp, next: 'accepted' | 'rejected'): Promise<void> {
    if (!signal.id) return
    const pendingKey = `${signal.id}:${next}`
    setActionId(pendingKey)
    setActionError('')
    try {
      const response = await api.updateSignalStatus(signal.id, {
        status: next,
        note: reviewNotes[signal.id]?.trim() || undefined,
      })
      signals.setData((previous) => ({
        ...previous,
        signals: previous.signals.map((item) => item.id === signal.id ? response.signal : item),
      }))
      selectNextPending(signal)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '信号状态更新失败')
      await signals.refetch()
    } finally {
      setActionId('')
    }
  }

  async function handleConvert(signal: SignalResp): Promise<void> {
    if (!signal.id) return
    const pendingKey = `${signal.id}:converted`
    setActionId(pendingKey)
    setActionError('')
    try {
      await api.createSimulationOrder({
        signal_id: signal.id,
        quantity: orderQuantities[signal.id] ?? 100,
      })
      await signals.refetch()
      selectNextPending(signal)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '模拟订单创建失败')
      await signals.refetch()
    } finally {
      setActionId('')
    }
  }

  return (
    <>
      <WorkspaceHeader
        context="执行 / 信号审核"
        title="信号审核队列"
        metrics={[
          { label: '待审核', value: rows.filter((row) => signalStatus(row) === 'new').length },
          { label: '待执行', value: rows.filter((row) => signalStatus(row) === 'accepted').length },
          { label: '已转订单', value: rows.filter((row) => signalStatus(row) === 'converted').length },
        ]}
      />

      <main className={s.page} data-board="signals">
        <div className={s.toolbar}>
          <div className={s.toolbarStatus}>
            <span className={s.liveDot} data-live={autoRefresh} />
            <label className={s.autoRefresh}>
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(event) => setAutoRefresh(event.target.checked)}
              />
              <span>自动刷新</span>
            </label>
          </div>
          <div className={s.toolbarActions}>
            <RefreshControl onRefresh={signals.refetch} refreshing={signals.loading || signals.reconnecting} updatedAt={signals.updatedAt} />
            <Button variant="link" size="sm" onClick={() => exportCsv(filtered)} disabled={!filtered.length}>
              导出 CSV
            </Button>
            <Button variant="primary" size="sm" onClick={() => setShowPublish((value) => !value)}>
              发布信号
            </Button>
          </div>
        </div>

        {showPublish && (
          <section className={s.publishPanel} aria-label="发布手动信号">
            <div className={s.sectionHeading}>
              <div><h2>发布信号</h2><span>写入信号总线并进入审核队列</span></div>
            </div>
            <div className={s.publishGrid}>
              <label>标的代码<Input placeholder="如 600519" value={publishForm.symbol} onChange={(event) => setPublishForm((form) => ({ ...form, symbol: event.target.value }))} /></label>
              <label>市场<Select options={PUBLISH_MARKET_OPTIONS} value={publishForm.market} onChange={(event) => setPublishForm((form) => ({ ...form, market: event.target.value }))} /></label>
              <label>方向<Select options={PUBLISH_DIRECTION_OPTIONS} value={publishForm.direction} onChange={(event) => setPublishForm((form) => ({ ...form, direction: event.target.value }))} /></label>
              <label>得分<Input type="number" min={0} max={1} step={0.05} value={publishForm.score} onChange={(event) => setPublishForm((form) => ({ ...form, score: Number(event.target.value) || 0 }))} /></label>
              <label>置信度<Input type="number" min={0} max={1} step={0.05} value={publishForm.confidence} onChange={(event) => setPublishForm((form) => ({ ...form, confidence: Number(event.target.value) || 0 }))} /></label>
              <label>来源<Input value={publishForm.source} onChange={(event) => setPublishForm((form) => ({ ...form, source: event.target.value }))} /></label>
              <label>周期<Input value={publishForm.timeframe} onChange={(event) => setPublishForm((form) => ({ ...form, timeframe: event.target.value }))} /></label>
              <label>标签<Input placeholder="逗号分隔" value={publishTags} onChange={(event) => setPublishTags(event.target.value)} /></label>
            </div>
            <div className={s.publishActions}>
              <Button variant="primary" size="sm" onClick={() => void handlePublish()} loading={publishing} disabled={!publishForm.symbol.trim()}>确认发布</Button>
              <Button variant="link" size="sm" onClick={() => setShowPublish(false)}>取消</Button>
            </div>
          </section>
        )}

        <div className={s.metricStrip}>
          <span><small>筛选结果</small><b>{filtered.length}</b></span>
          <span><small>待审核</small><b>{aggregate.pending}</b></span>
          <span><small>待执行</small><b>{aggregate.accepted}</b></span>
          <span className={s.longMetric}><small>做多</small><b>{aggregate.buy}</b></span>
          <span className={s.shortMetric}><small>做空</small><b>{aggregate.sell}</b></span>
        </div>

        {actionError && (
          <div className={s.error} role="alert">{actionError}</div>
        )}
        {actionMessage && <div className={s.success} role="status">{actionMessage}</div>}

        <div className={s.workbench}>
          <aside className={s.queuePanel} aria-label="信号审核队列">
            <div className={s.panelHeading}>
              <div><h2>信号队列</h2><span>{filtered.length} 条记录</span></div>
              <Button variant="link" size="sm" onClick={clearFilters} disabled={!hasFilters}>清空</Button>
            </div>
            <div className={s.filters}>
              <Input
                placeholder="如 600519、突破"
                aria-label="搜索信号"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value)
                  updateFilterParam('q', event.target.value, '')
                }}
              />
              <SegmentedControl value={direction} onChange={(value) => {
                setDirection(value as Dir)
                updateFilterParam('direction', value, 'all')
              }} options={DIR_OPTIONS} size="sm" fullWidth />
              <div className={s.filterPair}>
                <Select options={statusOptions} value={status} onChange={(event) => {
                  setStatus(event.target.value as StatusFilter)
                  updateFilterParam('status', event.target.value, 'all')
                }} aria-label="审核状态" />
                <Select options={marketOptions} value={market} onChange={(event) => {
                  setMarket(event.target.value)
                  updateFilterParam('market', event.target.value, 'all')
                }} aria-label="市场" />
              </div>
              <Select options={sourceOptions} value={source} onChange={(event) => {
                setSource(event.target.value)
                updateFilterParam('source', event.target.value, 'all')
              }} aria-label="来源策略" />
            </div>

            <div className={s.queueList} tabIndex={0} onKeyDown={handleQueueKeyDown} aria-label="可用方向键选择信号">
              <AsyncStateBoundary
                loading={signals.loading}
                error={signals.error}
                reconnecting={signals.reconnecting}
                hasData={signals.data !== null}
                isEmpty={rows.length === 0}
                onRetry={signals.refetch}
                loadingTitle="正在读取信号…"
                loadingSkeleton
                skeletonRows={6}
                emptyTitle="信号审核队列为空"
                emptyAction={{ label: '运行默认扫描', onClick: runDefaultScan, loading: filling }}
              >
                {rows.length > 0 && !filtered.length && <div className={s.queueEmpty}>没有符合筛选条件的信号</div>}
                {filtered.map((signal) => {
                  const currentStatus = signalStatus(signal)
                  const selected = selectedSignal ? signalKey(selectedSignal) === signalKey(signal) : false
                  return (
                    <button
                      type="button"
                      key={signalKey(signal)}
                      data-signal-row
                      className={`${s.queueItem} sig-row-expand ${selected ? s.queueItemSelected : ''}`}
                      aria-pressed={selected}
                      onClick={() => setSelectedKey(signalKey(signal))}
                    >
                    <span className={s.queueIdentity}>
                      <b>{signal.symbol}</b>
                      <small>{signal.market} · {signal.timeframe}</small>
                    </span>
                    <span className={`${s.direction} ${s[dirClass(signal.direction)]}`}>{dirLabel(signal.direction)}</span>
                    <span className={s.queueScore}>{signal.score.toFixed(2)}</span>
                    <span className={`${s.status} ${s[`status_${currentStatus}`]}`} title={STATUS_META[currentStatus].hint}>{STATUS_META[currentStatus].label}</span>
                    <span className={s.queueSource}>{signal.source}</span>
                    <time>{fmtTs(signal.ts)}</time>
                    </button>
                  )
                })}
                {signals.data?.next_cursor && (
                  <Button fullWidth size="sm" variant="ghost" loading={loadingMore} onClick={() => void loadMoreSignals()}>
                    继续加载 · 已显示 {rows.length} / {signals.data.total}
                  </Button>
                )}
              </AsyncStateBoundary>
            </div>
          </aside>

          <section className={s.reviewPanel} aria-label="信号证据与审核">
            {!selectedSignal ? (
              <EmptyState title="选择一条信号开始审核" />
            ) : (
              <>
                <div className={s.selectedHeader}>
                  <div>
                    <span className={s.eyebrow}>{selectedSignal.market} / {selectedSignal.timeframe}</span>
                    <h2>{selectedSignal.symbol}</h2>
                    <p>{selectedSignal.source} · {fmtTs(selectedSignal.ts)}</p>
                  </div>
                  <div className={s.selectedState}>
                    <span className={`${s.directionLarge} ${s[dirClass(selectedSignal.direction)]}`}>{dirLabel(selectedSignal.direction)}</span>
                    <span className={`${s.status} ${s[`status_${signalStatus(selectedSignal)}`]}`}>{STATUS_META[signalStatus(selectedSignal)].label}</span>
                  </div>
                </div>

                <div className={s.scoreBand}>
                  <span><small>信号得分</small><b>{selectedSignal.score.toFixed(2)}</b></span>
                  <span><small>置信度</small><b>{(selectedSignal.confidence * 100).toFixed(1)}%</b></span>
                  <span><small>有效至</small><b>{fmtEpoch(selectedSignal.expires_at)}</b></span>
                </div>

                {selectedSignal.tags.length > 0 && (
                  <div className={s.tags}>{selectedSignal.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                )}

                <section className={s.reviewSection}>
                  <div className={s.sectionHeading}>
                    <div><h3>研究证据</h3><span>{researchRunId ? researchRunId : '当前信号未关联研究运行'}</span></div>
                    {research && (
                      <a className={s.textLink} href={researchRunHref(research)}>打开研究记录</a>
                    )}
                  </div>
                  {researchLoading && <div className={s.inlineState}>正在读取研究证据…</div>}
                  {researchError && <div className={s.inlineError}>{researchError}</div>}
                  {!researchLoading && !researchRunId && <div className={s.inlineState}>该信号没有 `research_run_id`，审核依据仅包含信号字段。</div>}
                  {research && (
                    <>
                      <div className={s.researchContext}>
                        <span><small>研究状态</small><b>{research.status}</b></span>
                        <span><small>模块</small><b>{research.modules.join(' / ') || '—'}</b></span>
                        <span><small>证据数</small><b>{research.evidence_count}</b></span>
                      </div>
                      <div className={s.summaryList}>
                        {Object.entries(research.summary).slice(0, 8).map(([key, value]) => (
                          <div key={key}><dt>{key}</dt><dd>{formatStructured(value)}</dd></div>
                        ))}
                        {!Object.keys(research.summary).length && <div className={s.inlineState}>研究摘要为空</div>}
                      </div>
                      {(research.evidence ?? []).length > 0 && (
                        <div className={s.evidenceList}>
                          {(research.evidence ?? []).map((evidence) => (
                            <article key={evidence.id}>
                              <div><b>{evidence.title || evidence.kind}</b><span>{evidence.source} · {evidence.kind}</span></div>
                              {evidence.uri && <a className={s.textLink} href={evidence.uri} target="_blank" rel="noreferrer">查看来源</a>}
                            </article>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </section>

                <section className={s.reviewSection}>
                  <div className={s.sectionHeading}><div><h3>审核决定</h3><span>备注会随审核状态持久化</span></div></div>
                  {selectedSignal.id && (signalStatus(selectedSignal) === 'new' || signalStatus(selectedSignal) === 'accepted') ? (
                    <>
                      <textarea
                        className={s.reviewNote}
                        value={reviewNotes[selectedSignal.id] ?? selectedSignal.decision_note ?? ''}
                        onChange={(event) => setReviewNotes((notes) => ({ ...notes, [selectedSignal.id!]: event.target.value }))}
                        placeholder="审核备注（可选）"
                        aria-label={`${selectedSignal.symbol} 审核备注`}
                      />
                      <div className={s.reviewActions}>
                        {signalStatus(selectedSignal) === 'new' && (
                          <Button variant="primary" onClick={() => void handleStatus(selectedSignal, 'accepted')} loading={actionId === `${selectedSignal.id}:accepted`}>接受</Button>
                        )}
                        <Button variant="danger" onClick={() => void handleStatus(selectedSignal, 'rejected')} loading={actionId === `${selectedSignal.id}:rejected`}>拒绝</Button>
                      </div>
                    </>
                  ) : (
                    <div className={s.decisionRecord}>
                      <span>审核时间 <b>{fmtEpoch(selectedSignal.reviewed_at)}</b></span>
                      <span>审核备注 <b>{selectedSignal.decision_note || '—'}</b></span>
                    </div>
                  )}
                </section>

                {selectedSignal.id && (
                  <div className={s.destructiveRow}>
                    <ConfirmActionButton
                      label="删除信号"
                      title="确认删除信号"
                      description={`删除后信号 ${selectedSignal.id} 将不再出现在审核队列。已生成的模拟订单与账本记录不会被删除。`}
                      confirmLabel="确认删除"
                      variant="link"
                      disabled={Boolean(actionId)}
                      onConfirm={() => handleDelete(selectedSignal)}
                    />
                  </div>
                )}
              </>
            )}
          </section>

          <aside className={s.executionPanel} aria-label="模拟交易影响">
            <div className={s.panelHeading}><div><h2>执行影响</h2><span>模拟账户 · 下单前预览</span></div></div>
            {!selectedSignal && <div className={s.inlineState}>选择信号后查看执行影响</div>}
            {selectedSignal && signalStatus(selectedSignal) === 'new' && <div className={s.executionNotice}>完成审核后才能创建模拟订单。</div>}
            {selectedSignal && signalStatus(selectedSignal) === 'rejected' && <div className={s.executionNotice}>该信号已拒绝，不再进入执行。</div>}
            {selectedSignal && signalStatus(selectedSignal) === 'expired' && <div className={s.executionNotice}>该信号已经过期，不能进入执行。</div>}
            {selectedSignal && signalStatus(selectedSignal) === 'converted' && (
              <div className={s.convertedState}>
                <span className={`${s.status} ${s.status_converted}`} title="已关联模拟订单">已转订单</span>
                <b>{selectedSignal.order_id ?? '—'}</b>
                <a className={s.textLink} href="/simulation">打开模拟交易</a>
                {relatedOrderLoading && <span className={s.convertedHint}>正在读取成交与账本结果…</span>}
                {relatedOrderError && <span className={s.convertedError}>{relatedOrderError}</span>}
                {relatedOrder && (
                  <>
                    <div className={s.orderProgress}>
                      <span><small>订单状态</small><b>{relatedOrder.status}</b></span>
                      <span><small>成交进度</small><b>{formatNumber(relatedOrder.filled_quantity, 8)} / {formatNumber(relatedOrder.quantity, 8)}</b></span>
                    </div>
                    <div className={s.executionList}>
                      {relatedOrder.executions.map((execution) => (
                        <div key={execution.id}>
                          <span>
                            <b>{formatNumber(execution.quantity, 8)} @ {formatNumber(execution.price, 4)}</b>
                            <small>{execution.ledger_sync_status}</small>
                          </span>
                          {execution.ledger_trade_id
                            ? <a className={s.textLink} href={`/ledger?tab=trades&trade_id=${encodeURIComponent(execution.ledger_trade_id)}`}>查看账本</a>
                            : <small>{execution.ledger_sync_error || '尚未生成账本成交'}</small>}
                        </div>
                      ))}
                      {!relatedOrder.executions.length && <span className={s.convertedHint}>订单尚无成交记录</span>}
                    </div>
                  </>
                )}
              </div>
            )}
            {selectedSignal?.id && signalStatus(selectedSignal) === 'accepted' && (
              <>
                <label className={s.quantityField}>
                  <span>订单数量</span>
                  <Input
                    type="number"
                    min={0.000001}
                    step={selectedSignal.market === 'a_shares' ? 100 : 0.01}
                    variant="mono"
                    value={orderQuantities[selectedSignal.id] ?? 100}
                    onChange={(event) => setOrderQuantities((quantities) => ({
                      ...quantities,
                      [selectedSignal.id!]: Math.max(0.000001, Number(event.target.value) || 0.000001),
                    }))}
                    aria-label={`${selectedSignal.symbol} 模拟订单数量`}
                  />
                </label>

                {previewLoading && <div className={s.inlineState}>正在计算账户影响…</div>}
                {previewError && <div className={s.inlineError}>{previewError}</div>}
                {preview && (
                  <>
                    <div className={s.impactGrid}>
                      <span><small>参考价格</small><b>{formatNumber(preview.price, 4)}</b></span>
                      <span><small>订单名义金额</small><b>{formatNumber(preview.order_notional)}</b></span>
                      <span><small>当前持仓</small><b>{formatNumber(preview.current_quantity, 8)}</b></span>
                      <span><small>预计持仓</small><b>{formatNumber(preview.projected_quantity, 8)}</b></span>
                      <span><small>当前总敞口</small><b>{formatNumber(preview.gross_exposure_before)}</b></span>
                      <span><small>预计总敞口</small><b>{formatNumber(preview.gross_exposure_after)}</b></span>
                      <span><small>当前现金</small><b>{formatNumber(preview.cash_before)}</b></span>
                      <span><small>预计现金</small><b>{formatNumber(preview.cash_after)}</b></span>
                    </div>
                    <div className={s.checkList}>
                      {preview.checks.map((check) => (
                        <div key={check.code} className={s[`check_${check.status}`]}>
                          <span className={s.checkMark}>{check.status === 'passed' ? '✓' : '!'}</span>
                          <span><b>{check.code}</b><small>{formatRiskValue(check.actual)} / {formatRiskValue(check.limit)} · {check.reevaluate_action}</small></span>
                        </div>
                      ))}
                    </div>
                    {!preview.risk_evaluated && <div className={s.executionWarning}>风控未完成，必须刷新数据并重新评估后才能创建订单。</div>}
                  </>
                )}

                <Button
                  variant="primary"
                  fullWidth
                  onClick={() => void handleConvert(selectedSignal)}
                  loading={actionId === `${selectedSignal.id}:converted`}
                  disabled={previewLoading || !preview || !preview.risk_evaluated || !preview.can_submit}
                >
                  转模拟订单
                </Button>
                {preview && !preview.can_submit && <div className={s.executionBlocked}>服务端已阻止创建：{preview.reason_codes.join('、') || '风险证据不完整'}。</div>}
              </>
            )}
          </aside>
        </div>

        {filtered.length > 0 && (
          <section className={s.analytics}>
            <div className={s.sectionHeading}><div><h2>队列分布</h2><span>基于当前筛选结果</span></div></div>
            <div className={s.analyticsGrid}>
              <DirectionDonut signals={filtered} />
              <ScoreHistogram signals={filtered} />
              <SourceBars signals={filtered} />
            </div>
          </section>
        )}
      </main>
    </>
  )
}

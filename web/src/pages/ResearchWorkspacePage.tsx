import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AnalysisTask, ResearchRun, ResearchStatus } from '../api/types'
import { useApi } from '../api/useApi'
import DecisionPanel from '../components/DecisionPanel'
import KlineCard from '../components/KlineCard'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { setRecentResearchPath } from '../navigation/recentResearch'
import { ContextBar } from '../components/ContextBar/ContextBar'
import { EvidenceRail } from '../components/EvidenceRail/EvidenceRail'
import { useRecordNavigation } from '../hooks/useRecordNavigation'
import { shouldAdoptEvaluationRun } from '../lib/researchRunNavigation'
import EnsemblePage from './EnsemblePage'
import NewsPage from './NewsPage'
import '../styles/research.css'

const VIEWS = [
  { key: 'overview', label: '概览' },
  { key: 'chart', label: '行情' },
  { key: 'news', label: '新闻证据' },
  { key: 'pa', label: '价格结构' },
  { key: 'ensemble', label: '模型共识' },
  { key: 'history', label: '评估记录' },
] as const
type View = (typeof VIEWS)[number]['key']

const TIMEFRAMES = ['1h', '1d', '1w'] as const
type WorkspaceTimeframe = (typeof TIMEFRAMES)[number]
type WorkspaceMarket = 'a_shares' | 'us_stocks' | 'crypto'

const MARKET_LABELS: Record<WorkspaceMarket, string> = {
  a_shares: 'A股',
  us_stocks: '美股',
  crypto: '虚拟货币',
}

const EVALUATION_STEP_LABELS: Record<string, string> = {
  prepare: '准备数据',
  market: '量化快照',
  news: '新闻 AI',
  pa: '价格结构 AI',
  ensemble: '模型共识',
  report: '生成报告',
}

function pollRunningTask(response: { ok: boolean; task: AnalysisTask }): boolean {
  return response.task.status === 'queued' || response.task.status === 'running'
}

const TIMEFRAME_LABELS: Record<WorkspaceTimeframe, string> = {
  '1h': '短线',
  '1d': '波段',
  '1w': '中线',
}

const MODULE_LABELS: Record<string, string> = {
  news: '新闻 AI',
  pa: '价格结构 AI',
  ensemble: '模型共识',
  market: '量化快照',
}

const EVALUATION_PROFILE_LABELS: Record<string, string> = {
  quick: '快速筛查',
  balanced: '均衡评估',
  comprehensive: '全面评估',
}

function formatModules(modules: string[]) {
  return modules.map((module) => MODULE_LABELS[module] ?? module).join(' + ')
}

const STATUS_META: Record<ResearchStatus, { label: string; cls: string }> = {
  draft: { label: '草稿', cls: 'draft' },
  queued: { label: '排队', cls: 'queued' },
  running: { label: '分析中', cls: 'running' },
  succeeded: { label: '已完成', cls: 'succeeded' },
  partial: { label: '部分完成', cls: 'partial' },
  failed: { label: '失败', cls: 'failed' },
  cancelled: { label: '已取消', cls: 'cancelled' },
  timeout: { label: '已超时', cls: 'timeout' },
}

function formatTime(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function buildReadableReport(run: ResearchRun) {
  const modelEvidence = run.evidence?.find((item) => item.kind === 'model_output')
  const ensembleEvidence = run.evidence?.find((item) => item.kind === 'ensemble_output')
  const modelPayload = asRecord(modelEvidence?.payload)
  const ensemblePayload = asRecord(ensembleEvidence?.payload)
  const stage2 = asRecord(modelPayload?.stage2)
  const decision = asRecord(stage2?.decision)
  const summary = asRecord(run.summary)
  const marketSummary = asRecord(summary?.market)
  const quantitative = asRecord(marketSummary?.quantitative)
  const quantitativeMetrics = asRecord(quantitative?.metrics)
  const dimensionMap = asRecord(quantitative?.dimensions)
  const quantitativeDimensions = Object.values(dimensionMap ?? {})
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => item !== null)
  const quantitativeStrategies = Array.isArray(quantitative?.strategies)
    ? quantitative.strategies.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : []
  const ensemble = asRecord(summary?.ensemble)
  const consensus = asRecord(ensemble?.consensus)
  const news = asRecord(summary?.news)
  const consensusDirection = consensus?.direction === 'buy'
    || consensus?.direction === 'sell'
    || consensus?.direction === 'hold'
    ? consensus.direction
    : null
  const orderDirection = decision?.order_direction === '做多'
    || decision?.order_direction === '做空'
    ? decision.order_direction
    : null
  const successfulModules = run.modules.filter((module) => {
    const moduleSummary = asRecord(summary?.[module])
    return moduleSummary !== null && moduleSummary.ok !== false
  })
  const contributors = Array.isArray(ensemblePayload?.contributors)
    ? ensemblePayload.contributors.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : []
  const availableContributors = contributors.filter((item) => item.available !== false)
  const contributorDirections = availableContributors
    .map((item) => item.direction)
    .filter((direction): direction is 'buy' | 'sell' | 'hold' => direction === 'buy' || direction === 'sell' || direction === 'hold')
  const directionSet = new Set(contributorDirections)
  const hasConflict = directionSet.size > 1
  const conclusion = successfulModules.length < 2 || (!consensusDirection && !orderDirection)
    ? '数据不足'
    : consensusDirection === 'buy' || (!consensusDirection && orderDirection === '做多')
      ? '偏强'
      : consensusDirection === 'sell' || (!consensusDirection && orderDirection === '做空')
        ? '偏弱'
        : '中性'
  const keyFactors = Array.isArray(decision?.key_factors)
    ? decision.key_factors.filter((item): item is string => typeof item === 'string').slice(0, 3)
    : []
  if (!keyFactors.length) {
    availableContributors.forEach((item) => {
      if (keyFactors.length >= 3 || typeof item.rationale !== 'string' || !item.rationale.trim()) return
      const name = typeof item.name === 'string' ? item.name : '模型'
      keyFactors.push(`${name}：${item.rationale}`)
    })
  }
  if (keyFactors.length < 3) {
    quantitativeDimensions.forEach((item) => {
      if (keyFactors.length >= 3 || typeof item.evidence !== 'string' || !item.evidence.trim()) return
      keyFactors.push(`${typeof item.label === 'string' ? item.label : '量化维度'}：${item.evidence}`)
    })
  }
  const watchPoints = Array.isArray(decision?.watch_points)
    ? decision.watch_points.filter((item): item is string => typeof item === 'string').slice(0, 3)
    : []
  const sourceDetails = Array.from(new Set((run.evidence ?? []).map((item) => item.source).filter(Boolean)))
  const disagreements = hasConflict
    ? availableContributors
      .filter((item) => item.direction === 'buy' || item.direction === 'sell' || item.direction === 'hold')
      .map((item) => `${typeof item.name === 'string' ? item.name : '模型'}：${item.direction}`)
    : []

  return {
    conclusion,
    headline: conclusion === '数据不足'
      ? '当前成功模块不足，不能形成完整结论。'
      : hasConflict
        ? '可用模块方向存在分歧，需要等待新的确认依据。'
        : `可用模块当前共同指向${conclusion}。`,
    explanation: hasConflict
      ? `分歧来源：${disagreements.join('；')}`
      : `本结论仅使用已成功完成的模块：${successfulModules.map((module) => MODULE_LABELS[module] ?? module).join('、') || '无'}。`,
    newsStatus: asNumber(news?.total) === 0 ? '暂无有效新闻' : news ? '已纳入新闻' : '新闻未纳入',
    latestPrice: asNumber(marketSummary?.latest_price),
    latestTime: marketSummary?.latest_time,
    marketSource: typeof marketSummary?.source === 'string' ? marketSummary.source : null,
    entry: asNumber(decision?.entry_price),
    invalidation: asNumber(decision?.stop_loss_price),
    target: asNumber(decision?.take_profit_price),
    keyFactors,
    watchPoints,
    disagreements,
    sourceDetails,
    risk: String(decision?.risk_assessment ?? '模型结果仅用于研究，不构成交易建议。'),
    evaluationProfile: typeof run.input.evaluation_profile === 'string'
      ? EVALUATION_PROFILE_LABELS[run.input.evaluation_profile] ?? run.input.evaluation_profile
      : null,
    quantitativeConfidence: typeof quantitative?.confidence === 'string' ? quantitative.confidence : null,
    quantitativeDataQuality: typeof quantitative?.data_quality === 'string' ? quantitative.data_quality : null,
    quantitativeMetrics: {
      return20: asNumber(quantitativeMetrics?.return_20_pct),
      volatility: asNumber(quantitativeMetrics?.annualized_volatility_pct),
      drawdown: asNumber(quantitativeMetrics?.max_drawdown_pct),
      rsi: asNumber(quantitativeMetrics?.rsi_14),
    },
    quantitativeDimensions,
    quantitativeStrategies,
    quantitativeDisagreement: quantitative?.has_strategy_disagreement === true,
  }
}

type ReadableReport = ReturnType<typeof buildReadableReport>

function createReadableReportHtml(run: ResearchRun, report: ReadableReport, instrumentName: string) {
  const documentCopy = document.implementation.createHTMLDocument(`${instrumentName || run.symbol} 评估报告`)
  documentCopy.documentElement.lang = 'zh-CN'
  const style = documentCopy.createElement('style')
  style.textContent = 'body{max-width:820px;margin:40px auto;padding:0 24px;color:#172033;font:15px/1.7 system-ui,sans-serif}h1{font-size:28px}h2{margin-top:28px;font-size:18px}dl{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}dt{color:#687386}dd{margin:0;font-weight:700}section{border-top:1px solid #d9dee8;margin-top:24px;padding-top:8px}small{color:#687386}footer{margin-top:36px;padding-top:16px;border-top:1px solid #d9dee8;color:#687386}@media print{body{margin:0;max-width:none}}'
  documentCopy.head.appendChild(style)
  const appendText = (parent: HTMLElement, tag: string, text: string) => {
    const node = documentCopy.createElement(tag)
    node.textContent = text
    parent.appendChild(node)
    return node
  }
  appendText(documentCopy.body, 'h1', `${instrumentName ? `${instrumentName} ` : ''}${run.symbol} 评估报告`)
  appendText(documentCopy.body, 'small', `${run.market} · ${run.timeframe} · ${formatTime(run.updated_at)} · ${run.id}`)
  appendText(documentCopy.body, 'h2', `结论：${report.conclusion}`)
  appendText(documentCopy.body, 'p', report.headline)
  appendText(documentCopy.body, 'p', report.explanation)
  const facts = documentCopy.createElement('dl')
  ;[
    ['最新价格', report.latestPrice?.toLocaleString('zh-CN') ?? '数据不足'],
    ['价格时间', typeof report.latestTime === 'string' ? report.latestTime : '数据不足'],
    ['行情来源', report.marketSource ?? '数据不足'],
    ['适用周期', TIMEFRAME_LABELS[run.timeframe as WorkspaceTimeframe] ?? run.timeframe],
  ].forEach(([label, value]) => {
    const wrapper = documentCopy.createElement('div')
    appendText(wrapper, 'dt', label)
    appendText(wrapper, 'dd', value)
    facts.appendChild(wrapper)
  })
  documentCopy.body.appendChild(facts)
  const evidenceSection = documentCopy.createElement('section')
  appendText(evidenceSection, 'h2', '主要依据')
  const evidenceList = documentCopy.createElement('ul')
  ;(report.keyFactors.length ? report.keyFactors : ['当前运行没有可展示的主要依据']).forEach((item) => appendText(evidenceList, 'li', item))
  evidenceSection.appendChild(evidenceList)
  documentCopy.body.appendChild(evidenceSection)
  const watchSection = documentCopy.createElement('section')
  appendText(watchSection, 'h2', '风险、失效条件与观察项')
  appendText(watchSection, 'p', `主要风险：${report.risk}`)
  appendText(watchSection, 'p', `失效条件：${report.invalidation?.toLocaleString('zh-CN') ?? '数据不足'}`)
  const watchList = documentCopy.createElement('ul')
  ;(report.watchPoints.length ? report.watchPoints : ['等待下一次有效数据更新后重新评估']).forEach((item) => appendText(watchList, 'li', item))
  watchSection.appendChild(watchList)
  documentCopy.body.appendChild(watchSection)
  appendText(documentCopy.body, 'footer', '辅助研究，不构成投资建议。')
  return `<!doctype html>${documentCopy.documentElement.outerHTML}`
}

function ResearchHistory({
  runs,
  activeRunId,
  loading,
  error,
  reconnecting,
  hasData,
  onRetry,
  onSelect,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
}: {
  runs: ResearchRun[]
  activeRunId: string | null
  loading: boolean
  error: string | null
  reconnecting: boolean
  hasData: boolean
  onRetry: () => void
  onSelect: (runId: string) => void
  total: number
  hasMore: boolean
  loadingMore: boolean
  onLoadMore: () => void
}) {
  const handleKeyDown = useRecordNavigation({
    keys: runs.map((run) => run.id),
    activeKey: activeRunId,
    onSelect,
  })
  return (
    <AsyncStateBoundary
      loading={loading}
      error={error}
      reconnecting={reconnecting}
      hasData={hasData}
      isEmpty={runs.length === 0}
      onRetry={onRetry}
      loadingTitle="正在读取评估记录…"
      emptyTitle="还没有评估记录"
      emptyDescription="完成新闻 AI、价格结构 AI 或模型共识后，分析依据会出现在这里。"
    >
      <div className="research-run-list" tabIndex={0} onKeyDown={handleKeyDown} aria-label="可用方向键选择评估记录">
        {runs.map((run) => {
          const meta = STATUS_META[run.status]
          return (
            <button
              type="button"
              className={`research-run-row ${run.id === activeRunId ? 'active' : ''}`}
              key={run.id}
              onClick={() => onSelect(run.id)}
            >
              <span className={`research-status ${meta.cls}`}>{meta.label}</span>
              <span className="research-run-main">
                <b>{run.modules.length ? formatModules(run.modules) : '尚未分析'}</b>
                <small>{formatTime(run.updated_at)} · {TIMEFRAME_LABELS[run.timeframe as WorkspaceTimeframe] ?? run.timeframe}{run.note ? ` · ${run.note}` : ''}</small>
              </span>
              <span className={`research-favorite-mark ${run.favorite ? 'active' : ''}`} title={run.favorite ? '已收藏' : '未收藏'}>
                {run.favorite ? '★' : '☆'}
              </span>
              <span className="research-evidence-count mono-num">{run.evidence_count} 条依据</span>
            </button>
          )
        })}
        {hasMore && (
          <button type="button" className="research-load-more" disabled={loadingMore} onClick={onLoadMore}>
            {loadingMore ? '加载中…' : `继续加载 · 已显示 ${runs.length} / ${total}`}
          </button>
        )}
      </div>
    </AsyncStateBoundary>
  )
}

export default function ResearchWorkspacePage() {
  const params = useParams<{ symbol: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const symbol = (params.symbol || '600519').trim().toUpperCase()
  const market = (searchParams.get('market') || 'a_shares') as WorkspaceMarket
  const timeframe = (searchParams.get('tf') || '1d') as WorkspaceTimeframe
  const requestedRunId = searchParams.get('run_id') || ''
  const requestedCompareRunId = searchParams.get('compare_run_id') || ''
  const requestedFavoritesOnly = searchParams.get('favorite') === 'true'
  const evaluationTaskId = searchParams.get('evaluation_task_id') || ''
  const rawView = searchParams.get('view') || 'overview'
  const view: View = VIEWS.some((item) => item.key === rawView) ? rawView as View : 'overview'

  const [symbolInput, setSymbolInput] = useState(symbol)
  const [activeRunId, setActiveRunId] = useState<string | null>(requestedRunId || null)
  const [compareRunId, setCompareRunId] = useState(requestedCompareRunId)
  const [favoritesOnly, setFavoritesOnly] = useState(requestedFavoritesOnly)
  const [historyKey, setHistoryKey] = useState(0)
  const [noteDraft, setNoteDraft] = useState('')
  const [metadataSaving, setMetadataSaving] = useState(false)
  const [metadataMessage, setMetadataMessage] = useState('')
  const [historyLoadingMore, setHistoryLoadingMore] = useState(false)
  const [reportActionMessage, setReportActionMessage] = useState('')
  const history = useApi(
    () => api.researchRuns(symbol, undefined, 50, favoritesOnly || undefined),
    [symbol, favoritesOnly, historyKey],
    { retryInterval: 15000, resetKey: `${symbol}|${favoritesOnly}` },
  )
  const instrumentDirectory = useApi(
    () => api.instruments(symbol, 20),
    [symbol, market],
    { retry: false, resetKey: `${symbol}|${market}` },
  )
  const evaluationTask = useApi(
    () => api.analysisTask(evaluationTaskId),
    [evaluationTaskId],
    {
      enabled: Boolean(evaluationTaskId),
      retry: false,
      pollInterval: 750,
      pollWhile: pollRunningTask,
      resetKey: evaluationTaskId,
    },
  )
  const evaluation = evaluationTask.data?.task ?? null
  const evaluationResult = evaluation?.result ?? {}
  const evaluationRunId = typeof evaluationResult.research_run_id === 'string'
    ? evaluationResult.research_run_id
    : ''
  const evaluationSteps = (
    evaluationResult.steps && typeof evaluationResult.steps === 'object'
      ? evaluationResult.steps
      : {}
  ) as Record<string, { status?: string; error?: string | null }>
  const runs = history.data?.runs ?? []
  const instrument = instrumentDirectory.data?.instruments.find(
    (item) => item.code === symbol && item.market === market,
  ) ?? null

  async function loadMoreHistory() {
    const cursor = history.data?.next_cursor
    if (!cursor || historyLoadingMore) return
    setHistoryLoadingMore(true)
    try {
      const next = await api.researchRuns(symbol, undefined, 50, favoritesOnly || undefined, cursor)
      history.setData((previous) => {
        const existing = new Set(previous.runs.map((item) => item.id))
        return {
          ...next,
          count: previous.count + next.count,
          runs: [...previous.runs, ...next.runs.filter((item) => !existing.has(item.id))],
        }
      })
    } finally {
      setHistoryLoadingMore(false)
    }
  }
  const activeRun = useMemo(
    () => runs.find((run) => run.id === activeRunId) ?? null,
    [activeRunId, runs],
  )
  const runDetail = useApi(
    () => api.researchRun(activeRunId || ''),
    [activeRunId],
    { enabled: Boolean(activeRunId), retry: false, resetKey: activeRunId },
  )
  const detailedRun = runDetail.data?.run ?? activeRun
  const readableReport = useMemo(
    () => detailedRun ? buildReadableReport(detailedRun) : null,
    [detailedRun],
  )
  const verification = useApi(
    () => api.researchVerify(activeRunId || ''),
    [activeRunId],
    { enabled: Boolean(activeRunId), retry: false, resetKey: activeRunId },
  )
  const comparison = useApi(
    () => api.compareResearchRuns([activeRunId || '', compareRunId]),
    [activeRunId, compareRunId],
    {
      enabled: Boolean(activeRunId && compareRunId && activeRunId !== compareRunId),
      retry: false,
      resetKey: `${activeRunId}|${compareRunId}`,
    },
  )

  async function exportResearch(runId: string) {
    const exported = await api.researchExport(runId)
    const body = JSON.stringify(exported, null, 2)
    const blob = new Blob([body], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `quanthub-research-${runId.slice(0, 12)}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function exportReadableHtml(run: ResearchRun, report: ReadableReport) {
    const html = createReadableReportHtml(run, report, instrument?.name ?? '')
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `quanthub-report-${run.symbol}-${run.id.slice(0, 12)}.html`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function printReadableReport(run: ResearchRun, report: ReadableReport) {
    const html = createReadableReportHtml(run, report, instrument?.name ?? '')
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
    const printWindow = window.open(url, '_blank')
    if (!printWindow) {
      URL.revokeObjectURL(url)
      setReportActionMessage('浏览器阻止了打印窗口，请允许当前站点打开新窗口')
      return
    }
    printWindow.addEventListener('load', () => {
      printWindow.print()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    }, { once: true })
  }

  async function addCurrentInstrumentToWatchlist() {
    setReportActionMessage('')
    try {
      await api.addWatch({ sym: symbol, name: instrument?.name ?? '', market })
      setReportActionMessage('已加入自选')
    } catch (error) {
      setReportActionMessage(error instanceof Error ? error.message : '加入自选失败')
    }
  }

  async function updateMetadata(patch: { note?: string; favorite?: boolean }) {
    if (!detailedRun) return
    setMetadataSaving(true)
    setMetadataMessage('')
    try {
      const response = await api.updateResearchRun(detailedRun.id, patch)
      runDetail.setData(response)
      history.setData((previous) => ({
        ...previous,
        runs: previous.runs.map((run) => run.id === response.run.id ? response.run : run),
      }))
      setMetadataMessage('已保存')
      runDetail.refetch()
      history.refetch()
    } catch (error) {
      setMetadataMessage(error instanceof Error ? error.message : '保存失败')
    } finally {
      setMetadataSaving(false)
    }
  }

  useEffect(() => {
    setSymbolInput(symbol)
    setActiveRunId(requestedRunId || null)
    setCompareRunId(requestedCompareRunId)
    setFavoritesOnly(requestedFavoritesOnly)
  }, [market, requestedCompareRunId, requestedFavoritesOnly, requestedRunId, symbol, timeframe])

  useEffect(() => {
    setRecentResearchPath(`/research/${encodeURIComponent(symbol)}?${searchParams.toString()}`)
  }, [searchParams, symbol])

  useEffect(() => {
    if (!shouldAdoptEvaluationRun(requestedRunId, evaluationRunId)) return
    const query = new URLSearchParams(searchParams)
    query.set('run_id', evaluationRunId)
    if (evaluation && !['queued', 'running'].includes(evaluation.status)) query.set('view', 'history')
    setActiveRunId(evaluationRunId)
    setHistoryKey((key) => key + 1)
    setSearchParams(query, { replace: true })
  }, [evaluation, evaluationRunId, requestedRunId, searchParams, setSearchParams])

  async function cancelEvaluation() {
    if (!evaluation) return
    const response = await api.cancelAnalysisTask(evaluation.id)
    evaluationTask.setData(response)
  }

  async function retryEvaluation() {
    if (!evaluation) return
    const response = await api.retryAnalysisTask(evaluation.id)
    const query = new URLSearchParams(searchParams)
    query.set('evaluation_task_id', response.task.id)
    query.delete('run_id')
    setSearchParams(query, { replace: true })
  }

  useEffect(() => {
    setNoteDraft(detailedRun?.note ?? '')
    setMetadataMessage('')
  }, [detailedRun?.id, detailedRun?.note])

  const selectResearchRun = useCallback((runId: string) => {
    setActiveRunId(runId)
    const query = new URLSearchParams(searchParams)
    query.set('run_id', runId)
    query.delete('evaluation_task_id')
    setSearchParams(query, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (searchParams.get('from') !== 'example' || requestedRunId || activeRunId || !history.data) return
    const exampleRun = runs.find((run) => run.input.example === true && run.status === 'succeeded')
      ?? runs.find((run) => run.favorite && run.status === 'succeeded')
      ?? runs.find((run) => run.status === 'succeeded')
    if (!exampleRun) return
    const query = new URLSearchParams(searchParams)
    query.set('run_id', exampleRun.id)
    query.set('view', 'history')
    setActiveRunId(exampleRun.id)
    setSearchParams(query, { replace: true })
  }, [activeRunId, history.data, requestedRunId, runs, searchParams, setSearchParams])

  const handleResearchRun = useCallback((runId: string) => {
    selectResearchRun(runId)
    setHistoryKey((key) => key + 1)
  }, [selectResearchRun])

  function updateContext(next: { symbol?: string; market?: WorkspaceMarket; timeframe?: WorkspaceTimeframe }) {
    const nextSymbol = (next.symbol ?? symbol).trim().toUpperCase()
    if (!nextSymbol) return
    const nextMarket = next.market ?? market
    const nextTimeframe = next.timeframe ?? timeframe
    const query = new URLSearchParams(searchParams)
    query.set('market', nextMarket)
    query.set('tf', nextTimeframe)
    if (nextSymbol !== symbol || nextMarket !== market || nextTimeframe !== timeframe) {
      query.delete('run_id')
      query.delete('compare_run_id')
    }
    navigate(`/research/${encodeURIComponent(nextSymbol)}?${query.toString()}`)
  }

  function setView(next: View) {
    const query = new URLSearchParams(searchParams)
    query.set('view', next)
    setSearchParams(query)
  }

  function setFavoriteFilter(nextValue: boolean) {
    setFavoritesOnly(nextValue)
    const query = new URLSearchParams(searchParams)
    if (nextValue) query.set('favorite', 'true')
    else query.delete('favorite')
    setSearchParams(query, { replace: true })
  }

  function setCompareRun(nextRunId: string) {
    setCompareRunId(nextRunId)
    const query = new URLSearchParams(searchParams)
    if (nextRunId) query.set('compare_run_id', nextRunId)
    else query.delete('compare_run_id')
    setSearchParams(query, { replace: true })
  }

  return (
    <div className="research-page">
      <WorkspaceHeader
        context="研究 / 综合评估"
        title={symbol}
        metrics={[
          { label: '市场', value: MARKET_LABELS[market] ?? market },
          { label: '关注周期', value: TIMEFRAME_LABELS[timeframe] },
          { label: '分析依据', value: activeRun ? `${activeRun.evidence_count} 条` : '等待首次分析' },
        ]}
      />
      {evaluationTaskId && (
        <section className="evaluation-progress" aria-label="综合评估进度">
          <div className="evaluation-progress-head">
            <div>
              <span>统一标的评估</span>
              <strong>{evaluation ? STATUS_META[evaluation.status === 'succeeded' && evaluationResult.partial === true ? 'partial' : evaluation.status as ResearchStatus]?.label ?? evaluation.status : '正在读取任务'}</strong>
            </div>
            <div className="evaluation-progress-actions">
              {evaluation && ['queued', 'running'].includes(evaluation.status) && (
                <button type="button" onClick={() => void cancelEvaluation()}>取消评估</button>
              )}
              {evaluation && ['failed', 'cancelled', 'timeout'].includes(evaluation.status) && (
                <button type="button" onClick={() => void retryEvaluation()}>重新评估</button>
              )}
            </div>
          </div>
          <div className="evaluation-progress-steps">
            {Object.entries(EVALUATION_STEP_LABELS).map(([key, label]) => {
              const derived = key === 'prepare'
                ? (evaluationRunId ? 'succeeded' : evaluation?.status === 'failed' ? 'failed' : 'running')
                : key === 'report'
                  ? evaluation?.status === 'succeeded' ? 'succeeded' : evaluation?.status === 'failed' ? 'failed' : 'pending'
                  : evaluationSteps[key]?.status ?? 'pending'
              return (
                <div className={`evaluation-step ${derived}`} key={key} title={evaluationSteps[key]?.error ?? undefined}>
                  <span aria-hidden="true" />
                  <b>{label}</b>
                  <small>{derived === 'succeeded' ? '完成' : derived === 'failed' ? '失败' : derived === 'running' ? '进行中' : '等待'}</small>
                </div>
              )
            })}
          </div>
          {(evaluation?.error || evaluationTask.error) && (
            <div className="evaluation-progress-error" role="alert">{evaluation?.error || evaluationTask.error}</div>
          )}
        </section>
      )}
      <ContextBar items={[
        { label: '标的代码', value: symbol, mono: true },
        { label: '市场', value: MARKET_LABELS[market] ?? market },
        { label: '关注周期', value: TIMEFRAME_LABELS[timeframe] },
        { label: '评估状态', value: activeRun ? STATUS_META[activeRun.status].label : '未开始' },
        { label: '更新时间', value: activeRun ? formatTime(activeRun.updated_at) : '—', mono: true },
      ]}>
        <form
          className="research-context-controls"
          onSubmit={(event) => {
            event.preventDefault()
            updateContext({ symbol: symbolInput })
          }}
        >
          <label>
            <span>标的代码</span>
            <input
              value={symbolInput}
              onChange={(event) => setSymbolInput(event.target.value)}
              placeholder="600519"
              aria-label="标的代码"
            />
          </label>
          <label>
            <span>市场</span>
            <select
              value={market}
              onChange={(event) => updateContext({ market: event.target.value as WorkspaceMarket })}
              aria-label="标的市场"
            >
              <option value="a_shares">A股</option>
              <option value="us_stocks">美股</option>
              <option value="crypto">虚拟货币</option>
            </select>
          </label>
          <div className="research-timeframes" role="group" aria-label="关注周期">
            {TIMEFRAMES.map((item) => (
              <button
                type="button"
                key={item}
                className={item === timeframe ? 'active' : ''}
                onClick={() => updateContext({ timeframe: item })}
              >
                {TIMEFRAME_LABELS[item]}
              </button>
            ))}
          </div>
          <button className="research-go" type="submit">切换</button>
        </form>
      </ContextBar>

      <nav className="research-tabs" aria-label="综合评估视图">
        {VIEWS.map((item) => (
          <button
            type="button"
            key={item.key}
            className={view === item.key ? 'active' : ''}
            onClick={() => setView(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="research-workspace-grid">
      <section className="research-view" key={`${symbol}-${market}-${timeframe}-${view}`}>
        {view === 'overview' && (
          <div className="research-overview-grid">
            <KlineCard
              symbol={symbol}
              market={market}
              onSymbolChange={(next) => updateContext({ symbol: next })}
              onMarketChange={(next) => updateContext({ market: next })}
            />
            <aside className="research-history-panel">
                    <div className="research-section-head">
                <div>
                  <span>评估记录</span>
                  <h2>最近评估</h2>
                </div>
                <RefreshControl onRefresh={history.refetch} refreshing={history.loading || history.reconnecting} updatedAt={history.updatedAt} />
              </div>
              <ResearchHistory
                runs={runs.slice(0, 6)}
                activeRunId={activeRunId}
                loading={history.loading}
                error={history.error}
                reconnecting={history.reconnecting}
                hasData={history.data !== null}
                onRetry={history.refetch}
                onSelect={selectResearchRun}
                total={history.data?.total ?? runs.length}
                hasMore={Boolean(history.data?.next_cursor)}
                loadingMore={historyLoadingMore}
                onLoadMore={() => void loadMoreHistory()}
              />
            </aside>
          </div>
        )}
        {view === 'chart' && (
          <KlineCard
            symbol={symbol}
            market={market}
            onSymbolChange={(next) => updateContext({ symbol: next })}
            onMarketChange={(next) => updateContext({ market: next })}
          />
        )}
        {view === 'news' && (
          <NewsPage
            initialSymbol={symbol}
            market={market}
            timeframe={timeframe}
            researchRunId={activeRunId}
            onResearchRunId={handleResearchRun}
            embedded
          />
        )}
        {view === 'pa' && (
          <DecisionPanel
            symbol={symbol}
            market={market}
            timeframe={timeframe}
            researchRunId={activeRunId}
            onResearchRunId={handleResearchRun}
          />
        )}
        {view === 'ensemble' && (
          <EnsemblePage
            initialSymbol={symbol}
            initialMarket={market}
            initialTimeframe={timeframe}
            researchRunId={activeRunId}
            onResearchRunId={handleResearchRun}
            embedded
          />
        )}
        {view === 'history' && (
          <div className="research-history-panel full">
            <div className="research-section-head">
              <div>
                <span>历史记录</span>
                <h2>{symbol} 评估记录</h2>
              </div>
              <div className="research-head-actions">
                <button
                  type="button"
                  className={favoritesOnly ? 'active' : ''}
                  onClick={() => setFavoriteFilter(!favoritesOnly)}
                  aria-pressed={favoritesOnly}
                >
                  ★ 收藏
                </button>
                <RefreshControl onRefresh={history.refetch} refreshing={history.loading || history.reconnecting} updatedAt={history.updatedAt} />
              </div>
            </div>
            <ResearchHistory
              runs={runs}
              activeRunId={activeRunId}
              loading={history.loading}
              error={history.error}
              reconnecting={history.reconnecting}
              hasData={history.data !== null}
              onRetry={history.refetch}
              onSelect={selectResearchRun}
              total={history.data?.total ?? runs.length}
              hasMore={Boolean(history.data?.next_cursor)}
              loadingMore={historyLoadingMore}
              onLoadMore={() => void loadMoreHistory()}
            />
            {detailedRun && (
              <>
                {readableReport && (
                  <section className="research-report-summary" aria-labelledby="research-report-title">
                    <header className="research-report-lead">
                      <div>
                        <span>{detailedRun.input.example === true ? '示例报告 · 仅供学习' : '综合评估结论'}</span>
                        <h2 id="research-report-title">{instrument?.name ? `${instrument.name} ${detailedRun.symbol}` : detailedRun.symbol} · {readableReport.conclusion}</h2>
                        <p>{readableReport.headline}</p>
                      </div>
                      <div className="research-report-verdict">
                        <b>{readableReport.conclusion}</b>
                        <span>{TIMEFRAME_LABELS[detailedRun.timeframe as WorkspaceTimeframe] ?? detailedRun.timeframe}</span>
                      </div>
                    </header>
                    <p className="research-report-explanation">{readableReport.explanation}</p>
                    <dl className="research-report-metrics">
                      <div><dt>最新价格</dt><dd>{readableReport.latestPrice?.toLocaleString('zh-CN') ?? '数据不足'}</dd></div>
                      <div><dt>价格时间</dt><dd>{typeof readableReport.latestTime === 'string' ? readableReport.latestTime : '数据不足'}</dd></div>
                      <div><dt>行情来源</dt><dd>{readableReport.marketSource ?? '数据不足'}</dd></div>
                      <div><dt>新闻覆盖</dt><dd>{readableReport.newsStatus}</dd></div>
                    </dl>
                    {readableReport.quantitativeDimensions.length > 0 && (
                      <section className="research-quantitative" aria-labelledby="research-quantitative-title">
                        <header>
                          <div>
                            <span>可解释量化评估</span>
                            <h3 id="research-quantitative-title">{readableReport.evaluationProfile ?? '自定义评估'}</h3>
                          </div>
                          <p>数据质量 {readableReport.quantitativeDataQuality ?? '未知'} · 置信度 {readableReport.quantitativeConfidence ?? '未知'}</p>
                        </header>
                        <div className="research-quantitative-metrics">
                          <span><small>20 期收益</small><b>{readableReport.quantitativeMetrics.return20 === null ? '—' : `${readableReport.quantitativeMetrics.return20 > 0 ? '+' : ''}${readableReport.quantitativeMetrics.return20.toFixed(2)}%`}</b></span>
                          <span><small>年化波动</small><b>{readableReport.quantitativeMetrics.volatility === null ? '—' : `${readableReport.quantitativeMetrics.volatility.toFixed(2)}%`}</b></span>
                          <span><small>最大回撤</small><b>{readableReport.quantitativeMetrics.drawdown === null ? '—' : `${readableReport.quantitativeMetrics.drawdown.toFixed(2)}%`}</b></span>
                          <span><small>RSI(14)</small><b>{readableReport.quantitativeMetrics.rsi?.toFixed(1) ?? '—'}</b></span>
                        </div>
                        <div className="research-dimension-grid">
                          {readableReport.quantitativeDimensions.map((dimension, index) => (
                            <div key={`${String(dimension.label)}-${index}`}>
                              <span>{String(dimension.label ?? '量化维度')}</span>
                              <b>{String(dimension.signal ?? '数据不足')}</b>
                              <small>{String(dimension.evidence ?? '暂无可用证据')}</small>
                            </div>
                          ))}
                        </div>
                        {readableReport.quantitativeStrategies.length > 0 && (
                          <div className="research-strategy-views">
                            {readableReport.quantitativeStrategies.map((strategy, index) => (
                              <div key={`${String(strategy.key)}-${index}`}>
                                <span>{String(strategy.label ?? '策略视角')}</span>
                                <b>{String(strategy.stance ?? '数据不足')}</b>
                                <small>{String(strategy.rationale ?? '暂无判断依据')} · 置信度 {String(strategy.confidence ?? '未知')}</small>
                              </div>
                            ))}
                          </div>
                        )}
                        {readableReport.quantitativeDisagreement && <p className="research-strategy-disagreement">不同策略视角给出了不同约束，这是需要保留的判断分歧。</p>}
                      </section>
                    )}
                    <div className="research-report-levels" aria-label="模型关键价位">
                      <div><span>模型观察位</span><b>{readableReport.entry?.toLocaleString('zh-CN') ?? '—'}</b><small>不是买入价</small></div>
                      <div><span>判断失效位</span><b>{readableReport.invalidation?.toLocaleString('zh-CN') ?? '—'}</b><small>突破后重新评估</small></div>
                      <div><span>下方参考位</span><b>{readableReport.target?.toLocaleString('zh-CN') ?? '—'}</b><small>关注支撑反应</small></div>
                    </div>
                    <div className="research-report-reasons">
                      <div>
                        <h3>为什么这样判断</h3>
                        <ul>{(readableReport.keyFactors.length ? readableReport.keyFactors : ['当前运行没有可展示的主要依据']).map((item) => (
                          <li key={item}>
                            <details>
                              <summary>{item}</summary>
                              <div className="research-report-source-list">
                                {(detailedRun.evidence ?? []).map((evidence) => (
                                  <div key={evidence.id}>
                                    <b>{evidence.title || evidence.kind}</b>
                                    <span>{evidence.source} · {formatTime(evidence.captured_at)}{typeof evidence.payload.model === 'string' ? ` · ${evidence.payload.model}` : ''}</span>
                                    <pre>{JSON.stringify(evidence.payload, null, 2)}</pre>
                                  </div>
                                ))}
                                {!detailedRun.evidence?.length && <span>当前运行没有可展开的原始依据</span>}
                              </div>
                            </details>
                          </li>
                        ))}</ul>
                      </div>
                      <div>
                        <h3>接下来观察什么</h3>
                        <ul>{(readableReport.watchPoints.length ? readableReport.watchPoints : ['等待下一次有效数据更新后重新评估']).map((item) => <li key={item}>{item}</li>)}</ul>
                      </div>
                    </div>
                    {readableReport.disagreements.length > 0 && <p className="research-report-risk"><b>模块分歧</b>{readableReport.disagreements.join('；')}</p>}
                    <p className="research-report-risk"><b>主要风险</b>{readableReport.risk}</p>
                    <div className="research-report-actions">
                      <button type="button" onClick={() => void addCurrentInstrumentToWatchlist()}>加入自选</button>
                      <button type="button" onClick={() => navigate(`/alerts?action=create&symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}`)}>设置提醒</button>
                      <button type="button" onClick={() => navigate(`/simulation?symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}`)}>进入模拟交易</button>
                      <button type="button" onClick={() => exportReadableHtml(detailedRun, readableReport)}>导出 HTML</button>
                      <button type="button" onClick={() => printReadableReport(detailedRun, readableReport)}>打印 / PDF</button>
                      {reportActionMessage && <span role="status">{reportActionMessage}</span>}
                    </div>
                    <p className="research-report-disclaimer">辅助研究，不构成投资建议。</p>
                  </section>
                )}
                <div className="research-run-detail">
                  <span>运行 ID <b className="mono-num">{detailedRun.id}</b></span>
                  <span>分析内容 <b>{formatModules(detailedRun.modules) || '—'}</b></span>
                  <span>状态 <b>{STATUS_META[detailedRun.status].label}</b></span>
                  <span>
                    快照完整性{' '}
                    <b className={verification.data?.snapshots_valid ? 'integrity-ok' : 'integrity-warn'}>
                      {verification.loading
                        ? '校验中'
                        : verification.data?.snapshots_valid
                          ? '已验证'
                          : '无有效快照'}
                    </b>
                  </span>
                  {detailedRun.error && <span className="error">错误 <b>{detailedRun.error}</b></span>}
                  <button
                    type="button"
                    className={`research-favorite-action ${detailedRun.favorite ? 'active' : ''}`}
                    onClick={() => void updateMetadata({ favorite: !detailedRun.favorite })}
                    disabled={metadataSaving}
                    title={detailedRun.favorite ? '取消收藏' : '收藏评估'}
                  >
                    {detailedRun.favorite ? '★ 已收藏' : '☆ 收藏'}
                  </button>
                  <label className="research-compare-picker">
                    <span>对比</span>
                    <select
                      value={compareRunId}
                      onChange={(event) => setCompareRun(event.target.value)}
                      aria-label="选择对比评估记录"
                    >
                      <option value="">选择另一条运行</option>
                      {runs.filter((run) => run.id !== detailedRun.id).map((run) => (
                        <option value={run.id} key={run.id}>
                          {formatTime(run.updated_at)} · {formatModules(run.modules) || '尚未分析'}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="research-note-editor">
                  <label htmlFor="research-note">评估备注</label>
                  <textarea
                    id="research-note"
                    value={noteDraft}
                    maxLength={4000}
                    rows={3}
                    placeholder="记录关键假设、待验证事项或后续行动"
                    onChange={(event) => setNoteDraft(event.target.value)}
                  />
                  <div className="research-note-actions">
                    <span className={metadataMessage === '已保存' ? 'ok' : ''}>{metadataMessage}</span>
                    <span className="mono-num">{noteDraft.length}/4000</span>
                    <button
                      type="button"
                      onClick={() => void updateMetadata({ note: noteDraft.trim() })}
                      disabled={metadataSaving || noteDraft.trim() === detailedRun.note}
                    >
                      {metadataSaving ? '保存中' : '保存备注'}
                    </button>
                  </div>
                </div>
                {comparison.data && (
                  <div className="research-comparison">
                    <div className="research-comparison-head">
                      <b>运行对比</b>
                      <span>{comparison.data.same_context ? '股票与周期相同' : '股票或周期不同，不建议直接比较'}</span>
                    </div>
                    <div className="research-comparison-grid">
                      {comparison.data.rows.map((row, index) => (
                        <div className="research-comparison-col" key={row.id}>
                          <span>{index === 0 ? '当前运行' : '对比运行'}</span>
                          <b className="mono-num">{row.id.slice(0, 12)}</b>
                          <small>分析内容：{formatModules(row.modules) || '—'}</small>
                          <small>依据：{row.evidence_count} 条 · 摘要：{Object.keys(row.summary).map((key) => MODULE_LABELS[key] ?? key).join(' / ') || '—'}</small>
                          <small>行情哈希：{row.snapshot_sha256[0]?.slice(0, 12) || '无快照'}</small>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div className="research-evidence-ledger">
                  <div className="research-section-head">
                    <div>
                      <span>专业详情</span>
                      <h2>分析依据与版本</h2>
                    </div>
                    <div className="research-evidence-actions">
                      <b className="mono-num">{detailedRun.evidence_count}</b>
                      <button type="button" onClick={() => void exportResearch(detailedRun.id)}>
                        导出 JSON
                      </button>
                    </div>
                  </div>
                  {runDetail.loading && !detailedRun.evidence ? (
                    <div className="research-empty">正在读取分析依据…</div>
                  ) : detailedRun.evidence?.length ? (
                    <div className="research-evidence-list">
                      {detailedRun.evidence.map((evidence) => (
                        <details key={evidence.id} className="research-evidence-row">
                          <summary>
                            <span className="research-evidence-kind">{evidence.kind}</span>
                            <span className="research-evidence-title">
                              <b>{evidence.title || '未命名依据'}</b>
                              <small>
                                {evidence.source}
                                {typeof evidence.payload.model === 'string' ? ` · ${evidence.payload.model}` : ''}
                                {typeof evidence.payload.prompt_version === 'string' ? ` · ${evidence.payload.prompt_version}` : ''}
                              </small>
                            </span>
                            <span className="research-evidence-time mono-num">{formatTime(evidence.captured_at)}</span>
                          </summary>
                          <div className="research-evidence-body">
                            {evidence.uri && (
                              <a href={evidence.uri} target="_blank" rel="noreferrer">打开原始来源</a>
                            )}
                            <pre>{JSON.stringify(evidence.payload, null, 2)}</pre>
                          </div>
                        </details>
                      ))}
                    </div>
                  ) : (
                    <div className="research-empty">当前评估没有分析依据。</div>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </section>
      <EvidenceRail
        run={detailedRun}
        integrity={verification.loading ? '校验中' : verification.data?.snapshots_valid ? '已验证' : '无有效快照'}
      />
      </div>
    </div>
  )
}

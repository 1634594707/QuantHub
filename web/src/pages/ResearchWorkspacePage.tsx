import { useCallback, useEffect, useMemo, useState } from 'react'
import { Building2, FileSpreadsheet, Landmark, Scale } from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AnalysisTask, ResearchRun, ResearchStatus } from '../api/types'
import { useApi } from '../api/useApi'
import { useLanguage } from '../i18n'
import DecisionPanel from '../components/DecisionPanel'
import KlineCard from '../components/KlineCard'
import { IconChart } from '../components/icons'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { setRecentResearchPath } from '../navigation/recentResearch'
import { ContextBar } from '../components/ContextBar/ContextBar'
import { EvidenceRail } from '../components/EvidenceRail/EvidenceRail'
import { useRecordNavigation } from '../hooks/useRecordNavigation'
import { shouldAdoptEvaluationRun } from '../lib/researchRunNavigation'
import { ResearchReportStream } from '../components/ResearchReportStream'
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
  fundamentals: '财报质量',
  valuation: '估值位置',
  announcements: '公司公告',
  macro: '宏观传导',
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
  fundamentals: '财报质量',
  valuation: '估值位置',
  announcements: '公司公告',
  macro: '宏观传导',
}

const RESEARCH_MODE_LABELS: Record<string, string> = {
  quick: '简明',
  investor: '投资研究',
  professional: '专业验证',
  quant: '量化实验',
}

const FINANCIAL_QUALITY_LABELS: Record<string, string> = {
  strong: '质量稳健', healthy: '质量健康', mixed: '表现分化', weak: '质量偏弱', insufficient: '数据不足',
}

const EARNINGS_TREND_LABELS: Record<string, string> = {
  improving: '盈利改善', stable: '盈利稳定', deteriorating: '盈利走弱', insufficient: '趋势不足',
}

const VALUATION_RANGE_LABELS: Record<string, string> = {
  cheap: '相对偏低', fair: '合理区间', expensive: '相对偏高', unavailable: '暂不可用',
}

const GUIDANCE_LABELS: Record<string, string> = {
  continue_observing: '继续观察',
  research_further: '值得深入研究',
  wait_for_confirmation: '等待确认',
  review_holding: '持有复核',
  reduce_risk: '降低风险',
  exit_watch: '退出观察',
  insufficient_data: '数据不足',
}

const EVALUATION_PROFILE_LABELS: Record<string, string> = {
  quick: '快速筛查',
  balanced: '均衡评估',
  comprehensive: '全面评估',
}

const WORKSPACE_EVALUATION_METHODS = [
  'trend', 'momentum', 'volatility', 'drawdown', 'mean_reversion',
]
const WORKSPACE_STRATEGY_LENSES = ['trend_following', 'mean_reversion', 'risk_first']
const EVALUATION_HORIZONS: Record<WorkspaceTimeframe, 'short' | 'swing' | 'medium'> = {
  '1h': 'short',
  '1d': 'swing',
  '1w': 'medium',
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
  const news = asRecord(summary?.news)
  const unifiedDecision = asRecord(summary?.research_decision)
  const evidenceFusion = asRecord(summary?.evidence_fusion)
  const fundamentalSummary = asRecord(summary?.fundamentals)
  const valuationSummary = asRecord(summary?.valuation)
  const companyEventSummary = asRecord(summary?.announcements)
  const macroSummary = asRecord(summary?.macro)
  const actionGuidance = asRecord(summary?.action_guidance)
  const companyEvents = Array.isArray(companyEventSummary?.events)
    ? companyEventSummary.events.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : []
  const macroEvents = Array.isArray(macroSummary?.events)
    ? macroSummary.events.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : []
  const macroTransmissions = Array.isArray(macroSummary?.transmissions)
    ? macroSummary.transmissions.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : []
  const decisionDirection = unifiedDecision?.direction === 'long'
    || unifiedDecision?.direction === 'short'
    || unifiedDecision?.direction === 'neutral'
    || unifiedDecision?.direction === 'conflicted'
    || unifiedDecision?.direction === 'insufficient'
    ? unifiedDecision.direction
    : 'insufficient'
  const executionEligible = unifiedDecision?.execution_eligible === true
  const moduleOpinions = Array.isArray(unifiedDecision?.module_opinions)
    ? unifiedDecision.module_opinions.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : []
  const decisionConflicts = Array.isArray(unifiedDecision?.conflicts)
    ? unifiedDecision.conflicts.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : []
  const successfulModules = run.modules.filter((module) => {
    const moduleSummary = asRecord(summary?.[module])
    return moduleSummary !== null && moduleSummary.ok !== false
  })
  const contributors = Array.isArray(ensemblePayload?.contributors)
    ? ensemblePayload.contributors.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : []
  const availableContributors = contributors.filter((item) => item.available !== false)
  const hasConflict = decisionDirection === 'conflicted'
  const conclusion = decisionDirection === 'long'
    ? '偏强'
    : decisionDirection === 'short'
      ? '偏弱'
      : decisionDirection === 'neutral'
        ? '中性'
        : decisionDirection === 'conflicted'
          ? '方向分歧'
          : '数据不足'
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
  const watchPoints = Array.isArray(unifiedDecision?.reevaluate_triggers)
    ? unifiedDecision.reevaluate_triggers.filter((item): item is string => typeof item === 'string').slice(0, 5)
    : Array.isArray(decision?.watch_points)
      ? decision.watch_points.filter((item): item is string => typeof item === 'string').slice(0, 3)
      : []
  const sourceDetails = Array.from(new Set((run.evidence ?? []).map((item) => item.source).filter(Boolean)))
  const disagreements = decisionConflicts.map((item) => String(item.reason ?? item.kind ?? '模块意见冲突'))
  const coverage = ['fundamental', 'valuation', 'company_events', 'macro', 'factor', 'holding'].map((key) => {
    const item = asRecord(evidenceFusion?.[key])
    return {
      key,
      covered: item?.covered === true || item?.status === 'covered' || (key === 'holding' && (item?.available === true || item?.status === 'held')),
      missing: Array.isArray(item?.missing_fields) ? item.missing_fields.map(String) : [],
    }
  })
  const entry = asNumber(decision?.entry_price)
  const invalidation = asNumber(decision?.stop_loss_price)
  const target = asNumber(decision?.take_profit_price)
  const geometryReference = entry ?? asNumber(marketSummary?.latest_price)
  const targetGeometryValid = target === null || geometryReference === null
    ? null
    : decisionDirection === 'long'
      ? target > geometryReference
      : decisionDirection === 'short'
        ? target < geometryReference
        : null

  return {
    conclusion,
    decisionDirection,
    executionEligible,
    decisionVersion: typeof unifiedDecision?.decision_version === 'string' ? unifiedDecision.decision_version : null,
    moduleOpinions,
    coverage,
    headline: decisionDirection === 'insufficient'
      ? '关键证据缺失或过期，当前不能形成可执行结论。'
      : hasConflict
        ? '有效模块方向相反，统一决策已失败关闭。'
        : decisionDirection === 'neutral'
          ? '有效模块没有形成方向性优势。'
          : `统一研究决策为${conclusion}。`,
    explanation: disagreements.length
      ? `阻断原因：${disagreements.join('；')}`
      : `决策版本 ${typeof unifiedDecision?.decision_version === 'string' ? unifiedDecision.decision_version : '未知'}，有效模块：${successfulModules.map((module) => MODULE_LABELS[module] ?? module).join('、') || '无'}。`,
    newsStatus: asNumber(news?.total) === 0 ? '暂无有效新闻' : news ? '已纳入新闻' : '新闻未纳入',
    latestPrice: asNumber(marketSummary?.latest_price),
    latestTime: marketSummary?.latest_time,
    marketSource: typeof marketSummary?.source === 'string' ? marketSummary.source : null,
    entry,
    invalidation,
    target,
    targetLabel: decisionDirection === 'long' ? '上方目标位' : decisionDirection === 'short' ? '下方目标位' : '参考目标位',
    targetGeometryValid,
    invalidationConditions: Array.isArray(unifiedDecision?.invalidation_conditions) ? unifiedDecision.invalidation_conditions.filter((item): item is string => typeof item === 'string') : [],
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
    fundamental: fundamentalSummary,
    valuation: valuationSummary,
    companyEventSummary,
    macroSummary,
    companyEvents,
    macroEvents,
    macroTransmissions,
    actionGuidance,
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
  const evidence = run.evidence ?? []
  appendText(documentCopy.body, 'h1', `${instrumentName ? `${instrumentName} ` : ''}${run.symbol} 评估报告`)
  appendText(documentCopy.body, 'small', `${run.market} · ${run.timeframe} · ${formatTime(run.updated_at)} · ${run.id}`)
  const evidenceCutoffs = evidence.flatMap((item) => {
    const provenance = asRecord(item.payload?.provenance)
    return typeof provenance?.available_at === 'string'
      ? [provenance.available_at]
      : []
  })
  const dataCutoff = evidenceCutoffs.reduce<string | null>((latest, current) => (
    latest === null || Date.parse(current) > Date.parse(latest) ? current : latest
  ), null) ?? new Date(run.updated_at * 1000).toISOString()
  const methodVersions = Array.from(new Set(evidence.flatMap((item) => {
    const values = [item.source]
    const payload = item.payload
    for (const key of ['method_version', 'decision_version', 'version']) {
      if (typeof payload?.[key] === 'string') values.push(payload[key] as string)
    }
    return values.filter(Boolean)
  }))).sort()
  appendText(documentCopy.body, 'h2', `结论：${report.conclusion}`)
  appendText(documentCopy.body, 'p', report.headline)
  appendText(documentCopy.body, 'p', report.explanation)
  const facts = documentCopy.createElement('dl')
  ;[
    ['最新价格', report.latestPrice?.toLocaleString('zh-CN') ?? '数据不足'],
    ['价格时间', typeof report.latestTime === 'string' ? report.latestTime : '数据不足'],
    ['行情来源', report.marketSource ?? '数据不足'],
    ['适用周期', TIMEFRAME_LABELS[run.timeframe as WorkspaceTimeframe] ?? run.timeframe],
    ['数据截止', dataCutoff],
    ['证据数量', `${evidence.length} 条`],
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
  const auditSection = documentCopy.createElement('section')
  appendText(auditSection, 'h2', '证据来源与方法版本')
  appendText(auditSection, 'p', methodVersions.length ? methodVersions.join(' · ') : '没有可用的方法版本记录')
  const sourceList = documentCopy.createElement('ul')
  evidence.forEach((item) => {
    appendText(sourceList, 'li', `${item.kind} · ${item.title || '未命名证据'} · ${item.source}${item.uri ? ` · ${item.uri}` : ''}`)
  })
  auditSection.appendChild(sourceList)
  documentCopy.body.appendChild(auditSection)
  const watchSection = documentCopy.createElement('section')
  appendText(watchSection, 'h2', '风险、失效条件与观察项')
  appendText(watchSection, 'p', `主要风险：${report.risk}`)
  appendText(watchSection, 'p', `失效条件：${report.invalidation?.toLocaleString('zh-CN') ?? '数据不足'}`)
  const watchList = documentCopy.createElement('ul')
  ;(report.watchPoints.length ? report.watchPoints : ['等待下一次有效数据更新后重新评估']).forEach((item) => appendText(watchList, 'li', item))
  watchSection.appendChild(watchList)
  documentCopy.body.appendChild(watchSection)
  appendText(documentCopy.body, 'footer', '研究参考，不构成投资建议或收益承诺；请结合报告所列原始来源独立判断。')
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
  const { t } = useLanguage()
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
  const requestedReportId = searchParams.get('report_id') || ''
  const rawView = searchParams.get('view') || 'overview'
  const view: View = VIEWS.some((item) => item.key === rawView) ? rawView as View : 'overview'
  const rawResearchMode = searchParams.get('mode') || 'investor'
  const researchMode = rawResearchMode in RESEARCH_MODE_LABELS ? rawResearchMode : 'investor'

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
  const [evaluationStarting, setEvaluationStarting] = useState(false)
  const [evaluationStartError, setEvaluationStartError] = useState('')
  const preference = useApi(() => api.researchPreference(), [], { retry: false })
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
  const latestResearchRun = useMemo(
    () => {
      const hasDeepResearch = (run: ResearchRun) => {
        const summary = asRecord(run.summary)
        return run.modules.some((module) => ['fundamentals', 'valuation', 'announcements', 'macro'].includes(module))
          || Boolean(summary?.fundamentals || summary?.valuation || summary?.announcements || summary?.macro)
      }
      if (detailedRun && hasDeepResearch(detailedRun)) return detailedRun
      return runs.find((run) => (
        (run.status === 'succeeded' || run.status === 'partial') && hasDeepResearch(run)
      )) ?? null
    },
    [detailedRun, runs],
  )
  const latestResearchReport = useMemo(
    () => latestResearchRun ? buildReadableReport(latestResearchRun) : null,
    [latestResearchRun],
  )
  const researchModuleStates = useMemo(() => {
    const unsupported = (detail: string) => ({ status: 'unsupported', statusLabel: '不适用', value: detail })
    const pending = { status: 'pending', statusLabel: '待评估', value: '运行全面评估后显示' }
    const missing = { status: 'missing', statusLabel: '数据缺口', value: '最近评估未形成有效证据' }
    if (market === 'crypto') {
      return [
        { key: 'fundamentals', label: '财报质量', icon: FileSpreadsheet, ...unsupported('数字资产不适用公司财报') },
        { key: 'valuation', label: '估值位置', icon: Scale, ...unsupported('数字资产不使用公司估值口径') },
        { key: 'announcements', label: '公司事件', icon: Building2, ...unsupported('数字资产不适用公司公告域') },
        { key: 'macro', label: '宏观传导', icon: Landmark, ...unsupported('当前版本未建立可靠传导') },
      ]
    }
    const report = latestResearchReport
    const financialQuality = typeof report?.fundamental?.financial_quality === 'string'
      ? FINANCIAL_QUALITY_LABELS[report.fundamental.financial_quality] ?? report.fundamental.financial_quality
      : null
    const earningsTrend = typeof report?.fundamental?.earnings_trend === 'string'
      ? EARNINGS_TREND_LABELS[report.fundamental.earnings_trend] ?? report.fundamental.earnings_trend
      : null
    const valuationRange = typeof report?.valuation?.valuation_range === 'string'
      ? VALUATION_RANGE_LABELS[report.valuation.valuation_range] ?? report.valuation.valuation_range
      : null
    const valuationPercentile = asNumber(report?.valuation?.valuation_percentile)
    const verifiedEventCount = asNumber(report?.companyEventSummary?.verified_count) ?? report?.companyEvents.length ?? 0
    const reliableTransmissionCount = asNumber(report?.macroSummary?.reliable_transmission_count) ?? report?.macroTransmissions.length ?? 0
    const supportedCompanyModules = market === 'a_shares'
    return [
      {
        key: 'fundamentals', label: '财报质量', icon: FileSpreadsheet,
        ...(report?.fundamental
          ? { status: 'covered', statusLabel: '已覆盖', value: [financialQuality, earningsTrend].filter(Boolean).join(' · ') || '已生成财务快照' }
          : latestResearchRun ? missing : pending),
      },
      {
        key: 'valuation', label: '估值位置', icon: Scale,
        ...(report?.valuation
          ? { status: 'covered', statusLabel: '已覆盖', value: `${valuationRange ?? '已生成估值快照'}${valuationPercentile === null ? '' : ` · 历史分位 ${Math.round(valuationPercentile * 100)}%`}` }
          : latestResearchRun ? missing : pending),
      },
      {
        key: 'announcements', label: '公司事件', icon: Building2,
        ...(supportedCompanyModules
          ? report?.companyEventSummary
            ? { status: 'covered', statusLabel: '已覆盖', value: `${verifiedEventCount} 条已核实事件` }
            : latestResearchRun ? missing : pending
          : unsupported('当前美股版本暂未接入')),
      },
      {
        key: 'macro', label: '宏观传导', icon: Landmark,
        ...(supportedCompanyModules
          ? report?.macroSummary
            ? { status: 'covered', statusLabel: '已覆盖', value: `${reliableTransmissionCount} 条可靠传导` }
            : latestResearchRun ? missing : pending
          : unsupported('当前美股版本暂未接入')),
      },
    ]
  }, [latestResearchReport, latestResearchRun, market])
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

  useEffect(() => {
    const preferredMode = preference.data?.preference.default_mode
    if (searchParams.has('mode') || !preferredMode) return
    const query = new URLSearchParams(searchParams)
    query.set('mode', preferredMode)
    setSearchParams(query, { replace: true })
  }, [preference.data, searchParams, setSearchParams])

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

  async function startEvaluation() {
    setEvaluationStarting(true)
    setEvaluationStartError('')
    try {
      const modules = market === 'a_shares'
        ? ['market', 'news', 'pa', 'ensemble', 'fundamentals', 'valuation', 'announcements', 'macro']
        : market === 'us_stocks'
          ? ['market', 'pa', 'ensemble', 'fundamentals', 'valuation']
          : ['market', 'pa', 'ensemble']
      const response = await api.createAnalysisTask({
        kind: 'evaluation',
        symbol,
        market,
        timeframe,
        payload: {
          modules,
          evaluation_horizon: EVALUATION_HORIZONS[timeframe],
          evaluation_profile: market === 'crypto' ? 'balanced' : 'comprehensive',
          market_methods: WORKSPACE_EVALUATION_METHODS,
          strategy_lenses: WORKSPACE_STRATEGY_LENSES,
          market_limit: market === 'crypto' ? 240 : 480,
          research_mode: researchMode,
          holding_status: preference.data?.preference.holding_status ?? 'not_held',
        },
        timeout_seconds: 360,
      })
      const query = new URLSearchParams(searchParams)
      query.set('evaluation_task_id', response.task.id)
      query.set('view', 'overview')
      query.delete('run_id')
      query.delete('compare_run_id')
      setActiveRunId(null)
      setCompareRunId('')
      navigate(`/research/${encodeURIComponent(symbol)}?${query.toString()}`, { replace: true })
    } catch (error) {
      setEvaluationStartError(error instanceof Error ? error.message : '综合评估任务创建失败')
    } finally {
      setEvaluationStarting(false)
    }
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

  function setResearchMode(next: string) {
    const query = new URLSearchParams(searchParams)
    query.set('mode', next)
    setSearchParams(query, { replace: true })
    const saved = preference.data?.preference
    if (next in RESEARCH_MODE_LABELS) {
      void api.updateResearchPreference({
        default_mode: next as 'quick' | 'investor' | 'professional' | 'quant',
        default_market: saved?.default_market ?? market,
        holding_status: saved?.holding_status ?? 'not_held',
        research_horizon: saved?.research_horizon ?? EVALUATION_HORIZONS[timeframe],
        risk_preference: saved?.risk_preference ?? 'balanced',
        terminology_level: saved?.terminology_level ?? 'standard',
      }).then((response) => preference.setData(response)).catch(() => undefined)
    }
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
          { label: t('市场'), value: t(MARKET_LABELS[market] ?? market) },
          { label: t('关注周期'), value: t(TIMEFRAME_LABELS[timeframe]) },
          { label: t('分析依据'), value: activeRun ? `${activeRun.evidence_count} ${t('条')}` : t('等待首次分析') },
        ]}
      />
      {evaluationTaskId && (
        <section className="evaluation-progress" aria-label={t('综合评估进度')}>
          <div className="evaluation-progress-head">
            <div>
              <span>{t('统一标的评估')}</span>
              <strong>{evaluation ? t(STATUS_META[evaluation.status === 'succeeded' && evaluationResult.partial === true ? 'partial' : evaluation.status as ResearchStatus]?.label ?? evaluation.status) : t('正在读取任务')}</strong>
            </div>
            <div className="evaluation-progress-actions">
              {evaluation && ['queued', 'running'].includes(evaluation.status) && (
                <button type="button" onClick={() => void cancelEvaluation()}>{t('取消评估')}</button>
              )}
              {evaluation && ['failed', 'cancelled', 'timeout'].includes(evaluation.status) && (
                <button type="button" onClick={() => void retryEvaluation()}>{t('重新评估')}</button>
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
                  <b>{t(label)}</b>
                  <small>{t(derived === 'succeeded' ? '完成' : derived === 'failed' ? '失败' : derived === 'running' ? '进行中' : '等待')}</small>
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
        { label: t('市场'), value: t(MARKET_LABELS[market] ?? market) },
        { label: t('关注周期'), value: t(TIMEFRAME_LABELS[timeframe]) },
        { label: t('评估状态'), value: activeRun ? t(STATUS_META[activeRun.status].label) : t('未开始') },
        { label: t('更新时间'), value: activeRun ? formatTime(activeRun.updated_at) : '—', mono: true },
      ]}>
        <form
          className="research-context-controls"
          onSubmit={(event) => {
            event.preventDefault()
            updateContext({ symbol: symbolInput })
          }}
        >
          <label>
            <span>{t('标的代码')}</span>
            <input
              value={symbolInput}
              onChange={(event) => setSymbolInput(event.target.value)}
              placeholder="600519"
              aria-label={t('标的代码')}
            />
          </label>
          <label>
            <span>{t('市场')}</span>
            <select
              value={market}
              onChange={(event) => updateContext({ market: event.target.value as WorkspaceMarket })}
              aria-label={t('标的市场')}
            >
              <option value="a_shares">{t('A股')}</option>
              <option value="us_stocks">{t('美股')}</option>
              <option value="crypto">{t('虚拟货币')}</option>
            </select>
          </label>
          <div className="research-timeframes" role="group" aria-label={t('关注周期')}>
            {TIMEFRAMES.map((item) => (
              <button
                type="button"
                key={item}
                className={item === timeframe ? 'active' : ''}
                onClick={() => updateContext({ timeframe: item })}
              >
                {t(TIMEFRAME_LABELS[item])}
              </button>
            ))}
          </div>
          <label>
            <span>{t('查看方式')}</span>
            <select
              value={researchMode}
              onChange={(event) => setResearchMode(event.target.value)}
              aria-label={t('研究查看方式')}
            >
              {Object.entries(RESEARCH_MODE_LABELS).map(([value, label]) => (
                <option value={value} key={value}>{t(label)}</option>
              ))}
            </select>
          </label>
          <button className="research-go" type="submit">{t('切换')}</button>
          <Button
            className="research-evaluate"
            type="button"
            variant="primary"
            icon={<IconChart size={16} />}
            loading={evaluationStarting}
            disabled={evaluation?.status === 'queued' || evaluation?.status === 'running'}
            onClick={() => void startEvaluation()}
          >
            {t(evaluation?.status === 'queued' || evaluation?.status === 'running' ? '全面评估进行中' : '运行全面评估')}
          </Button>
        </form>
      </ContextBar>
      {evaluationStartError && (
        <div className="evaluation-start-error" role="alert">
          <strong>{t('一键评估启动失败')}</strong>
          <span>{evaluationStartError}。{t('当前工作台数据未受影响，请检查分析服务后重试。')}</span>
        </div>
      )}

      <section className="research-module-rail" aria-labelledby="research-module-title">
        <header>
          <div>
            <span>{t('最新研究覆盖')}</span>
            <h2 id="research-module-title">{t('财务、估值与事件状态')}</h2>
          </div>
          <p>{latestResearchRun ? `${t('读取最近评估')} · ${formatTime(latestResearchRun.updated_at)}` : t('全面评估会在这里直接给出结果摘要')}</p>
        </header>
        <div className="research-module-grid">
          {researchModuleStates.map((module) => {
            const ModuleIcon = module.icon
            return (
              <div className={`research-module ${module.status}`} key={module.key}>
                <ModuleIcon size={18} aria-hidden="true" />
                <div>
                  <span>{t(module.label)}</span>
                  <strong>{t(module.value)}</strong>
                </div>
                <small><i aria-hidden="true" />{t(module.statusLabel)}</small>
              </div>
            )
          })}
        </div>
      </section>
      {detailedRun ? <ResearchReportStream runId={detailedRun.id} reportId={requestedReportId || undefined} mode={researchMode as 'quick' | 'investor' | 'professional' | 'quant'} /> : null}

      <nav className="research-tabs" aria-label={t('综合评估视图')}>
        {VIEWS.map((item) => (
          <button
            type="button"
            key={item.key}
            className={view === item.key ? 'active' : ''}
            onClick={() => setView(item.key)}
          >
            {t(item.label)}
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
                    {readableReport.actionGuidance && (
                      <section className="research-action-guidance" aria-label="场景化建议参考">
                        <div>
                          <span>建议参考</span>
                          <b>{GUIDANCE_LABELS[String(readableReport.actionGuidance.status)] ?? String(readableReport.actionGuidance.status)}</b>
                        </div>
                        <p>{Array.isArray(readableReport.actionGuidance.primary_reasons) ? readableReport.actionGuidance.primary_reasons.map(String).slice(0, 3).join('；') : '等待有效建议依据'}</p>
                        <small>{String(readableReport.actionGuidance.disclaimer ?? '研究参考，不是收益承诺。')}</small>
                      </section>
                    )}
                    <div className="research-decision-modules" aria-label="统一研究决策模块意见">
                      {readableReport.moduleOpinions.map((opinion) => <div key={String(opinion.module)}><span>{MODULE_LABELS[String(opinion.module)] ?? String(opinion.module)}</span><b>{String(opinion.direction)}</b><small>{String(opinion.status)}{typeof opinion.reason === 'string' && opinion.reason ? ` · ${opinion.reason}` : ''}</small></div>)}
                      {!readableReport.moduleOpinions.length && <div><span>统一决策</span><b>insufficient</b><small>没有保存模块意见</small></div>}
                    </div>
                    <div className="research-evidence-coverage" aria-label="证据覆盖范围">
                      {readableReport.coverage.map((item) => <span key={item.key} className={item.covered ? 'covered' : 'missing'}>{item.key === 'fundamental' ? '基本面' : item.key === 'valuation' ? '估值' : item.key === 'company_events' ? '公司事件' : item.key === 'macro' ? '宏观传导' : item.key === 'factor' ? '因子' : '持仓'} · {item.covered ? '已覆盖' : `缺失${item.missing.length ? `：${item.missing.join('/')}` : ''}`}</span>)}
                    </div>
                    <dl className="research-report-metrics">
                      <div><dt>最新价格</dt><dd>{readableReport.latestPrice?.toLocaleString('zh-CN') ?? '数据不足'}</dd></div>
                      <div><dt>价格时间</dt><dd>{typeof readableReport.latestTime === 'string' ? readableReport.latestTime : '数据不足'}</dd></div>
                      <div><dt>行情来源</dt><dd>{readableReport.marketSource ?? '数据不足'}</dd></div>
                      <div><dt>新闻覆盖</dt><dd>{readableReport.newsStatus}</dd></div>
                    </dl>
                    {(readableReport.fundamental || readableReport.valuation) && (
                      <div className="research-financial-grid">
                        <section>
                          <span>财报质量</span>
                          <b>{String(readableReport.fundamental?.financial_quality ?? '数据不足')}</b>
                          <small>盈利趋势 {String(readableReport.fundamental?.earnings_trend ?? 'insufficient')} · 现金流 {String(readableReport.fundamental?.cash_flow_quality ?? 'insufficient')}</small>
                        </section>
                        <section>
                          <span>估值位置</span>
                          <b>{String(readableReport.valuation?.valuation_range ?? '数据不足')}</b>
                          <small>自身历史分位 {typeof readableReport.valuation?.valuation_percentile === 'number' ? `${(readableReport.valuation.valuation_percentile * 100).toFixed(0)}%` : '不可用'} · 置信度 {typeof readableReport.valuation?.confidence === 'number' ? `${(readableReport.valuation.confidence * 100).toFixed(0)}%` : '不可用'}</small>
                        </section>
                      </div>
                    )}
                    {(readableReport.companyEvents.length > 0 || readableReport.macroEvents.length > 0 || readableReport.macroTransmissions.length > 0) && (
                      <section className="research-event-timeline" aria-labelledby="research-event-timeline-title">
                        <header>
                          <div>
                            <span>公司与宏观</span>
                            <h3 id="research-event-timeline-title">事件时间线</h3>
                          </div>
                          <p>{String(readableReport.companyEventSummary?.reason ?? readableReport.macroSummary?.reason ?? '事件证据已归档')}</p>
                        </header>
                        <div className="research-event-list">
                          {[
                            ...readableReport.companyEvents.map((event) => ({
                              kind: '公司事件',
                              title: String(event.title ?? '未命名公司事件'),
                              time: String(asRecord(event.provenance)?.published_at ?? ''),
                              direction: String(event.direction ?? 'insufficient'),
                              detail: `${String(event.category ?? 'other')} · ${String(event.verification_status ?? 'pending')}`,
                            })),
                            ...readableReport.macroEvents.map((event) => ({
                              kind: '宏观事件',
                              title: String(event.title ?? '未命名宏观事件'),
                              time: String(asRecord(event.provenance)?.published_at ?? ''),
                              direction: String(event.direction ?? 'insufficient'),
                              detail: `${String(event.state ?? 'scheduled')} · 实际 ${String(event.actual_value ?? '待公布')} · 预期 ${String(event.expected_value ?? '无')}`,
                            })),
                            ...readableReport.macroTransmissions.map((item) => ({
                              kind: '宏观传导',
                              title: `${String(item.channel ?? 'unknown')} → ${symbol}`,
                              time: '',
                              direction: String(item.direction ?? 'insufficient'),
                              detail: `${String(item.order ?? 'second_order')} · ${String(item.horizon ?? 'short')} · 强度 ${typeof item.strength === 'number' ? Math.round(item.strength * 100) : 0}%`,
                            })),
                          ]
                            .sort((left, right) => right.time.localeCompare(left.time))
                            .slice(0, researchMode === 'quick' ? 4 : 10)
                            .map((item, index) => (
                              <article key={`${item.kind}:${item.title}:${index}`}>
                                <time>{item.time ? new Date(item.time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '传导'}</time>
                                <i className={`direction-${item.direction}`} aria-hidden="true" />
                                <div>
                                  <span>{item.kind}</span>
                                  <b>{item.title}</b>
                                  <small>{item.detail}</small>
                                </div>
                              </article>
                            ))}
                        </div>
                      </section>
                    )}
                    {researchMode !== 'quick' && readableReport.quantitativeDimensions.length > 0 && (
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
                    {readableReport.executionEligible ? <div className="research-report-levels" aria-label="模型关键价位">
                      <div><span>模型观察位</span><b>{readableReport.entry?.toLocaleString('zh-CN') ?? '—'}</b><small>不是买入价</small></div>
                      <div><span>判断失效位</span><b>{readableReport.invalidation?.toLocaleString('zh-CN') ?? '—'}</b><small>突破后重新评估</small></div>
                      <div><span>{readableReport.targetLabel}</span><b>{readableReport.target?.toLocaleString('zh-CN') ?? '—'}</b><small>{readableReport.targetGeometryValid === false ? '价位几何关系异常，禁止执行' : readableReport.decisionDirection === 'long' ? '应高于观察位' : '应低于观察位'}</small></div>
                    </div> : <div className="research-execution-gate" role="status"><b>执行入口已锁定</b><span>{readableReport.decisionDirection === 'conflicted' ? '方向冲突' : '证据不足或无方向性优势'}，不展示入场、止损和止盈动作。</span></div>}
                    <div className="research-report-reasons">
                      <div>
                        <h3>为什么这样判断</h3>
                        <ul>{(readableReport.keyFactors.length ? readableReport.keyFactors : ['当前运行没有可展示的主要依据']).map((item) => (
                          <li key={item}>
                            {researchMode === 'professional' || researchMode === 'quant' ? (
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
                            ) : item}
                          </li>
                        ))}</ul>
                      </div>
                      <div>
                        <h3>接下来观察什么</h3>
                        <ul>{(readableReport.watchPoints.length ? readableReport.watchPoints : ['等待下一次有效数据更新后重新评估']).map((item) => <li key={item}>{item}</li>)}</ul>
                      </div>
                    </div>
                    {readableReport.disagreements.length > 0 && <p className="research-report-risk"><b>模块分歧</b>{readableReport.disagreements.join('；')}</p>}
                    {readableReport.invalidationConditions.length > 0 && <p className="research-report-risk"><b>失效条件</b>{readableReport.invalidationConditions.join('；')}</p>}
                    <p className="research-report-risk"><b>主要风险</b>{readableReport.risk}</p>
                    <div className="research-report-actions">
                      <button type="button" onClick={() => void addCurrentInstrumentToWatchlist()}>加入自选</button>
                      <button type="button" onClick={() => navigate(`/alerts?action=create&type=evaluation_changed&symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}&research_run_id=${encodeURIComponent(detailedRun.id)}`)}>监控结论变化</button>
                      {readableReport.invalidation !== null && readableReport.decisionDirection !== 'insufficient' && (
                        <button type="button" onClick={() => navigate(`/alerts?action=create&type=risk_invalidated&symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}&threshold=${encodeURIComponent(String(readableReport.invalidation))}&condition=${readableReport.decisionDirection === 'short' ? 'above' : 'below'}&research_run_id=${encodeURIComponent(detailedRun.id)}`)}>监控失效条件</button>
                      )}
                      <button type="button" disabled={!readableReport.executionEligible || readableReport.targetGeometryValid === false} title={!readableReport.executionEligible ? '统一研究决策未通过执行门禁' : readableReport.targetGeometryValid === false ? '关键价位几何关系异常' : undefined} onClick={() => navigate(`/simulation?symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}`)}>进入模拟交易</button>
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
                          <small>依据：{row.evidence_count} 条 · 方向：{comparison.data?.structured_snapshots[index]?.direction ?? 'insufficient'}</small>
                          <small>规则：{comparison.data?.structured_snapshots[index]?.decision_version ?? '未知'} · 执行：{comparison.data?.structured_snapshots[index]?.execution_eligible ? '允许' : '阻断'}</small>
                        </div>
                      ))}
                    </div>
                    <div className="research-comparison-changes">
                      {comparison.data.changes.map((change, index) => <div key={`${change.kind}:${change.field}:${index}`}><span>{change.kind} / {change.field}</span><b>{String(change.before ?? '—')} → {String(change.after ?? '—')}</b>{typeof change.delta === 'number' && <small>差值 {change.delta > 0 ? '+' : ''}{change.delta}</small>}</div>)}
                      {!comparison.data.changes.length && <div><span>实质变化</span><b>未检测到结构化字段变化</b></div>}
                    </div>
                  </div>
                )}
                {(researchMode === 'professional' || researchMode === 'quant') && <div className="research-evidence-ledger">
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
                </div>}
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

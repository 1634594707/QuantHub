import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Database,
  FlaskConical,
  Gauge,
  History,
  Info,
  Microscope,
  Play,
  RefreshCw,
  ScanLine,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Waves,
  X,
} from 'lucide-react'
import { api } from '../api/client'
import type {
  DrawdownLevel,
  FactorCurvePoint,
  FactorEvaluation,
  FactorResearchResp,
  FactorAiReviewResp,
  FactorStatus,
  ResearchRun,
} from '../api/types'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { Button } from '../components/ui/Button/Button'
import { EmptyState } from '../components/ui/EmptyState/EmptyState'
import { Input } from '../components/ui/Input/Input'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { Select } from '../components/ui/Select/Select'
import { classifyResearchError, recordUsabilityEvent } from '../lib/usabilityMetrics'
import s from './FactorResearchPage.module.css'

const MARKETS = [
  { value: 'a_shares', label: 'A 股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '加密资产' },
  { value: 'mt5', label: 'MT5' },
]

const INTERVALS = [
  { value: '1d', label: '日线' },
  { value: '4h', label: '4 小时' },
  { value: '1h', label: '1 小时' },
]

const HORIZONS = [
  { value: '3', label: '未来 3 周期' },
  { value: '5', label: '未来 5 周期' },
  { value: '10', label: '未来 10 周期' },
  { value: '20', label: '未来 20 周期' },
]

const VIEW_OPTIONS = [
  { value: 'current', label: '当前研究' },
  { value: 'history', label: '历史记录' },
]

const RUN_STATUS_LABEL: Record<string, string> = {
  succeeded: '已完成',
  partial: '统计完成 / AI 未完成',
  failed: '失败',
  running: '运行中',
  draft: '准备中',
}

type ResearchForm = {
  market: string
  symbol: string
  interval: string
  limit: number
  horizon: number
  transaction_cost_bps: number
}

type ResearchTemplateKey = 'short' | 'swing' | 'medium' | 'custom'

const RESEARCH_TEMPLATES: Record<Exclude<ResearchTemplateKey, 'custom'>, {
  label: string
  description: string
  values: Pick<ResearchForm, 'interval' | 'limit' | 'horizon' | 'transaction_cost_bps'>
}> = {
  short: {
    label: '短线',
    description: '未来 3 个交易日 · 300 根日线',
    values: { interval: '1d', limit: 300, horizon: 3, transaction_cost_bps: 10 },
  },
  swing: {
    label: '波段',
    description: '未来 5 个交易日 · 500 根日线',
    values: { interval: '1d', limit: 500, horizon: 5, transaction_cost_bps: 10 },
  },
  medium: {
    label: '中线',
    description: '未来 20 个交易日 · 1000 根日线',
    values: { interval: '1d', limit: 1000, horizon: 20, transaction_cost_bps: 10 },
  },
}

const TEMPLATE_OPTIONS = [
  { value: 'short', label: '短线' },
  { value: 'swing', label: '波段' },
  { value: 'medium', label: '中线' },
  { value: 'custom', label: '自定义' },
]

type ResearchGoalKey = 'robust' | 'trend' | 'drawdown'

const RESEARCH_GOALS: Record<ResearchGoalKey, {
  label: string
  description: string
  values: Pick<ResearchForm, 'interval' | 'limit' | 'horizon' | 'transaction_cost_bps'>
}> = {
  robust: {
    label: '稳健验证',
    description: '扩大样本并提高成本假设，优先排除偶然有效。',
    values: { interval: '1d', limit: 1000, horizon: 5, transaction_cost_bps: 20 },
  },
  trend: {
    label: '趋势研究',
    description: '观察趋势与动量因子在中短期样本外表现。',
    values: { interval: '1d', limit: 500, horizon: 10, transaction_cost_bps: 10 },
  },
  drawdown: {
    label: '回撤检查',
    description: '使用更长观察窗口，重点阅读风险退出与恢复信号。',
    values: { interval: '1d', limit: 1000, horizon: 20, transaction_cost_bps: 15 },
  },
}

const EXAMPLE_REPORTS = [
  { tone: 'positive', label: '正常', title: '可继续研究（示例）', detail: '样本外 IC 为正、成本后收益为正；下一步做滚动窗口与跨标的验证。' },
  { tone: 'risk', label: '风险退出', title: '当前优先控制回撤', detail: '统计因子仍可保留，但回撤信号进入减仓或风险退出，暂停扩大使用范围。' },
  { tone: 'caution', label: '数据不足', title: '证据不足，暂不进入策略实验', detail: '有效样本或可用因子不足；补充历史数据、调整周期后重新验证。' },
  { tone: 'neutral', label: 'AI 失败', title: '统计已完成，AI 复核未完成', detail: '程序统计结论与历史记录保持可用；检查模型服务后可单独重新复核。' },
] as const

const TERM_GLOSSARY = [
  { term: 'IC', explanation: '因子值与未来收益的相关性。绝对值越大，因子对未来排序的解释力通常越强。' },
  { term: 'ICIR', explanation: 'IC 的平均值除以波动，用来观察因子解释力是否稳定，而不只看某一次表现。' },
  { term: '样本外', explanation: '没有参与权重选择的数据区间，用于检验结论能否离开训练数据后继续成立。' },
  { term: 'CVaR', explanation: '最差一部分情形中的平均损失，比单一最大回撤更关注尾部风险。' },
  { term: 'Calmar', explanation: '年化收益相对最大回撤的比值，用来衡量承担一单位回撤得到多少收益。' },
  { term: '回撤信号', explanation: '从历史高点下跌后的风险状态提示，只约束风险动作，不等同于买卖指令。' },
] as const

const FIRST_READ_GUIDE_KEY = 'quanthub.factor-research.guide-dismissed.v1'

const STATUS_LABEL: Record<FactorStatus, string> = {
  usable: '可用',
  watch: '观察',
  reject: '淘汰',
}

const LEVEL_ICON: Record<DrawdownLevel, typeof Activity> = {
  normal: CheckCircle2,
  watch: AlertTriangle,
  reduce: ArrowDownRight,
  risk_off: ShieldAlert,
  recovery: ArrowUpRight,
}

function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`
}

function signed(value: number, digits = 3): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

function formatRunTime(value: number | undefined): string {
  if (!value) return '—'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

function marketLabel(value: string): string {
  return MARKETS.find((item) => item.value === value)?.label ?? value
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function inferResearchTemplate(form: ResearchForm): ResearchTemplateKey {
  const entry = Object.entries(RESEARCH_TEMPLATES).find(([, template]) => (
    template.values.interval === form.interval
    && template.values.limit === form.limit
    && template.values.horizon === form.horizon
    && template.values.transaction_cost_bps === form.transaction_cost_bps
  ))
  return entry ? entry[0] as ResearchTemplateKey : 'custom'
}

function researchConclusion(result: FactorResearchResp): {
  tone: 'positive' | 'caution' | 'risk'
  title: string
  description: string
} {
  const method = result.methods.find((item) => item.key === result.summary.best_method)
    ?? result.methods[0]
  if (['risk_off', 'reduce'].includes(result.current_signal.level)) {
    return {
      tone: 'risk',
      title: '当前优先控制回撤',
      description: '统计结果仍可用于研究，但当前风险状态不适合扩大因子使用范围。',
    }
  }
  if (result.summary.usable_factors === 0 || !method || method.total_return <= 0) {
    return {
      tone: 'caution',
      title: '统计证据不足，暂不进入策略实验',
      description: '先补充样本、调整成本假设或更换周期，再检查结论是否稳定。',
    }
  }
  if (method.sharpe >= 1 && result.summary.usable_factors >= 1) {
    return {
      tone: 'positive',
      title: '因子组合具备继续研究价值',
      description: '样本外与成本后结果达到继续验证标准，但仍需跨窗口和跨标的复核。',
    }
  }
  return {
    tone: 'caution',
    title: '存在有效因子，但稳健性仍需确认',
    description: '保留当前候选组合，优先完成滚动样本外和成本压力测试。',
  }
}

function indicatorValue(key: string, value: number | null): string {
  if (value === null) return '—'
  if (['atr_pct', 'realized_volatility', 'downside_volatility', 'macd_histogram'].includes(key)) {
    return pct(value, key === 'macd_histogram' ? 3 : 1)
  }
  if (key === 'relative_volume') return `${value.toFixed(2)}x`
  return value.toFixed(2)
}

function buildPath(
  points: FactorCurvePoint[],
  key: keyof FactorCurvePoint,
  width: number,
  height: number,
  domain?: { min: number; max: number },
): string {
  const values = points.map((point) => Number(point[key])).filter(Number.isFinite)
  if (values.length < 2) return ''
  const min = domain?.min ?? Math.min(...values)
  const max = domain?.max ?? Math.max(...values)
  const range = max - min || 1
  return points.map((point, index) => {
    const value = Number(point[key])
    if (!Number.isFinite(value)) return ''
    const x = (index / Math.max(points.length - 1, 1)) * width
    const y = height - ((value - min) / range) * height
    return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function EquityChart({ points }: { points: FactorCurvePoint[] }) {
  const width = 900
  const height = 240
  const domain = useMemo(() => {
    const values = points.flatMap((point) => [Number(point.asset), Number(point.multifactor)]).filter(Number.isFinite)
    return { min: Math.min(...values), max: Math.max(...values) }
  }, [points])
  const asset = useMemo(() => buildPath(points, 'asset', width, height, domain), [domain, points])
  const multifactor = useMemo(() => buildPath(points, 'multifactor', width, height, domain), [domain, points])
  const start = points[0]?.t?.slice(0, 10) || '—'
  const end = points[points.length - 1]?.t?.slice(0, 10) || '—'
  return (
    <div className={s.chartWrap}>
      <div className={s.legend}>
        <span><i className={s.assetDot} />标的净值</span>
        <span><i className={s.factorDot} />多因子净值</span>
      </div>
      <svg className={s.chart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="标的与多因子净值曲线">
        {[0, 1, 2, 3, 4].map((line) => (
          <line key={line} x1="0" x2={width} y1={line * height / 4} y2={line * height / 4} className={s.gridLine} />
        ))}
        <path d={asset} className={s.assetLine} />
        <path d={multifactor} className={s.factorLine} />
      </svg>
      <div className={s.axis}><span>{start}</span><span>{end}</span></div>
    </div>
  )
}

function DrawdownChart({ points }: { points: FactorCurvePoint[] }) {
  const width = 900
  const height = 150
  const domain = useMemo(() => {
    const values = points.flatMap((point) => [Number(point.asset_drawdown), Number(point.strategy_drawdown)]).filter(Number.isFinite)
    return { min: Math.min(...values), max: Math.max(...values) }
  }, [points])
  const asset = useMemo(() => buildPath(points, 'asset_drawdown', width, height, domain), [domain, points])
  const multifactor = useMemo(() => buildPath(points, 'strategy_drawdown', width, height, domain), [domain, points])
  return (
    <svg className={s.drawdownChart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="标的与多因子回撤曲线">
      {[0, 1, 2, 3].map((line) => (
        <line key={line} x1="0" x2={width} y1={line * height / 3} y2={line * height / 3} className={s.gridLine} />
      ))}
      <path d={asset} className={s.drawdownAsset} />
      <path d={multifactor} className={s.drawdownFactor} />
    </svg>
  )
}

function FactorRow({ factor }: { factor: FactorEvaluation }) {
  return (
    <tr>
      <td>
        <div className={s.factorName}>
          <strong>{factor.label}{factor.selected && <em>训练权重 {(factor.weight * 100).toFixed(0)}%</em>}</strong>
          <span>{factor.category} · {factor.description}</span>
        </div>
      </td>
      <td><span className={`${s.status} ${s[factor.status]}`}>{STATUS_LABEL[factor.status]}</span></td>
      <td className={s.numeric}>{factor.score.toFixed(1)}</td>
      <td className={`${s.numeric} ${factor.test_ic > 0 ? s.positive : s.negative}`}>{signed(factor.test_ic)}</td>
      <td className={`${s.numeric} ${factor.icir > 0 ? s.positive : s.negative}`}>{signed(factor.icir, 2)}</td>
      <td className={s.numeric}>{pct(factor.positive_ic_ratio, 0)}</td>
      <td className={s.numeric}>{pct(factor.hit_rate)}</td>
      <td>
        <div className={s.decay} aria-label={`${factor.label} IC 衰减`}>
          {factor.decay.map((point) => (
            <span key={point.horizon} className={point.ic >= 0 ? s.decayPositive : s.decayNegative} title={`${point.horizon} 周期 IC ${signed(point.ic)}`}>
              <i style={{ height: `${Math.max(3, Math.min(22, Math.abs(point.ic) * 100))}px` }} />
              <small>{point.horizon}</small>
            </span>
          ))}
        </div>
      </td>
    </tr>
  )
}

function ErrorExplanation({
  title,
  cause,
  impact,
  action,
  tone = 'error',
}: {
  title: string
  cause: string
  impact: string
  action: string
  tone?: 'error' | 'warning'
}) {
  return (
    <div className={s.errorExplanation} data-tone={tone} role="alert">
      <AlertTriangle size={18} />
      <div>
        <strong>{title}</strong>
        <dl>
          <div><dt>原因</dt><dd>{cause}</dd></div>
          <div><dt>影响</dt><dd>{impact}</dd></div>
          <div><dt>处理</dt><dd>{action}</dd></div>
        </dl>
      </div>
    </div>
  )
}

export default function FactorResearchPage() {
  const [form, setForm] = useState<ResearchForm>({
    market: 'a_shares', symbol: '600519', interval: '1d', limit: 500, horizon: 5, transaction_cost_bps: 10,
  })
  const [researchTemplate, setResearchTemplate] = useState<ResearchTemplateKey>('swing')
  const [lastRequest, setLastRequest] = useState<ResearchForm | null>(null)
  const [result, setResult] = useState<FactorResearchResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [aiReview, setAiReview] = useState<FactorAiReviewResp | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState('')
  const [viewMode, setViewMode] = useState<'current' | 'history'>('current')
  const [historyRuns, setHistoryRuns] = useState<ResearchRun[]>([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyCursor, setHistoryCursor] = useState<string | null>(null)
  const [historySymbol, setHistorySymbol] = useState('')
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [openingRunId, setOpeningRunId] = useState('')
  const [comparison, setComparison] = useState<{ run: ResearchRun; result: FactorResearchResp } | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonError, setComparisonError] = useState('')
  const [researchGoal, setResearchGoal] = useState<ResearchGoalKey>('robust')
  const [showFirstGuide, setShowFirstGuide] = useState(
    () => typeof localStorage === 'undefined' || localStorage.getItem(FIRST_READ_GUIDE_KEY) !== 'true',
  )
  const researchStartedAt = useRef<number | null>(null)
  const researchCompleted = useRef(false)
  const initialRunId = useMemo(
    () => new URLSearchParams(window.location.search).get('run_id'),
    [],
  )

  useEffect(() => {
    if (initialRunId) void restoreRun(initialRunId)
  }, [initialRunId])

  useEffect(() => {
    const markAbandoned = () => {
      if (researchStartedAt.current === null || researchCompleted.current) return
      recordUsabilityEvent({
        name: 'research_abandoned',
        step: 'statistical_research',
        duration_ms: Date.now() - researchStartedAt.current,
      })
    }
    window.addEventListener('beforeunload', markAbandoned)
    return () => {
      window.removeEventListener('beforeunload', markAbandoned)
      markAbandoned()
    }
  }, [])

  function replaceRunId(runId: string | undefined) {
    const url = new URL(window.location.href)
    if (runId) url.searchParams.set('run_id', runId)
    else url.searchParams.delete('run_id')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }

  function applyTemplate(value: string) {
    const next = value as ResearchTemplateKey
    setResearchTemplate(next)
    if (next === 'custom') return
    setForm((current) => ({ ...current, ...RESEARCH_TEMPLATES[next].values }))
  }

  function applyResearchGoal(value: ResearchGoalKey) {
    setResearchGoal(value)
    setResearchTemplate('custom')
    setForm((current) => ({ ...current, ...RESEARCH_GOALS[value].values }))
  }

  function dismissFirstGuide() {
    setShowFirstGuide(false)
    if (typeof localStorage !== 'undefined') localStorage.setItem(FIRST_READ_GUIDE_KEY, 'true')
  }

  function updateAdvancedForm(patch: Partial<ResearchForm>) {
    setResearchTemplate('custom')
    setForm((current) => ({ ...current, ...patch }))
  }

  async function loadHistory(reset = true) {
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const response = await api.factorResearchRuns(
        historySymbol,
        20,
        reset ? undefined : historyCursor ?? undefined,
      )
      setHistoryRuns((current) => reset ? response.runs : [...current, ...response.runs])
      setHistoryTotal(response.total)
      setHistoryCursor(response.next_cursor)
      setHistoryLoaded(true)
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : '读取因子研究历史失败')
    } finally {
      setHistoryLoading(false)
    }
  }

  async function compareWithPrevious() {
    if (!result?.run_id) {
      setComparisonError('当前研究尚未保存，无法与历史记录比较')
      return
    }
    setComparisonLoading(true)
    setComparisonError('')
    try {
      const history = await api.factorResearchRuns(result.symbol, 20)
      const previous = history.runs.find((run) => run.id !== result.run_id)
      if (!previous) throw new Error('当前标的还没有上一条可比较的因子研究记录')
      const detail = await api.factorResearchRun(previous.id)
      if (!detail.result) throw new Error('上一条记录缺少可比较的统计结果')
      setComparison({ run: detail.run, result: detail.result })
    } catch (reason) {
      setComparison(null)
      setComparisonError(reason instanceof Error ? reason.message : '历史研究比较失败')
    } finally {
      setComparisonLoading(false)
    }
  }

  function changeView(value: string) {
    const next = value === 'history' ? 'history' : 'current'
    setViewMode(next)
    if (next === 'history' && !historyLoaded) void loadHistory(true)
  }

  async function restoreRun(runId: string) {
    setOpeningRunId(runId)
    setError('')
    setAiError('')
    try {
      const response = await api.factorResearchRun(runId)
      if (!response.result) throw new Error('该记录没有可恢复的因子统计结果')
      const input = asRecord(response.run.input.factor_research)
      const restoredForm: ResearchForm = {
        market: String(input.market ?? response.run.market),
        symbol: String(input.symbol ?? response.run.symbol),
        interval: String(input.interval ?? response.run.timeframe),
        limit: Number(input.limit ?? 500),
        horizon: Number(input.horizon ?? 5),
        transaction_cost_bps: Number(input.transaction_cost_bps ?? 10),
      }
      setForm(restoredForm)
      setResearchTemplate(inferResearchTemplate(restoredForm))
      setLastRequest(restoredForm)
      setResult(response.result)
      setAiReview(response.ai_review)
      setComparison(null)
      setComparisonError('')
      if (response.run.status === 'partial' && response.run.error) setAiError(response.run.error)
      setViewMode('current')
      replaceRunId(runId)
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : '恢复因子研究记录失败')
    } finally {
      setOpeningRunId('')
    }
  }

  async function analyze(event: React.FormEvent) {
    event.preventDefault()
    if (!form.symbol.trim()) return
    setLoading(true)
    setError('')
    setAiReview(null)
    setAiError('')
    setComparison(null)
    setComparisonError('')
    researchStartedAt.current = Date.now()
    researchCompleted.current = false
    recordUsabilityEvent({ name: 'research_started', step: 'setup' })
    try {
      const request = { ...form, symbol: form.symbol.trim().toUpperCase() }
      const response = await api.factorResearch(request)
      if (!response.ok) throw new Error(response.error || '因子验证失败')
      setResult(response)
      setLastRequest(request)
      setHistoryLoaded(false)
      replaceRunId(response.run_id)
      researchCompleted.current = true
      recordUsabilityEvent({
        name: 'research_completed',
        step: 'result_reading',
        duration_ms: Date.now() - researchStartedAt.current,
      })
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '因子验证失败'
      setError(message)
      researchCompleted.current = true
      recordUsabilityEvent({
        name: 'research_error',
        step: 'statistical_research',
        duration_ms: researchStartedAt.current === null ? undefined : Date.now() - researchStartedAt.current,
        error_type: classifyResearchError(message),
      })
    } finally {
      setLoading(false)
    }
  }

  async function runAiReview() {
    if (!result || !lastRequest) return
    setAiLoading(true)
    setAiError('')
    try {
      const response = await api.factorAiReview({
        ...lastRequest,
        review_focus: '稳健性、过拟合、市场状态依赖与下一步实验',
        run_id: result.run_id,
      })
      if (!response.ok || !response.review) throw new Error(response.error || 'AI 科研复核失败')
      setAiReview(response)
      setHistoryLoaded(false)
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'AI 科研复核失败'
      setAiError(message)
      recordUsabilityEvent({
        name: 'research_error',
        step: 'ai_review',
        error_type: 'ai_provider',
      })
    } finally {
      setAiLoading(false)
    }
  }

  const signal = result?.current_signal
  const SignalIcon = signal ? LEVEL_ICON[signal.level] : Activity
  const selectedNames = result?.summary.selected_factors
    .map((key) => result.factors.find((factor) => factor.key === key)?.label || key)
    .join(' + ') || '—'
  const multifactorMethod = result?.methods.find((method) => method.key === 'multifactor')
  const bestMethod = result?.methods.find((method) => method.key === result.summary.best_method)
    ?? result?.methods[0]
  const conclusion = result ? researchConclusion(result) : null
  const summaryEvidence = result ? [
    `${result.summary.usable_factors}/${result.factors.length} 个因子通过样本外规则，训练期组合为 ${selectedNames}`,
    bestMethod
      ? `${bestMethod.label}成本后收益 ${pct(bestMethod.total_return)}，夏普 ${bestMethod.sharpe.toFixed(2)}`
      : '没有量化方法通过当前统计口径',
    `${result.summary.test_rows} 根样本外数据，数据质量${result.quality.status === 'ok' ? '通过' : '需要复核'}`,
  ] : []
  const summaryRisks = result ? [
    `当前回撤信号为“${result.current_signal.label}”，标的回撤 ${pct(result.current_signal.drawdown)}`,
    multifactorMethod
      ? `组合最大回撤 ${pct(multifactorMethod.max_drawdown)}，95% CVaR ${pct(multifactorMethod.cvar_95, 2)}`
      : '组合风险指标尚不完整',
    aiReview?.review
      ? `AI 复核为“${aiReview.review.verdict}”，过拟合风险${aiReview.review.overfitting_risk.level}`
      : aiError
        ? 'AI 复核未完成，统计结果已保留，过拟合风险仍需复核'
        : '尚未进行 AI 复核，过拟合与市场状态依赖仍待检查',
  ] : []
  const invalidationConditions = result ? [
    `入选因子不再满足：${result.methodology.usable_rule}`,
    '更换市场、研究周期或成本假设后，当前结论必须重新验证',
    result.methodology.warning,
  ] : []
  const templateDescription = researchTemplate === 'custom'
    ? `${INTERVALS.find((item) => item.value === form.interval)?.label ?? form.interval} · 未来 ${form.horizon} 周期 · ${form.limit} 根`
    : RESEARCH_TEMPLATES[researchTemplate].description
  const comparisonBestMethod = comparison?.result.methods.find(
    (method) => method.key === comparison.result.summary.best_method,
  ) ?? comparison?.result.methods[0]
  const comparisonFactorRows = comparison && result ? Array.from(new Set([
    ...result.summary.selected_factors,
    ...comparison.result.summary.selected_factors,
  ])).map((key) => {
    const current = result.factors.find((factor) => factor.key === key)
    const previous = comparison.result.factors.find((factor) => factor.key === key)
    return {
      key,
      label: current?.label ?? previous?.label ?? key,
      currentStatus: current?.status,
      previousStatus: previous?.status,
      currentIc: current?.test_ic,
      previousIc: previous?.test_ic,
    }
  }) : []

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="研究 / 因子验证"
        title="因子有效性与回撤验证"
        description="训练期锁定 · 样本外检验 · 成本后回测"
        metrics={result ? [
          { label: '可用因子', value: result.summary.usable_factors },
          { label: '候选因子', value: result.factors.length },
          { label: '样本外区间', value: result.summary.test_rows },
        ] : []}
      />

      <div className={s.viewBar}>
        <SegmentedControl value={viewMode} onChange={changeView} options={VIEW_OPTIONS} size="sm" />
        {viewMode === 'current' && result?.saved && result.run_id ? (
          <div className={s.savedState} title={result.run_id}>
            <Database size={15} />
            <span>研究记录已保存</span>
            <small>{formatRunTime(result.saved_at)} · {result.run_id.slice(0, 10)}</small>
          </div>
        ) : viewMode === 'current' && result?.saved === false ? (
          <div className={s.unsavedState}><AlertTriangle size={15} /><span>结果未保存：{result.persistence_error || '存储不可用'}</span></div>
        ) : null}
      </div>

      {viewMode === 'current' && showFirstGuide && (
        <aside className={s.firstGuide} aria-label="第一次阅读顺序">
          <div className={s.guideLead}>
            <BookOpen size={20} />
            <div><span>FIRST RESEARCH / 约 3 分钟</span><strong>第一次先按这个顺序阅读</strong></div>
          </div>
          <ol>
            <li><b>1</b><span><strong>选模板并运行</strong><small>先保留默认参数，避免一开始调太多变量。</small></span></li>
            <li><b>2</b><span><strong>先看结论与风险</strong><small>确认是否值得继续研究，以及何时失效。</small></span></li>
            <li><b>3</b><span><strong>再展开专业详情</strong><small>需要复核时再读 IC、CVaR 与方法对比。</small></span></li>
          </ol>
          <button type="button" onClick={dismissFirstGuide} aria-label="永久关闭首次阅读引导"><X size={17} /></button>
        </aside>
      )}

      {viewMode === 'current' && result?.saved === false && (
        <ErrorExplanation
          title="统计结果未保存"
          cause={result.persistence_error || '研究存储暂时不可用'}
          impact="当前页面仍可阅读本次统计，但刷新或关闭页面后可能无法恢复。"
          action="先保留当前页面，检查数据库写入状态后重新运行并确认出现“研究记录已保存”。"
          tone="warning"
        />
      )}

      {viewMode === 'history' ? (
        <section className={s.historyPanel} aria-label="因子研究历史记录">
          <header className={s.historyHead}>
            <div>
              <span>RESEARCH ARCHIVE</span>
              <h2>因子研究历史</h2>
              <p>恢复当时的参数、统计结果和最近一次 AI 科研复核。</p>
            </div>
            <div className={s.historyTools}>
              <Input
                variant="mono"
                value={historySymbol}
                onChange={(event) => setHistorySymbol(event.target.value)}
                placeholder="按标的筛选"
              />
              <Button type="button" variant="secondary" size="sm" loading={historyLoading} icon={<Search size={15} />} onClick={() => void loadHistory(true)}>
                筛选
              </Button>
              <Button type="button" variant="ghost" size="sm" icon={<RefreshCw size={15} />} onClick={() => void loadHistory(true)} aria-label="刷新历史记录" />
            </div>
          </header>

          {historyError && <ErrorExplanation title="历史记录读取失败" cause={historyError} impact="当前研究仍可继续，但暂时不能恢复或比较历史结果。" action="重新筛选或刷新；若持续失败，检查 API 与研究数据库。" />}

          {!historyLoading && historyLoaded && historyRuns.length === 0 ? (
            <EmptyState title="还没有因子研究记录" desc="切换到当前研究并运行一次验证，系统会自动保存结果。" icon={<History size={30} />} />
          ) : (
            <div className={s.historyList}>
              {historyRuns.map((run) => {
                const factorSummary = asRecord(run.summary.factor_research)
                const aiSummary = asRecord(run.summary.factor_ai_review)
                const selected = Array.isArray(factorSummary.selected_factors) ? factorSummary.selected_factors : []
                const drawdown = typeof factorSummary.drawdown === 'number' ? pct(factorSummary.drawdown) : '—'
                const aiState = aiSummary.ok === true ? 'AI 已复核' : aiSummary.ok === false ? 'AI 未完成' : '尚未复核'
                return (
                  <button
                    type="button"
                    className={s.historyCard}
                    key={run.id}
                    onClick={() => void restoreRun(run.id)}
                    disabled={openingRunId === run.id}
                  >
                    <div className={s.historyIdentity}>
                      <span>{marketLabel(run.market)} · {run.timeframe}</span>
                      <strong>{run.symbol}</strong>
                      <small>{formatRunTime(run.updated_at)}</small>
                    </div>
                    <div className={s.historyMetrics}>
                      <span><small>入选因子</small><b>{selected.length}</b></span>
                      <span><small>当前回撤</small><b>{drawdown}</b></span>
                      <span><small>最佳方法</small><b>{String(factorSummary.best_method || '—')}</b></span>
                    </div>
                    <div className={s.historyOutcome}>
                      <span data-status={run.status}>{RUN_STATUS_LABEL[run.status] || run.status}</span>
                      <small>{aiState}</small>
                    </div>
                    <div className={s.historyOpen}>
                      <span>{openingRunId === run.id ? '恢复中' : '打开结果'}</span>
                      <ArrowRight size={17} />
                    </div>
                  </button>
                )
              })}
            </div>
          )}

          <footer className={s.historyFooter}>
            <span>共 {historyTotal} 条因子研究记录</span>
            {historyCursor && (
              <Button type="button" variant="secondary" size="sm" loading={historyLoading} onClick={() => void loadHistory(false)}>
                加载更多
              </Button>
            )}
          </footer>
        </section>
      ) : (
        <>
      <form className={s.toolbar} onSubmit={analyze}>
        <div className={s.goalTemplates} aria-label="研究目的模板">
          <div><span>研究目的</span><small>选择目的会给出一组可复现参数，仍可在高级参数中调整。</small></div>
          <div>
            {(Object.entries(RESEARCH_GOALS) as Array<[ResearchGoalKey, typeof RESEARCH_GOALS[ResearchGoalKey]]>).map(([key, goal]) => (
              <button type="button" key={key} data-active={researchGoal === key} onClick={() => applyResearchGoal(key)}>
                <strong>{goal.label}</strong><span>{goal.description}</span>
              </button>
            ))}
          </div>
        </div>
        <div className={s.researchSetup}>
          <label><span>市场</span><Select value={form.market} options={MARKETS} onChange={(event) => setForm({ ...form, market: event.target.value })} /></label>
          <label><span>标的</span><Input variant="mono" value={form.symbol} onChange={(event) => setForm({ ...form, symbol: event.target.value })} placeholder="600519 / AAPL" /></label>
          <div className={s.templateField}>
            <span>研究周期</span>
            <SegmentedControl value={researchTemplate} onChange={applyTemplate} options={TEMPLATE_OPTIONS} size="sm" fullWidth />
            <small>{templateDescription}</small>
          </div>
          <Button type="submit" variant="primary" loading={loading} icon={<Play size={16} />}>运行研究</Button>
        </div>
        <details className={s.advancedParams}>
          <summary><span>高级参数</span><small>{form.interval} · {form.horizon} 周期 · {form.transaction_cost_bps} bp</small><ChevronDown size={16} /></summary>
          <div className={s.advancedGrid}>
            <label><span>K 线周期</span><Select value={form.interval} options={INTERVALS} onChange={(event) => updateAdvancedForm({ interval: event.target.value })} /></label>
            <label><span>预测窗口</span><Select value={String(form.horizon)} options={HORIZONS} onChange={(event) => updateAdvancedForm({ horizon: Number(event.target.value) })} /></label>
            <label><span>历史长度</span><Input type="number" min={120} max={5000} step={20} value={form.limit} suffix="根" onChange={(event) => updateAdvancedForm({ limit: Number(event.target.value) })} /></label>
            <label><span>单边成本</span><Input type="number" min={0} max={200} value={form.transaction_cost_bps} suffix="bp" onChange={(event) => updateAdvancedForm({ transaction_cost_bps: Number(event.target.value) })} /></label>
          </div>
        </details>
      </form>

      <details className={s.exampleReports}>
        <summary><BookOpen size={17} /><span>先看示例报告</span><small>正常、风险退出、数据不足与 AI 失败如何阅读</small><ChevronDown size={16} /></summary>
        <div>
          {EXAMPLE_REPORTS.map((example) => (
            <article key={example.label} data-tone={example.tone}>
              <span>{example.label}</span><strong>{example.title}</strong><p>{example.detail}</p>
            </article>
          ))}
        </div>
      </details>

      {error && <ErrorExplanation title="统计研究未完成" cause={error} impact="本次没有生成新统计结果，已保存的历史记录不受影响。" action="检查标的、市场与数据源后重新运行；若持续失败，前往运行故障页查看。" />}

      {!result ? (
        <EmptyState
          title="选择标的并验证因子"
          desc="系统将读取真实历史 K 线，比较六类因子与六种量化方法，并给出当前回撤动作。"
          icon={<Waves size={30} />}
        />
      ) : (
        <div className={s.results}>
          <section className={s.beginnerSummary} data-tone={conclusion?.tone} aria-label="新手研究摘要">
            <div className={s.summaryVerdict}>
              <span>RESEARCH READOUT / 先看结论</span>
              <h2>{conclusion?.title}</h2>
              <p>{conclusion?.description}</p>
              <small>研究判断，不构成交易指令</small>
            </div>
            <div className={s.summaryColumns}>
              <div>
                <h3><CheckCircle2 size={16} />为什么这样判断</h3>
                <ul>{summaryEvidence.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
              <div>
                <h3><AlertTriangle size={16} />需要注意的风险</h3>
                <ul>{summaryRisks.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
              <div>
                <h3><ShieldAlert size={16} />结论何时失效</h3>
                <ul>{invalidationConditions.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            </div>
            <div className={s.nextActions}>
              <div><span>NEXT ACTION</span><strong>继续验证，而不是直接交易</strong></div>
              <div className={s.actionButtons}>
                <button type="button" disabled={comparisonLoading} onClick={() => void compareWithPrevious()}><RefreshCw size={16} /><span>{comparisonLoading ? '比较中' : '与上次对比'}</span></button>
                <button type="button" onClick={() => changeView('history')}><History size={16} /><span>查看历史</span></button>
                <a href={`/alerts?action=create&type=signal_created&symbol=${encodeURIComponent(result.symbol)}&market=${encodeURIComponent(result.market)}`}><Bell size={16} /><span>设置提醒</span></a>
                <a href={`/strategy-lab?action=create_experiment&symbol=${encodeURIComponent(result.symbol)}&market=${encodeURIComponent(result.market)}&timeframe=${encodeURIComponent(result.interval)}`}><FlaskConical size={16} /><span>策略实验</span></a>
              </div>
            </div>
          </section>

          {comparisonError && <ErrorExplanation title="历史比较未完成" cause={comparisonError} impact="当前研究结果保持可读，只缺少与上一条记录的差异。" action="先确认当前结果已保存且同标的存在更早记录，再重新比较。" tone="warning" />}

          {comparison && (
            <section className={s.comparisonPanel} aria-label="与上次因子研究对比">
              <header>
                <div><span>PREVIOUS RUN DELTA</span><h2>与上次研究对比</h2><p>{result.symbol} · 当前记录与 {formatRunTime(comparison.run.updated_at)} 的统计快照</p></div>
                <button type="button" onClick={() => setComparison(null)} aria-label="关闭研究对比"><X size={17} /></button>
              </header>
              <div className={s.comparisonMetrics}>
                <div><span>指标</span><strong>当前研究</strong><strong>上次研究</strong></div>
                <div><span>入选因子</span><b>{result.summary.selected_factors.length}</b><b>{comparison.result.summary.selected_factors.length}</b></div>
                <div><span>组合收益</span><b className={(bestMethod?.total_return ?? 0) >= 0 ? s.positive : s.negative}>{bestMethod ? pct(bestMethod.total_return) : '—'}</b><b className={(comparisonBestMethod?.total_return ?? 0) >= 0 ? s.positive : s.negative}>{comparisonBestMethod ? pct(comparisonBestMethod.total_return) : '—'}</b></div>
                <div><span>当前回撤</span><b>{pct(result.current_signal.strategy_drawdown)}</b><b>{pct(comparison.result.current_signal.strategy_drawdown)}</b></div>
                <div><span>最佳方法</span><b>{bestMethod?.label ?? '—'}</b><b>{comparisonBestMethod?.label ?? '—'}</b></div>
              </div>
              <div className={s.factorDelta}>
                <div className={s.factorDeltaHead}><span>入选因子变化</span><small>状态与样本外 IC</small></div>
                {comparisonFactorRows.map((row) => (
                  <div key={row.key}>
                    <strong>{row.label}</strong>
                    <span>{row.currentStatus ? STATUS_LABEL[row.currentStatus] : '未入选'} · {row.currentIc === undefined ? '—' : signed(row.currentIc)}</span>
                    <span>{row.previousStatus ? STATUS_LABEL[row.previousStatus] : '未入选'} · {row.previousIc === undefined ? '—' : signed(row.previousIc)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className={`${s.signalBand} ${s[`level_${signal?.level}`]}`} aria-label="当前回撤信号">
            <div className={s.signalIcon}><SignalIcon size={24} /></div>
            <div className={s.signalMain}>
              <span>当前回撤信号</span>
              <strong>{signal?.label}</strong>
              <p>{signal?.guidance}</p>
            </div>
            <dl className={s.signalMetrics}>
              <div><dt>标的当前回撤</dt><dd>{pct(signal?.drawdown ?? 0)}</dd></div>
              <div><dt>标的最大回撤</dt><dd>{pct(signal?.asset_peak_drawdown ?? 0)}</dd></div>
              <div><dt>组合当前回撤</dt><dd>{pct(signal?.strategy_drawdown ?? 0)}</dd></div>
              <div><dt>最新价</dt><dd>{result.latest.close.toLocaleString('zh-CN')}</dd></div>
            </dl>
          </section>

          <section id="factor-terms" className={s.termGlossary} aria-label="量化术语速查">
            <header><Info size={18} /><div><span>ON-DEMAND GLOSSARY</span><h2>量化术语速查</h2><p>只在需要时展开，不影响先读结论。</p></div></header>
            <div>
              {TERM_GLOSSARY.map((item) => (
                <details key={item.term}>
                  <summary><strong>{item.term}</strong><span>查看中文解释</span><ChevronDown size={15} /></summary>
                  <p>{item.explanation}</p>
                </details>
              ))}
            </div>
          </section>

          <details className={s.professionalDetails}>
            <summary>
              <BookOpen size={18} />
              <span><strong>专业统计与方法细节</strong><small>指标快照、样本外曲线、因子 IC、风险指标与方法对比</small></span>
              <ChevronDown className={s.detailsChevron} size={18} />
            </summary>
            <div className={s.professionalBody}>
          <section className={s.indicatorBand} aria-label="当前市场指标">
            <div className={s.indicatorLead}><ScanLine size={20} /><div><span>MARKET STATE</span><strong>当前指标快照</strong></div></div>
            <div className={s.indicatorGrid}>
              {result.indicators.map((indicator) => (
                <div key={indicator.key} className={s.indicator} data-state={indicator.state}>
                  <span>{indicator.label}</span>
                  <strong>{indicatorValue(indicator.key, indicator.value)}</strong>
                  <small>{indicator.interpretation}</small>
                </div>
              ))}
            </div>
          </section>

          <div className={s.primaryGrid}>
            <section className={s.panel}>
              <div className={s.sectionHead}>
                <div><span>01 / OUT-OF-SAMPLE PERFORMANCE</span><h2>样本外成本后净值</h2></div>
                <small>{result.symbol} · {result.interval} · {result.source}</small>
              </div>
              <EquityChart points={result.curve} />
            </section>

            <aside className={s.decisionRail}>
              <div className={s.sectionHead}><div><span>FACTOR SET</span><h2>训练期锁定组合</h2></div><Gauge size={19} /></div>
              <strong className={s.selectedFactors}>{selectedNames}</strong>
              <dl className={s.railStats}>
                <div><dt>训练 / 隔离 / 验证</dt><dd>{result.summary.train_rows} / {result.summary.purged_rows} / {result.summary.test_rows}</dd></div>
                <div><dt>未来收益窗口</dt><dd>{result.summary.horizon} 周期</dd></div>
                <div><dt>交易成本</dt><dd>{result.summary.transaction_cost_bps} bp</dd></div>
                <div><dt>数据质量</dt><dd>{result.quality.status === 'ok' ? '通过' : result.quality.status}</dd></div>
              </dl>
              <div className={s.methodNote}><Info size={16} /><span>组合因子与权重只由训练段确定；表格结论再按样本外数据独立检验。{result.methodology.usable_rule}</span></div>
            </aside>
          </div>

          <section className={s.panel}>
            <div className={s.sectionHead}><div><span>02 / UNDERWATER</span><h2>样本外回撤轨迹</h2></div><small>红：标的 · 青：多因子组合</small></div>
            <DrawdownChart points={result.curve} />
          </section>

          <section className={s.panel}>
            <div className={s.sectionHead}><div><span>03 / FACTOR SCREEN</span><h2>因子有效性与衰减</h2></div><small>方向由训练段确定 · 按样本外结果排序</small></div>
            <div className={s.tableScroll}>
              <table className={s.table}>
                <thead><tr><th>因子</th><th>结论</th><th className={s.numeric}>评分</th><th className={s.numeric}>样本外 IC</th><th className={s.numeric}>ICIR</th><th className={s.numeric}>滚动 IC 正值</th><th className={s.numeric}>命中率</th><th>IC 衰减 1/3/5/10/20</th></tr></thead>
                <tbody>{result.factors.map((factor) => <FactorRow key={factor.key} factor={factor} />)}</tbody>
              </table>
            </div>
          </section>

          {multifactorMethod && (
            <section className={s.riskBand} aria-label="多因子风险诊断">
              <div className={s.riskLead}><ShieldCheck size={20} /><div><span>MULTIFACTOR RISK</span><strong>多因子风险诊断</strong></div></div>
              <dl className={s.riskGrid}>
                <div><dt>Sortino</dt><dd>{multifactorMethod.sortino.toFixed(2)}</dd></div>
                <div><dt>Calmar</dt><dd>{multifactorMethod.calmar.toFixed(2)}</dd></div>
                <div><dt>95% VaR</dt><dd className={s.negative}>{pct(multifactorMethod.var_95, 2)}</dd></div>
                <div><dt>95% CVaR</dt><dd className={s.negative}>{pct(multifactorMethod.cvar_95, 2)}</dd></div>
                <div><dt>Ulcer Index</dt><dd>{pct(multifactorMethod.ulcer_index, 2)}</dd></div>
                <div><dt>最长回撤</dt><dd>{multifactorMethod.max_drawdown_duration} 周期</dd></div>
                <div><dt>利润因子</dt><dd>{multifactorMethod.profit_factor.toFixed(2)}</dd></div>
                <div><dt>平均持有</dt><dd>{multifactorMethod.average_holding_period.toFixed(1)} 周期</dd></div>
              </dl>
            </section>
          )}

          <section className={s.panel}>
            <div className={s.sectionHead}><div><span>04 / METHOD BENCHMARK</span><h2>量化方法对比</h2></div><small>仅样本外 · 信号延迟一周期 · 已计成本</small></div>
            <div className={s.tableScroll}>
              <table className={s.table}>
                <thead><tr><th>方法</th><th className={s.numeric}>总收益</th><th className={s.numeric}>年化</th><th className={s.numeric}>夏普</th><th className={s.numeric}>Sortino</th><th className={s.numeric}>Calmar</th><th className={s.numeric}>最大回撤</th><th className={s.numeric}>CVaR</th><th className={s.numeric}>胜率</th><th className={s.numeric}>交易</th><th className={s.numeric}>敞口</th></tr></thead>
                <tbody>{result.methods.map((method, index) => (
                  <tr key={method.key}>
                    <td><div className={s.methodName}><strong>{method.label}</strong>{index === 0 && <span>风险调整后最优</span>}</div></td>
                    <td className={`${s.numeric} ${method.total_return >= 0 ? s.positive : s.negative}`}>{pct(method.total_return)}</td>
                    <td className={s.numeric}>{pct(method.annual_return)}</td>
                    <td className={s.numeric}>{method.sharpe.toFixed(2)}</td>
                    <td className={s.numeric}>{method.sortino.toFixed(2)}</td>
                    <td className={s.numeric}>{method.calmar.toFixed(2)}</td>
                    <td className={`${s.numeric} ${s.negative}`}>{pct(method.max_drawdown)}</td>
                    <td className={`${s.numeric} ${s.negative}`}>{pct(method.cvar_95, 2)}</td>
                    <td className={s.numeric}>{pct(method.win_rate)}</td>
                    <td className={s.numeric}>{method.trades}</td>
                    <td className={s.numeric}>{pct(method.exposure)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>

            <footer className={s.methodology}>
              <Activity size={17} />
              <span>{result.methodology.split}；{result.methodology.execution}。</span>
              <strong>{result.methodology.warning}</strong>
            </footer>
            </div>
          </details>

          <section id="factor-ai-review" className={s.aiLab} aria-label="AI 科研复核">
            <header className={s.aiLabHead}>
              <div className={s.aiLabTitle}>
                <span className={s.aiLabIcon}><Microscope size={20} /></span>
                <div><span>05 / AI RESEARCH REVIEW</span><h2>AI 科研复核</h2><p>审阅统计证据、失效环境与后续实验，不改写因子状态</p></div>
              </div>
              <Button type="button" variant="secondary" loading={aiLoading} icon={<Sparkles size={16} />} onClick={() => void runAiReview()}>
                {aiLoading ? 'AI 深度复核中' : aiReview?.review ? '重新复核' : '启动 AI 复核'}
              </Button>
            </header>

            {aiError && (
              <ErrorExplanation
                title="统计研究已完成，AI 复核未完成"
                cause={aiError}
                impact="程序统计状态、回撤信号和已保存结果保持不变；仅缺少 AI 对过拟合与状态依赖的复核。"
                action="检查高级 AI 服务后点击“重新复核”，无需重新抓取行情或重跑统计。"
                tone="warning"
              />
            )}

            {!aiReview?.review ? (
              <div className={s.aiEmpty}>
                <div><ShieldCheck size={22} /><strong>统计结论保持锁定</strong></div>
                <p>AI 将读取本次结构化研究摘要，检查过拟合、样本量、IC 衰减、成本敏感度与市场状态依赖，并给出可证伪实验。</p>
              </div>
            ) : (
              <div className={s.aiResults}>
                <div className={s.aiVerdict}>
                  <div><span>复核结论</span><strong>{aiReview.review.verdict}</strong><p>{aiReview.review.summary}</p></div>
                  <dl>
                    <div><dt>AI 置信</dt><dd>{aiReview.review.confidence}%</dd></div>
                    <div><dt>统计对齐</dt><dd>{aiReview.review.statistical_alignment}</dd></div>
                    <div data-risk={aiReview.review.overfitting_risk.level}><dt>过拟合风险</dt><dd>{aiReview.review.overfitting_risk.level}</dd></div>
                    <div data-risk={aiReview.review.regime_risk.level}><dt>状态依赖</dt><dd>{aiReview.review.regime_risk.level}</dd></div>
                  </dl>
                </div>

                <div className={s.aiReviewGrid}>
                  {aiReview.review.factor_reviews.map((item) => (
                    <article key={item.factor_key}>
                      <header><div><span>{item.factor_key}</span><h3>{item.label}</h3></div><em className={s[item.statistical_status]}>{STATUS_LABEL[item.statistical_status]}</em></header>
                      <p>{item.assessment}</p>
                      <div className={s.aiEvidence}><span>证据</span>{item.evidence.map((line) => <small key={line}>{line}</small>)}</div>
                      {!!item.risks.length && <div className={s.aiRisks}><span>风险</span>{item.risks.map((line) => <small key={line}>{line}</small>)}</div>}
                      <footer><span>下一项检验</span><strong>{item.next_test}</strong></footer>
                    </article>
                  ))}
                </div>

                <div className={s.aiBottomGrid}>
                  <section>
                    <div className={s.aiSubhead}><span>EXPERIMENT QUEUE</span><h3>建议实验</h3></div>
                    {aiReview.review.experiments.map((item, index) => (
                      <div className={s.experiment} key={item.title}><b>{String(index + 1).padStart(2, '0')}</b><div><strong>{item.title}</strong><p>{item.design}</p><small>通过标准：{item.success_criteria}</small></div></div>
                    ))}
                  </section>
                  <section>
                    <div className={s.aiSubhead}><span>UNCERTAINTY REGISTER</span><h3>未知与限制</h3></div>
                    <ul>{aiReview.review.uncertainties.map((item) => <li key={item}>{item}</li>)}</ul>
                    <div className={s.aiMeta}>模型 {aiReview.meta?.model || '—'} · 输出 {aiReview.meta?.attempts ?? 1} 次 · 指纹 {aiReview.meta?.input_fingerprint || '—'}</div>
                  </section>
                </div>
              </div>
            )}
          </section>

        </div>
      )}
        </>
      )}
    </div>
  )
}

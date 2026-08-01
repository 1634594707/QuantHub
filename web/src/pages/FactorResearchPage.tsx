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
  Download,
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
  Star,
  StickyNote,
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
import { buildFactorResearchExport, type FactorResearchExportFormat } from '../lib/factorResearchExport'
import { CrossSectionResearchPanel } from './CrossSectionResearchPanel'
import { FactorConfirmationPanel } from './FactorConfirmationPanel'
import { FactorEvidenceWorkbench } from './FactorEvidenceWorkbench'
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

const WALK_FORWARD_MODES = [
  { value: 'expanding', label: '扩展窗口' },
  { value: 'rolling', label: '滚动窗口' },
]

const EXPORT_FORMATS = [
  { value: 'json', label: 'JSON 快照' },
  { value: 'csv', label: 'CSV 因子表' },
  { value: 'md', label: 'Markdown 报告' },
]

const VIEW_OPTIONS = [
  { value: 'current', label: '当前研究' },
  { value: 'cross_section', label: '横截面' },
  { value: 'governance', label: '研究治理' },
  { value: 'history', label: '历史记录' },
]

const RUN_STATUS_LABEL: Record<string, string> = {
  queued: '排队中',
  succeeded: '已完成',
  partial: '统计完成 / AI 未完成',
  failed: '失败',
  running: '运行中',
  draft: '准备中',
  cancelled: '已取消',
  timeout: '超时',
}

const HISTORY_MARKETS = [{ value: '', label: '全部市场' }, ...MARKETS]
const HISTORY_INTERVALS = [{ value: '', label: '全部周期' }, ...INTERVALS]
const HISTORY_STATUSES = [
  { value: '', label: '全部状态' },
  ...Object.entries(RUN_STATUS_LABEL).map(([value, label]) => ({ value, label })),
]
const HISTORY_WALK_FORWARD_MODES = [
  { value: '', label: '全部验证模式' },
  ...WALK_FORWARD_MODES,
]

type ResearchForm = {
  market: string
  symbol: string
  interval: string
  limit: number
  horizon: number
  transaction_cost_bps: number
  start_date?: string
  end_date?: string
  walk_forward_mode: 'expanding' | 'rolling'
  walk_forward_folds: number
}

type HistoryFilters = {
  symbol: string
  market: string
  interval: string
  status: string
  favorite_only: boolean
  archived_only: boolean
  tag: string
  created_from: string
  created_to: string
  research_limit: string
  horizon: string
  transaction_cost_bps: string
  walk_forward_mode: '' | 'expanding' | 'rolling'
  walk_forward_folds: string
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
  if (
    result.summary.usable_factors === 0
    || result.summary.multifactor_constructed === false
    || !method
    || method.total_return <= 0
  ) {
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
    description: '保留当前因子组合，优先完成滚动样本外和成本压力测试。',
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

function EquityChart({ points, showMultifactor = true }: { points: FactorCurvePoint[]; showMultifactor?: boolean }) {
  const width = 900
  const height = 240
  const domain = useMemo(() => {
    const values = points.flatMap((point) => showMultifactor
      ? [Number(point.asset), Number(point.multifactor)]
      : [Number(point.asset)]).filter(Number.isFinite)
    return { min: Math.min(...values), max: Math.max(...values) }
  }, [points, showMultifactor])
  const asset = useMemo(() => buildPath(points, 'asset', width, height, domain), [domain, points])
  const multifactor = useMemo(() => buildPath(points, 'multifactor', width, height, domain), [domain, points])
  const start = points[0]?.t?.slice(0, 10) || '—'
  const end = points[points.length - 1]?.t?.slice(0, 10) || '—'
  return (
    <div className={s.chartWrap}>
      <div className={s.legend}>
        <span><i className={s.assetDot} />标的净值</span>
        {showMultifactor && <span><i className={s.factorDot} />多因子净值</span>}
      </div>
      <svg className={s.chart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="标的与多因子净值曲线">
        {[0, 1, 2, 3, 4].map((line) => (
          <line key={line} x1="0" x2={width} y1={line * height / 4} y2={line * height / 4} className={s.gridLine} />
        ))}
        <path d={asset} className={s.assetLine} />
        {showMultifactor && <path d={multifactor} className={s.factorLine} />}
      </svg>
      <div className={s.axis}><span>{start}</span><span>{end}</span></div>
    </div>
  )
}

function DrawdownChart({ points, showMultifactor = true }: { points: FactorCurvePoint[]; showMultifactor?: boolean }) {
  const width = 900
  const height = 150
  const domain = useMemo(() => {
    const values = points.flatMap((point) => showMultifactor
      ? [Number(point.asset_drawdown), Number(point.strategy_drawdown)]
      : [Number(point.asset_drawdown)]).filter(Number.isFinite)
    return { min: Math.min(...values), max: Math.max(...values) }
  }, [points, showMultifactor])
  const asset = useMemo(() => buildPath(points, 'asset_drawdown', width, height, domain), [domain, points])
  const multifactor = useMemo(() => buildPath(points, 'strategy_drawdown', width, height, domain), [domain, points])
  return (
    <svg className={s.drawdownChart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="标的与多因子回撤曲线">
      {[0, 1, 2, 3].map((line) => (
        <line key={line} x1="0" x2={width} y1={line * height / 3} y2={line * height / 3} className={s.gridLine} />
      ))}
      <path d={asset} className={s.drawdownAsset} />
      {showMultifactor && <path d={multifactor} className={s.drawdownFactor} />}
    </svg>
  )
}

function FactorRow({ factor }: { factor: FactorEvaluation }) {
  const adjustedPValue = factor.adjusted_p_value ?? factor.p_value
  return (
    <tr>
      <td>
        <div className={s.factorName}>
          <strong>{factor.label}{factor.selected && <em>组合权重 {(factor.weight * 100).toFixed(0)}%</em>}</strong>
          <span>{factor.category} · {factor.description}{factor.is_redundant_alias ? ` · 等价变体，归入 ${factor.canonical_factor_key}` : ''}</span>
        </div>
      </td>
      <td>
        <details className={s.statusEvidence}>
          <summary><span className={`${s.status} ${s[factor.status]}`}>{STATUS_LABEL[factor.status]}</span></summary>
          <div>
            <strong>计算规则</strong>
            <p>可用要求有效样本充足、多数窗口通过、窗口 IC 中位数至少 0.03、命中率至少 50%，且 Benjamini-Hochberg 校正显著性通过；样本不足或窗口 IC 中位数不大于 0 时淘汰，其余进入观察。</p>
            <dl>
              <div><dt>窗口通过</dt><dd>{factor.passed_windows ?? 0} / {factor.window_count ?? 0}</dd></div>
              <div><dt>IC 中位数</dt><dd>{signed(factor.test_ic)}</dd></div>
              <div><dt>命中率</dt><dd>{pct(factor.hit_rate)}</dd></div>
              <div><dt>校正显著性</dt><dd>{adjustedPValue.toFixed(4)}</dd></div>
            </dl>
          </div>
        </details>
      </td>
      <td className={s.numeric}>{factor.score.toFixed(1)}</td>
      <td className={`${s.numeric} ${factor.test_ic > 0 ? s.positive : s.negative}`}>{signed(factor.test_ic)}</td>
      <td
        className={`${s.numeric} ${factor.multi_window_consistent === true ? s.positive : s.negative}`}
        title={factor.window_count === undefined ? '旧记录没有多窗口验证结果' : `最差窗口 IC ${signed(factor.worst_window_ic ?? 0)}`}
      >{factor.window_count === undefined ? '—' : `${factor.passed_windows}/${factor.window_count}`}</td>
      <td
        className={`${s.numeric} ${factor.statistically_significant === true ? s.positive : s.negative}`}
        title={factor.adjusted_p_value === undefined ? '旧记录仅保存原始显著性' : 'Benjamini-Hochberg 校正结果'}
      >{adjustedPValue.toFixed(4)}</td>
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
    walk_forward_mode: 'expanding', walk_forward_folds: 3,
  })
  const [researchTemplate, setResearchTemplate] = useState<ResearchTemplateKey>('swing')
  const [lastRequest, setLastRequest] = useState<ResearchForm | null>(null)
  const [result, setResult] = useState<FactorResearchResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [aiReview, setAiReview] = useState<FactorAiReviewResp | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState('')
  const [viewMode, setViewMode] = useState<'current' | 'cross_section' | 'governance' | 'history'>('current')
  const [historyRuns, setHistoryRuns] = useState<ResearchRun[]>([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyCursor, setHistoryCursor] = useState<string | null>(null)
  const [historyFilters, setHistoryFilters] = useState<HistoryFilters>({
    symbol: '', market: '', interval: '', status: '', favorite_only: false, archived_only: false, tag: '', created_from: '', created_to: '',
    research_limit: '', horizon: '', transaction_cost_bps: '', walk_forward_mode: '', walk_forward_folds: '',
  })
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [openingRunId, setOpeningRunId] = useState('')
  const [metadataSavingRunId, setMetadataSavingRunId] = useState('')
  const [editingNoteRunId, setEditingNoteRunId] = useState('')
  const [noteDraft, setNoteDraft] = useState('')
  const [tagDraft, setTagDraft] = useState('')
  const [selectedHistoryRunIds, setSelectedHistoryRunIds] = useState<string[]>([])
  const [bulkTagDraft, setBulkTagDraft] = useState('')
  const [bulkSaving, setBulkSaving] = useState(false)
  const [comparison, setComparison] = useState<{ run: ResearchRun; result: FactorResearchResp } | null>(null)
  const [comparisonRuns, setComparisonRuns] = useState<ResearchRun[]>([])
  const [comparisonRunId, setComparisonRunId] = useState('')
  const [showComparisonPicker, setShowComparisonPicker] = useState(false)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonError, setComparisonError] = useState('')
  const [exportFormat, setExportFormat] = useState<FactorResearchExportFormat>('json')
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
        {
          symbol: historyFilters.symbol,
          market: historyFilters.market || undefined,
          interval: historyFilters.interval || undefined,
          status: historyFilters.status || undefined,
          favorite: historyFilters.favorite_only || undefined,
          archived: historyFilters.archived_only || undefined,
          tag: historyFilters.tag || undefined,
          created_from: historyFilters.created_from || undefined,
          created_to: historyFilters.created_to || undefined,
          research_limit: historyFilters.research_limit ? Number(historyFilters.research_limit) : undefined,
          horizon: historyFilters.horizon ? Number(historyFilters.horizon) : undefined,
          transaction_cost_bps: historyFilters.transaction_cost_bps ? Number(historyFilters.transaction_cost_bps) : undefined,
          walk_forward_mode: historyFilters.walk_forward_mode || undefined,
          walk_forward_folds: historyFilters.walk_forward_folds ? Number(historyFilters.walk_forward_folds) : undefined,
        },
        20,
        reset ? undefined : historyCursor ?? undefined,
      )
      setHistoryRuns((current) => reset ? response.runs : [...current, ...response.runs])
      setHistoryTotal(response.total)
      setHistoryCursor(response.next_cursor)
      if (reset) setSelectedHistoryRunIds([])
      setHistoryLoaded(true)
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : '读取因子研究历史失败')
    } finally {
      setHistoryLoading(false)
    }
  }

  function updateHistoryFilters(patch: Partial<HistoryFilters>) {
    setHistoryFilters((current) => ({ ...current, ...patch }))
  }

  function parseTags(value: string): string[] {
    return [...new Set(value.split(',').map((item) => item.trim()).filter(Boolean))]
  }

  function toggleHistorySelection(runId: string, selected: boolean) {
    setSelectedHistoryRunIds((current) => selected
      ? [...new Set([...current, runId])]
      : current.filter((item) => item !== runId))
  }

  async function updateHistoryMetadata(runId: string, patch: { favorite?: boolean; note?: string; tags?: string[] }) {
    setMetadataSavingRunId(runId)
    setHistoryError('')
    try {
      const response = await api.updateResearchRun(runId, patch)
      setHistoryRuns((current) => current.map((run) => run.id === runId ? response.run : run))
      if (patch.note !== undefined) setEditingNoteRunId('')
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : '保存研究记录信息失败')
    } finally {
      setMetadataSavingRunId('')
    }
  }

  async function updateSelectedHistoryRuns(patch: { tags?: string[]; archived?: boolean }) {
    if (!selectedHistoryRunIds.length) return
    setBulkSaving(true)
    setHistoryError('')
    try {
      const response = await api.updateResearchRunsBatch(selectedHistoryRunIds, patch)
      if (patch.archived !== undefined) {
        setHistoryRuns((current) => current.filter((run) => !selectedHistoryRunIds.includes(run.id)))
        setHistoryTotal((current) => Math.max(0, current - response.count))
      } else {
        const updated = new Map(response.runs.map((run) => [run.id, run]))
        setHistoryRuns((current) => current.map((run) => updated.get(run.id) ?? run))
      }
      setSelectedHistoryRunIds([])
      setBulkTagDraft('')
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : '批量更新研究记录失败')
    } finally {
      setBulkSaving(false)
    }
  }

  async function openComparisonPicker() {
    if (!result?.run_id) {
      setComparisonError('当前研究尚未保存，无法与历史记录比较')
      return
    }
    setComparisonLoading(true)
    setComparisonError('')
    try {
      const history = await api.factorResearchRuns({ symbol: result.symbol }, 50)
      const available = history.runs.filter((run) => run.id !== result.run_id)
      if (!available.length) throw new Error('当前标的还没有其他可比较的因子研究记录')
      setComparisonRuns(available)
      setComparisonRunId((current) => available.some((run) => run.id === current) ? current : available[0].id)
      setShowComparisonPicker(true)
    } catch (reason) {
      setComparisonError(reason instanceof Error ? reason.message : '历史研究比较失败')
    } finally {
      setComparisonLoading(false)
    }
  }

  async function compareWithSelectedRun() {
    if (!comparisonRunId) return
    setComparisonLoading(true)
    setComparisonError('')
    try {
      const detail = await api.factorResearchRun(comparisonRunId)
      if (!detail.result) throw new Error('所选记录缺少可比较的统计结果')
      setComparison({ run: detail.run, result: detail.result })
      setShowComparisonPicker(false)
    } catch (reason) {
      setComparison(null)
      setComparisonError(reason instanceof Error ? reason.message : '历史研究比较失败')
    } finally {
      setComparisonLoading(false)
    }
  }

  function downloadResult() {
    if (!result) return
    const artifact = buildFactorResearchExport(result, exportFormat)
    const url = URL.createObjectURL(new Blob([artifact.content], { type: artifact.mimeType }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = artifact.filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  }

  function changeView(value: string) {
    const next = value === 'history'
      ? 'history'
      : value === 'cross_section'
        ? 'cross_section'
        : value === 'governance' ? 'governance' : 'current'
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
        start_date: input.start_date ? String(input.start_date) : undefined,
        end_date: input.end_date ? String(input.end_date) : undefined,
        walk_forward_mode: input.walk_forward_mode === 'rolling' ? 'rolling' : 'expanding',
        walk_forward_folds: Number(input.walk_forward_folds ?? 3),
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
      const request = {
        ...form,
        symbol: form.symbol.trim().toUpperCase(),
        start_date: form.start_date || undefined,
        end_date: form.end_date || undefined,
      }
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
  const exploratoryKeys = result
    ? (result.summary.exploratory_candidates ?? result.summary.selected_factors)
    : []
  const selectedNames = result
    ? exploratoryKeys
      .map((key) => result.factors.find((factor) => factor.key === key)?.label || key)
      .join(' + ') || '未发现合格因子'
    : '未发现合格因子'
  const multifactorConstructed = result
    ? (result.summary.multifactor_constructed ?? exploratoryKeys.length > 0)
    : false
  const multifactorMethod = multifactorConstructed
    ? result?.methods.find((method) => method.key === 'multifactor')
    : undefined
  const bestMethod = result?.methods.find((method) => method.key === result.summary.best_method)
    ?? result?.methods[0]
  const conclusion = result ? researchConclusion(result) : null
  const summaryEvidence = result ? [
    `${result.summary.usable_factors}/${result.factors.length} 个因子通过样本外规则，${multifactorConstructed ? `探索组合为 ${selectedNames}` : '未发现合格因子，多因子组合未构建'}`,
    bestMethod
      ? `${bestMethod.label}成本后收益 ${pct(bestMethod.total_return)}，夏普 ${bestMethod.sharpe.toFixed(2)}${bestMethod.deflated_sharpe_ratio !== undefined ? `，DSR ${pct(bestMethod.deflated_sharpe_ratio)}` : ''}`
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
    `探索候选不再满足：${result.methodology.usable_rule}`,
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
    ...(result.summary.exploratory_candidates ?? result.summary.selected_factors),
    ...(comparison.result.summary.exploratory_candidates
      ?? comparison.result.summary.selected_factors),
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
          { label: '已检验因子', value: result.factors.length },
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

      {viewMode === 'current' && result && <FactorEvidenceWorkbench result={result} aiReview={aiReview} />}

      {viewMode === 'current' && result?.saved === false && (
        <ErrorExplanation
          title="统计结果未保存"
          cause={result.persistence_error || '研究存储暂时不可用'}
          impact="当前页面仍可阅读本次统计，但刷新或关闭页面后可能无法恢复。"
          action="先保留当前页面，检查数据库写入状态后重新运行并确认出现“研究记录已保存”。"
          tone="warning"
        />
      )}

      {viewMode === 'cross_section' ? (
        <CrossSectionResearchPanel />
      ) : viewMode === 'governance' ? (
        <FactorConfirmationPanel />
      ) : viewMode === 'history' ? (
        <section className={s.historyPanel} aria-label="因子研究历史记录">
          <header className={s.historyHead}>
            <div>
              <span>RESEARCH ARCHIVE</span>
              <h2>因子研究历史</h2>
              <p>恢复当时的参数、统计结果和最近一次 AI 科研复核。</p>
            </div>
            <div className={s.historyTools}>
              <Button type="button" variant="secondary" size="sm" loading={historyLoading} icon={<Search size={15} />} onClick={() => void loadHistory(true)}>
                应用筛选
              </Button>
              <Button type="button" variant="ghost" size="sm" icon={<RefreshCw size={15} />} onClick={() => void loadHistory(true)} aria-label="刷新历史记录" />
            </div>
          </header>

          <div className={s.historyFilters} aria-label="历史记录筛选条件">
            <label><span>标的</span><Input variant="mono" value={historyFilters.symbol} onChange={(event) => updateHistoryFilters({ symbol: event.target.value })} placeholder="600519 / AAPL" /></label>
            <label><span>市场</span><Select value={historyFilters.market} options={HISTORY_MARKETS} onChange={(event) => updateHistoryFilters({ market: event.target.value })} /></label>
            <label><span>周期</span><Select value={historyFilters.interval} options={HISTORY_INTERVALS} onChange={(event) => updateHistoryFilters({ interval: event.target.value })} /></label>
            <label><span>状态</span><Select value={historyFilters.status} options={HISTORY_STATUSES} onChange={(event) => updateHistoryFilters({ status: event.target.value })} /></label>
            <label className={s.historyFavoriteFilter}><input type="checkbox" checked={historyFilters.favorite_only} onChange={(event) => updateHistoryFilters({ favorite_only: event.target.checked })} /><span>仅显示收藏</span></label>
            <label className={s.historyFavoriteFilter}><input type="checkbox" checked={historyFilters.archived_only} onChange={(event) => updateHistoryFilters({ archived_only: event.target.checked })} /><span>查看归档</span></label>
            <label><span>标签</span><Input aria-label="标签" value={historyFilters.tag} placeholder="例如：待复验" onChange={(event) => updateHistoryFilters({ tag: event.target.value })} /></label>
            <label><span>创建日期起</span><Input type="date" value={historyFilters.created_from} max={historyFilters.created_to || undefined} onChange={(event) => updateHistoryFilters({ created_from: event.target.value })} /></label>
            <label><span>创建日期止</span><Input type="date" value={historyFilters.created_to} min={historyFilters.created_from || undefined} onChange={(event) => updateHistoryFilters({ created_to: event.target.value })} /></label>
            <label><span>历史长度</span><Input type="number" min={120} max={5000} value={historyFilters.research_limit} placeholder="全部" onChange={(event) => updateHistoryFilters({ research_limit: event.target.value })} /></label>
            <label><span>预测窗口</span><Input type="number" min={1} max={60} value={historyFilters.horizon} placeholder="全部" onChange={(event) => updateHistoryFilters({ horizon: event.target.value })} /></label>
            <label><span>单边成本</span><Input aria-label="单边成本" type="number" min={0} max={200} value={historyFilters.transaction_cost_bps} placeholder="全部" suffix="bp" onChange={(event) => updateHistoryFilters({ transaction_cost_bps: event.target.value })} /></label>
            <label><span>验证模式</span><Select value={historyFilters.walk_forward_mode} options={HISTORY_WALK_FORWARD_MODES} onChange={(event) => updateHistoryFilters({ walk_forward_mode: event.target.value as HistoryFilters['walk_forward_mode'] })} /></label>
            <label><span>验证窗口</span><Input type="number" min={1} max={10} value={historyFilters.walk_forward_folds} placeholder="全部" onChange={(event) => updateHistoryFilters({ walk_forward_folds: event.target.value })} /></label>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setHistoryFilters({
                symbol: '', market: '', interval: '', status: '', favorite_only: false, archived_only: false, tag: '', created_from: '', created_to: '',
                research_limit: '', horizon: '', transaction_cost_bps: '', walk_forward_mode: '', walk_forward_folds: '',
              })}
            >重置条件</Button>
          </div>

          {historyError && <ErrorExplanation title="历史记录读取失败" cause={historyError} impact="当前研究仍可继续，但暂时不能恢复或比较历史结果。" action="重新筛选或刷新；若持续失败，检查 API 与研究数据库。" />}

          {selectedHistoryRunIds.length > 0 && <div className={s.historyBatchActions} aria-label="批量管理研究记录">
            <strong>已选择 {selectedHistoryRunIds.length} 条</strong>
            <Input aria-label="批量标签" value={bulkTagDraft} placeholder="标签以逗号分隔" onChange={(event) => setBulkTagDraft(event.target.value)} />
            <Button type="button" size="sm" variant="secondary" loading={bulkSaving} disabled={!parseTags(bulkTagDraft).length} onClick={() => void updateSelectedHistoryRuns({ tags: parseTags(bulkTagDraft) })}>应用标签</Button>
            <Button type="button" size="sm" variant={historyFilters.archived_only ? 'secondary' : 'danger'} loading={bulkSaving} onClick={() => void updateSelectedHistoryRuns({ archived: !historyFilters.archived_only })}>{historyFilters.archived_only ? '恢复所选' : '归档所选'}</Button>
          </div>}

          {!historyLoading && historyLoaded && historyRuns.length === 0 ? (
            <EmptyState title="还没有因子研究记录" desc="切换到当前研究并运行一次验证，系统会自动保存结果。" icon={<History size={30} />} />
          ) : (
            <div className={s.historyList}>
              {historyRuns.map((run) => {
                const factorSummary = asRecord(run.summary.factor_research)
                const aiSummary = asRecord(run.summary.factor_ai_review)
                const selected = Array.isArray(factorSummary.exploratory_candidates)
                  ? factorSummary.exploratory_candidates
                  : Array.isArray(factorSummary.selected_factors) ? factorSummary.selected_factors : []
                const drawdown = typeof factorSummary.drawdown === 'number' ? pct(factorSummary.drawdown) : '—'
                const aiState = aiSummary.ok === true ? 'AI 已复核' : aiSummary.ok === false ? 'AI 未完成' : '尚未复核'
                const runTags = run.tags ?? []
                return (
                  <article className={s.historyCard} key={run.id}>
                    <button
                      type="button"
                      className={s.historyCardOpen}
                      onClick={() => void restoreRun(run.id)}
                      disabled={openingRunId === run.id}
                    >
                      <div className={s.historyIdentity}>
                        <span>{marketLabel(run.market)} · {run.timeframe}</span>
                        <strong>{run.symbol}</strong>
                        <small>{formatRunTime(run.updated_at)}</small>
                        {runTags.length > 0 && <span className={s.historyTags}>{runTags.map((tag) => <i key={tag}>{tag}</i>)}</span>}
                      </div>
                      <div className={s.historyMetrics}>
                        <span><small>探索候选</small><b>{selected.length}</b></span>
                        <span><small>当前回撤</small><b>{drawdown}</b></span>
                        <span><small>最佳方法</small><b>{String(factorSummary.best_method || '—')}</b></span>
                      </div>
                      <div className={s.historyOutcome}>
                        <span data-status={run.status}>{RUN_STATUS_LABEL[run.status] || run.status}</span>
                        <small>{aiState}</small>
                        {run.note && <small title={run.note}>{run.note}</small>}
                      </div>
                      <div className={s.historyOpen}>
                        <span>{openingRunId === run.id ? '恢复中' : '打开结果'}</span>
                        <ArrowRight size={17} />
                      </div>
                    </button>
                    <div className={s.historyRecordActions}>
                      <label className={s.historySelect}>
                        <input aria-label={`选择 ${run.symbol} 研究记录`} type="checkbox" checked={selectedHistoryRunIds.includes(run.id)} onChange={(event) => toggleHistorySelection(run.id, event.target.checked)} />
                      </label>
                      <button
                        type="button"
                        data-active={run.favorite}
                        aria-label={`${run.favorite ? '取消收藏' : '收藏'} ${run.symbol}`}
                        title={run.favorite ? '取消收藏' : '收藏研究记录'}
                        disabled={metadataSavingRunId === run.id}
                        onClick={() => void updateHistoryMetadata(run.id, { favorite: !run.favorite })}
                      ><Star size={17} fill={run.favorite ? 'currentColor' : 'none'} /></button>
                      <button
                        type="button"
                        aria-label={`编辑 ${run.symbol} 备注`}
                        title="编辑研究备注"
                        onClick={() => {
                          setEditingNoteRunId((current) => current === run.id ? '' : run.id)
                          setNoteDraft(run.note)
                          setTagDraft(runTags.join(', '))
                        }}
                      ><StickyNote size={17} /></button>
                    </div>
                    {editingNoteRunId === run.id && (
                      <div className={s.historyNoteEditor}>
                        <textarea aria-label={`${run.symbol} 研究备注`} value={noteDraft} maxLength={4000} rows={3} onChange={(event) => setNoteDraft(event.target.value)} />
                        <Input aria-label={`${run.symbol} 研究标签`} value={tagDraft} placeholder="标签以逗号分隔" onChange={(event) => setTagDraft(event.target.value)} />
                        <span>{noteDraft.length}/4000</span>
                        <Button type="button" size="sm" loading={metadataSavingRunId === run.id} disabled={noteDraft.trim() === run.note && parseTags(tagDraft).join(',') === runTags.join(',')} onClick={() => void updateHistoryMetadata(run.id, { note: noteDraft.trim(), tags: parseTags(tagDraft) })}>保存备注与标签</Button>
                      </div>
                    )}
                  </article>
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
          <summary><span>高级参数</span><small>{form.interval} · {form.horizon} 周期 · {form.walk_forward_mode === 'rolling' ? '滚动' : '扩展'} {form.walk_forward_folds} 窗口 · {form.transaction_cost_bps} bp</small><ChevronDown size={16} /></summary>
          <div className={s.advancedGrid}>
            <label><span>K 线周期</span><Select value={form.interval} options={INTERVALS} onChange={(event) => updateAdvancedForm({ interval: event.target.value })} /></label>
            <label><span>预测窗口</span><Select value={String(form.horizon)} options={HORIZONS} onChange={(event) => updateAdvancedForm({ horizon: Number(event.target.value) })} /></label>
            <label><span>历史长度</span><Input type="number" min={120} max={5000} step={20} value={form.limit} suffix="根" onChange={(event) => updateAdvancedForm({ limit: Number(event.target.value) })} /></label>
            <label><span>单边成本</span><Input type="number" min={0} max={200} value={form.transaction_cost_bps} suffix="bp" onChange={(event) => updateAdvancedForm({ transaction_cost_bps: Number(event.target.value) })} /></label>
            <label><span>开始日期</span><Input type="date" value={form.start_date ?? ''} max={form.end_date} onChange={(event) => updateAdvancedForm({ start_date: event.target.value || undefined })} /></label>
            <label><span>结束日期</span><Input type="date" value={form.end_date ?? ''} min={form.start_date} onChange={(event) => updateAdvancedForm({ end_date: event.target.value || undefined })} /></label>
            <label><span>验证模式</span><Select value={form.walk_forward_mode} options={WALK_FORWARD_MODES} onChange={(event) => updateAdvancedForm({ walk_forward_mode: event.target.value === 'rolling' ? 'rolling' : 'expanding' })} /></label>
            <label><span>验证窗口</span><Input type="number" min={1} max={10} value={form.walk_forward_folds} suffix="个" onChange={(event) => updateAdvancedForm({ walk_forward_folds: Number(event.target.value) })} /></label>
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
                <button type="button" disabled={comparisonLoading} onClick={() => void openComparisonPicker()}><RefreshCw size={16} /><span>{comparisonLoading ? '读取记录中' : '选择历史对比'}</span></button>
                <button type="button" onClick={() => changeView('history')}><History size={16} /><span>查看历史</span></button>
                {result.summary.best_factor
                  ? <a href={`/alerts?action=create&type=factor_status_changed&symbol=${encodeURIComponent(result.symbol)}&market=${encodeURIComponent(result.market)}&factor_key=${encodeURIComponent(result.summary.best_factor)}${result.run_id ? `&research_run_id=${encodeURIComponent(result.run_id)}` : ''}`}><Bell size={16} /><span>设置提醒</span></a>
                  : <button type="button" disabled title="当前研究没有可设置提醒的观察因子"><Bell size={16} /><span>设置提醒</span></button>}
                {multifactorConstructed
                  ? <a href={`/strategy-lab?action=create_experiment&symbol=${encodeURIComponent(result.symbol)}&market=${encodeURIComponent(result.market)}&timeframe=${encodeURIComponent(result.interval)}${result.run_id ? `&research_run_id=${encodeURIComponent(result.run_id)}` : ''}`}><FlaskConical size={16} /><span>策略实验</span></a>
                  : <button type="button" disabled title="没有因子通过统计门禁，不能创建策略实验"><FlaskConical size={16} /><span>策略实验</span></button>}
                <div className={s.exportControl}>
                  <Select value={exportFormat} options={EXPORT_FORMATS} selectSize="sm" aria-label="导出格式" onChange={(event) => setExportFormat(event.target.value as FactorResearchExportFormat)} />
                  <button type="button" onClick={downloadResult} title="下载研究结果"><Download size={16} /><span>导出</span></button>
                </div>
              </div>
              {showComparisonPicker && (
                <div className={s.comparisonPicker}>
                  <label><span>对比记录</span><Select value={comparisonRunId} options={comparisonRuns.map((run) => ({ value: run.id, label: `${formatRunTime(run.updated_at)} · ${run.id.slice(0, 10)}` }))} onChange={(event) => setComparisonRunId(event.target.value)} /></label>
                  <Button type="button" size="sm" loading={comparisonLoading} onClick={() => void compareWithSelectedRun()}>开始对比</Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setShowComparisonPicker(false)}>取消</Button>
                </div>
              )}
            </div>
          </section>

          {comparisonError && <ErrorExplanation title="历史比较未完成" cause={comparisonError} impact="当前研究结果保持可读，只缺少与所选记录的差异。" action="先确认当前结果已保存且同标的存在其他记录，再重新比较。" tone="warning" />}

          {comparison && (
            <section className={s.comparisonPanel} aria-label="历史因子研究对比">
              <header>
                <div><span>SELECTED RUN DELTA</span><h2>历史研究对比</h2><p>{result.symbol} · 当前记录与 {formatRunTime(comparison.run.updated_at)} · {comparison.run.id.slice(0, 10)}</p></div>
                <button type="button" onClick={() => setComparison(null)} aria-label="关闭研究对比"><X size={17} /></button>
              </header>
              <div className={s.comparisonMetrics}>
                <div><span>指标</span><strong>当前研究</strong><strong>所选研究</strong></div>
                <div><span>探索候选</span><b>{exploratoryKeys.length}</b><b>{(comparison.result.summary.exploratory_candidates ?? comparison.result.summary.selected_factors).length}</b></div>
                <div><span>组合收益</span><b className={(bestMethod?.total_return ?? 0) >= 0 ? s.positive : s.negative}>{bestMethod ? pct(bestMethod.total_return) : '—'}</b><b className={(comparisonBestMethod?.total_return ?? 0) >= 0 ? s.positive : s.negative}>{comparisonBestMethod ? pct(comparisonBestMethod.total_return) : '—'}</b></div>
                <div><span>当前回撤</span><b>{pct(result.current_signal.strategy_drawdown)}</b><b>{pct(comparison.result.current_signal.strategy_drawdown)}</b></div>
                <div><span>最佳方法</span><b>{bestMethod?.label ?? '—'}</b><b>{comparisonBestMethod?.label ?? '—'}</b></div>
              </div>
              <div className={s.factorDelta}>
                <div className={s.factorDeltaHead}><span>探索候选变化</span><small>状态与样本外 IC</small></div>
                {comparisonFactorRows.map((row) => (
                  <div key={row.key}>
                    <strong>{row.label}</strong>
                    <span>{row.currentStatus ? STATUS_LABEL[row.currentStatus] : '非探索候选'} · {row.currentIc === undefined ? '—' : signed(row.currentIc)}</span>
                    <span>{row.previousStatus ? STATUS_LABEL[row.previousStatus] : '非探索候选'} · {row.previousIc === undefined ? '—' : signed(row.previousIc)}</span>
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
              <EquityChart points={result.curve} showMultifactor={multifactorConstructed} />
            </section>

            <aside className={s.decisionRail}>
              <div className={s.sectionHead}><div><span>FACTOR SET</span><h2>{multifactorConstructed ? '探索候选组合' : '未发现合格因子'}</h2></div><Gauge size={19} /></div>
              <strong className={s.selectedFactors}>{selectedNames}</strong>
              <dl className={s.railStats}>
                <div><dt>训练 / 隔离 / 验证</dt><dd>{result.summary.train_rows} / {result.summary.purged_rows} / {result.summary.test_rows}</dd></div>
                <div><dt>未来收益窗口</dt><dd>{result.summary.horizon} 周期</dd></div>
                <div><dt>交易成本</dt><dd>{result.summary.transaction_cost_bps} bp</dd></div>
                <div><dt>窗口验证</dt><dd>{result.summary.walk_forward_folds ?? 1} 个 · {result.summary.walk_forward_mode === 'rolling' ? '滚动' : result.summary.walk_forward_mode === 'expanding' ? '扩展' : '单次'}</dd></div>
                <div><dt>研究区间</dt><dd>{result.summary.research_period ? `${result.summary.research_period.start.slice(0, 10)} / ${result.summary.research_period.end.slice(0, 10)}` : '旧记录未保存'}</dd></div>
                <div><dt>引擎 / 公式</dt><dd>{result.summary.engine_version && result.summary.factor_formula_version ? `${result.summary.engine_version} / ${result.summary.factor_formula_version}` : '旧记录未保存'}</dd></div>
                <div><dt>数据指纹</dt><dd title={result.summary.data_fingerprint}>{result.summary.data_fingerprint?.slice(0, 12) ?? '旧记录未保存'}</dd></div>
                <div><dt>数据质量</dt><dd>{result.quality.status === 'ok' ? '通过' : result.quality.status}</dd></div>
              </dl>
              <div className={s.methodNote}><Info size={16} /><span>{multifactorConstructed ? '组合方向与初始权重由训练段确定，且只有通过样本外统计门禁的因子可以进入组合。' : '当前没有因子通过样本外统计门禁，因此不生成组合、成本曲线或策略实验。'}{result.methodology.usable_rule}</span></div>
            </aside>
          </div>

          <section className={s.panel}>
            <div className={s.sectionHead}><div><span>02 / UNDERWATER</span><h2>样本外回撤轨迹</h2></div><small>红：标的 · 青：多因子组合</small></div>
            <DrawdownChart points={result.curve} showMultifactor={multifactorConstructed} />
          </section>

          <section className={s.panel}>
            <div className={s.sectionHead}><div><span>03 / FACTOR SCREEN</span><h2>因子有效性与衰减</h2></div><small>方向由训练段确定 · 按样本外结果排序</small></div>
            <div className={s.tableScroll}>
              <table className={s.table}>
                <thead><tr><th>因子</th><th>结论</th><th className={s.numeric}>评分</th><th className={s.numeric}>窗口 IC 中位数</th><th className={s.numeric}>窗口通过</th><th className={s.numeric}>校正显著性</th><th className={s.numeric}>ICIR</th><th className={s.numeric}>滚动 IC 正值</th><th className={s.numeric}>命中率</th><th>IC 衰减 1/3/5/10/20</th></tr></thead>
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
                <div><dt>闭合交易利润因子</dt><dd>{multifactorMethod.profit_factor.toFixed(2)}</dd></div>
                <div><dt>平均持有</dt><dd>{multifactorMethod.average_holding_period.toFixed(1)} 周期</dd></div>
                <div><dt>盈亏平衡成本</dt><dd>{result.cost_analysis?.breakeven_transaction_cost_bps === null ? '> 1000 bp' : result.cost_analysis?.breakeven_transaction_cost_bps === undefined ? '旧记录未保存' : `${result.cost_analysis.breakeven_transaction_cost_bps.toFixed(2)} bp`}</dd></div>
              </dl>
            </section>
          )}

          {result.cost_analysis?.available !== false && result.cost_analysis && (
            <section className={s.panel} aria-label="交易成本敏感度">
              <div className={s.sectionHead}>
                <div><span>TRANSACTION COST STRESS</span><h2>交易成本敏感度</h2></div>
                <small>多因子 · 最后一个样本外窗口</small>
              </div>
              <div className={s.costCurve}>
                {result.cost_analysis.curve.map((point) => (
                  <div key={point.transaction_cost_bps}>
                    <span>{point.transaction_cost_bps} bp</span>
                    <strong className={point.total_return >= 0 ? s.positive : s.negative}>{pct(point.total_return)}</strong>
                  </div>
                ))}
              </div>
            </section>
          )}

          {result.methodology.metric_definitions && (
            <details className={s.metricDefinitions}>
              <summary><span>交易指标定义</span><small>公式、单位与数据来源</small><ChevronDown size={16} /></summary>
              <div className={s.metricDefinitionGrid}>
                {result.methodology.metric_definitions.map((item) => (
                  <article key={item.key}>
                    <strong>{item.label}</strong><span>{item.formula}</span><small>{item.unit} · {item.source}</small>
                  </article>
                ))}
              </div>
            </details>
          )}

          <section className={s.panel}>
            <div className={s.sectionHead}><div><span>04 / METHOD BENCHMARK</span><h2>量化方法对比</h2></div><small>仅样本外 · 信号延迟一周期 · 已计成本{result.reality_check?.available ? ` · Reality Check p=${result.reality_check.p_value?.toFixed(3)}` : ''}</small></div>
            <div className={s.tableScroll}>
              <table className={s.table}>
                <thead><tr><th>方法</th><th className={s.numeric}>总收益</th><th className={s.numeric}>年化</th><th className={s.numeric}>夏普</th><th className={s.numeric}>DSR</th><th className={s.numeric}>Sortino</th><th className={s.numeric}>Calmar</th><th className={s.numeric}>最大回撤</th><th className={s.numeric}>CVaR</th><th className={s.numeric}>闭合交易胜率</th><th className={s.numeric}>闭合交易</th><th className={s.numeric}>敞口</th></tr></thead>
                <tbody>{result.methods.map((method, index) => (
                  <tr key={method.key}>
                    <td><div className={s.methodName}><strong>{method.label}</strong>{index === 0 && <span>风险调整后最优</span>}</div></td>
                    <td className={`${s.numeric} ${method.total_return >= 0 ? s.positive : s.negative}`}>{pct(method.total_return)}</td>
                    <td className={s.numeric}>{pct(method.annual_return)}</td>
                    <td className={s.numeric}>{method.sharpe.toFixed(2)}</td>
                    <td className={s.numeric}>{method.deflated_sharpe_ratio !== undefined ? pct(method.deflated_sharpe_ratio) : '—'}</td>
                    <td className={s.numeric}>{method.sortino.toFixed(2)}</td>
                    <td className={s.numeric}>{method.calmar.toFixed(2)}</td>
                    <td className={`${s.numeric} ${s.negative}`}>{pct(method.max_drawdown)}</td>
                    <td className={`${s.numeric} ${s.negative}`}>{pct(method.cvar_95, 2)}</td>
                    <td className={s.numeric}>{pct(method.win_rate)}</td>
                    <td className={s.numeric}>{method.closed_trades ?? method.trades}</td>
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

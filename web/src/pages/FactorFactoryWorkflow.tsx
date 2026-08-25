import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Archive, BookOpenCheck, CandlestickChart, Check, CircleAlert, FileCheck2, FlaskConical, Link2, ListFilter, RefreshCw, ScanSearch, Search, ShieldAlert, ShieldCheck, Star, TimerReset, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { AlphaDslCatalog, FactorFactoryArchiveRecord, FactorFactoryRunResponse, FactorLifecycleState, Instrument, LLMConfigResp, LLMProviderId, OkxSwapCatalogResponse, OkxSwapInstrument } from '../api/types'
import KlineCard from '../components/KlineCard'
import { Badge, Button, Field, Input, Panel, SegmentedControl, Select, Textarea } from '../components/ui'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { FactorCohortPanel } from './FactorCohortPanel'
import s from './FactorFactoryWorkflow.module.css'

type Ast = Record<string, unknown>
type ManualAlphaDraft = {
  candidate_id?: string
  label?: string
  family?: string
  expression?: string
  formula_ast?: Ast
  hypothesis?: string
  invalidation?: string
  falsification_tests?: string[]
}

type InstrumentSuggestion = Pick<Instrument, 'code' | 'market' | 'name' | 'exchange'> & { verified?: boolean }
type FactorFactorySource = 'okx_local' | 'okx_live' | 'akshare_live' | 'synthetic'
type FavoriteInstrument = InstrumentSuggestion
type ManualAlphaPreset = 'momentum' | 'reversal' | 'volume_pressure' | 'breakout'
type ManualAlphaProfile = 'fast' | 'balanced' | 'robust'

const COMMON_INSTRUMENTS: Record<'crypto' | 'a_shares', InstrumentSuggestion[]> = {
  crypto: [
    { code: 'BTC-USDT-SWAP', market: 'crypto', name: '比特币 / Bitcoin 永续', exchange: 'okx' },
    { code: 'ETH-USDT-SWAP', market: 'crypto', name: '以太坊 / Ethereum 永续', exchange: 'okx' },
    { code: 'SOL-USDT-SWAP', market: 'crypto', name: 'Solana 永续', exchange: 'okx' },
    { code: 'NVDA-USDT-SWAP', market: 'crypto', name: '英伟达 / NVIDIA 永续', exchange: 'okx' },
    { code: 'AVGO-USDT-SWAP', market: 'crypto', name: '博通 / Broadcom 永续', exchange: 'okx' },
  ],
  a_shares: [
    { code: '600519', market: 'a_shares', name: '贵州茅台', exchange: 'sse' },
    { code: '000001', market: 'a_shares', name: '平安银行', exchange: 'szse' },
    { code: '300750', market: 'a_shares', name: '宁德时代', exchange: 'szse' },
    { code: '601318', market: 'a_shares', name: '中国平安', exchange: 'sse' },
  ],
}

const FAVORITE_INSTRUMENTS_KEY = 'quanthub.factor-factory.favorite-instruments.v1'

function okxTradingReady(item: Pick<OkxSwapInstrument, 'trading_ready' | 'verified'>): boolean {
  return item.trading_ready ?? item.verified === true
}

function okxCatalogTradingReady(
  source: OkxSwapCatalogResponse['source'] | undefined,
  item: Pick<OkxSwapInstrument, 'trading_ready' | 'verified'>,
): boolean {
  return source === 'okx_public' && okxTradingReady(item)
}

function isResearchOnlySource(source: FactorFactorySource): boolean {
  return source === 'okx_local' || source === 'synthetic'
}

function okxAvailableIntervals(item: Pick<OkxSwapInstrument, 'available_intervals'>): string[] {
  return item.available_intervals?.length ? item.available_intervals : ['1h', '4h', '1d']
}

const ALPHA_PRESET_OPTIONS = [
  { value: 'momentum', label: '趋势动量' },
  { value: 'reversal', label: '短期反转' },
  { value: 'volume_pressure', label: '量价压力' },
  { value: 'breakout', label: '放量突破' },
]

const ALPHA_PROFILE_OPTIONS = [
  { value: 'fast', label: '短线 · 2 / 12' },
  { value: 'balanced', label: '均衡 · 3 / 20' },
  { value: 'robust', label: '稳健 · 5 / 40' },
]

const ALPHA_PROFILE_PARAMS: Record<ManualAlphaProfile, { period: number; window: number }> = {
  fast: { period: 2, window: 12 },
  balanced: { period: 3, window: 20 },
  robust: { period: 5, window: 40 },
}

const DEFAULT_ALPHA_DSL: AlphaDslCatalog = {
  version: 'brain-alpha-v1.1',
  fields: [
    { name: 'open', label: '开盘价', unit: 'price' },
    { name: 'high', label: '最高价', unit: 'price' },
    { name: 'low', label: '最低价', unit: 'price' },
    { name: 'close', label: '收盘价', unit: 'price' },
    { name: 'volume', label: '成交量', unit: 'volume' },
  ],
  parameters: [
    { name: 'value', description: '字段、数值常量或另一个算子的结果' },
    { name: 'left / right', description: '二元算子的左右输入' },
    { name: 'periods', description: '回看或滞后的 K 线数量；整数 1–500' },
    { name: 'window', description: '滚动统计窗口；整数 1–500' },
    { name: 'lower / upper', description: '缩尾分位数；0 ≤ lower < upper ≤ 1' },
    { name: 'condition / then / else', description: '布尔条件、条件成立值、条件不成立值' },
  ],
  operators: [
    { name: 'add', signature: 'add(left, right)', description: '相加；两侧单位必须一致', example: 'add(close, neg(open))' },
    { name: 'sub', signature: 'sub(left, right)', description: '相减；两侧单位必须一致', example: 'sub(close, open)' },
    { name: 'mul', signature: 'mul(left, right)', description: '相乘，用于组合两个信号', example: 'mul(pct_change(close, 3), rank(volume, 20))' },
    { name: 'div', signature: 'div(left, right)', description: '相除；同单位结果为无量纲', example: 'div(sub(close, open), open)' },
    { name: 'gt', signature: 'gt(left, right)', description: '大于比较，生成布尔条件', example: 'gt(close, rolling_mean(close, 20))' },
    { name: 'lt', signature: 'lt(left, right)', description: '小于比较，生成布尔条件', example: 'lt(close, rolling_mean(close, 20))' },
    { name: 'neg', signature: 'neg(value)', description: '信号取反，常用于反转因子', example: 'neg(pct_change(close, 3))' },
    { name: 'abs', signature: 'abs(value)', description: '取绝对值', example: 'abs(pct_change(close, 1))' },
    { name: 'lag', signature: 'lag(value, periods)', description: '向后滞后 periods 根 K 线', example: 'lag(close, 1)' },
    { name: 'diff', signature: 'diff(value, periods)', description: '与 periods 根 K 线前做差', example: 'diff(close, 5)' },
    { name: 'pct_change', signature: 'pct_change(value, periods)', description: '计算 periods 根 K 线收益率', example: 'pct_change(close, 3)' },
    { name: 'rolling_mean', signature: 'rolling_mean(value, window)', description: '滚动均值', example: 'rolling_mean(close, 20)' },
    { name: 'rolling_std', signature: 'rolling_std(value, window)', description: '滚动标准差', example: 'rolling_std(pct_change(close, 1), 20)' },
    { name: 'rolling_min', signature: 'rolling_min(value, window)', description: '滚动最小值', example: 'rolling_min(low, 20)' },
    { name: 'rolling_max', signature: 'rolling_max(value, window)', description: '滚动最大值', example: 'rolling_max(high, 20)' },
    { name: 'rolling_sum', signature: 'rolling_sum(value, window)', description: '滚动求和', example: 'rolling_sum(volume, 20)' },
    { name: 'rolling_zscore', signature: 'rolling_zscore(value, window)', description: '滚动标准分，常用于归一化', example: 'rolling_zscore(pct_change(close, 3), 20)' },
    { name: 'rolling_winsorize', signature: 'rolling_winsorize(value, window[, lower, upper])', description: '滚动缩尾；默认分位数 0.01 / 0.99', example: 'rolling_winsorize(pct_change(close, 1), 20, 0.01, 0.99)' },
    { name: 'rank', signature: 'rank(value, window)', description: '当前值在滚动窗口内的百分位排名', example: 'rank(volume, 20)' },
    { name: 'where', signature: 'where(condition, then, else)', description: '按布尔条件选择两个同单位结果', example: 'where(gt(close, open), volume, neg(volume))' },
  ],
  limits: { periods_min: 1, periods_max: 500, window_min: 1, window_max: 500, max_depth: 10, max_operators: 30, winsor_lower_min: 0, winsor_upper_max: 1 },
}

function manualAlphaExpression(preset: ManualAlphaPreset, profile: ManualAlphaProfile) {
  const { period, window } = ALPHA_PROFILE_PARAMS[profile]
  if (preset === 'momentum') return `rolling_zscore(pct_change(close, ${period}), ${window})`
  if (preset === 'reversal') return `neg(rolling_zscore(pct_change(close, ${period}), ${window}))`
  if (preset === 'breakout') return `mul(rolling_zscore(pct_change(close, ${window}), ${window}), rank(volume, ${window}))`
  return `mul(rolling_zscore(pct_change(close, ${period}), ${window}), rank(volume, ${window}))`
}

function normalizedDirectSymbol(value: string, market: 'crypto' | 'a_shares') {
  const normalized = value.trim().toUpperCase().replace(/\s/g, '').replace('/', '-')
  if (market === 'a_shares') return /^\d{6}$/.test(normalized) ? normalized : ''
  if (/^[A-Z][A-Z0-9]{1,14}$/.test(normalized)) return `${normalized}-USDT-SWAP`
  if (/^[A-Z0-9]+USDT$/.test(normalized)) return `${normalized.slice(0, -4)}-USDT-SWAP`
  if (/^[A-Z0-9]+-USDT$/.test(normalized)) return `${normalized}-SWAP`
  return /^[A-Z0-9]+-USDT-SWAP$/.test(normalized) ? normalized : ''
}

function matchesInstrument(item: InstrumentSuggestion, query: string) {
  const needle = query.trim().toUpperCase()
  if (!needle) return true
  return `${item.code} ${item.name}`.toUpperCase().includes(needle)
}

function okxCatalogErrorMessage(reason: unknown) {
  const raw = typeof reason === 'string'
    ? reason
    : reason instanceof Error
      ? reason.message
      : ''
  const normalized = raw.toLowerCase()
  if (normalized.includes('timeout') || normalized.includes('timed out') || raw.includes('连接超时')) {
    return 'OKX 公共合约目录连接超时，公共目录暂时不可用，请稍后重试。'
  }
  if (normalized.includes('connection') || normalized.includes('network') || raw.includes('无法连接')) {
    return 'OKX 公共合约目录暂时无法连接，请稍后重试。'
  }
  return 'OKX 公共合约目录暂不可用，请稍后重试。'
}

const FACTORY_STATUS: Record<string, string> = {
  discovering: '搜索中',
  no_qualified_factor: '滚动验证无通过',
  no_research_passed_factor: '锁定确认未通过',
  paper_observing: '模拟观察中',
  paper_rejected: '模拟门禁未通过',
  trading_validated: '模拟验证通过',
  degraded: '已降级',
  failed: '运行失败',
}

const CANDIDATE_SOURCE_LABELS: Record<string, string> = {
  ai: 'AI 提案',
  human: '手工输入',
  template: '固定模板',
  random_dsl: '规则生成',
  symbolic_regression: '符号组合',
  parameter_search: '参数搜索',
}

const RESEARCH_CHECK_LABELS: Record<string, string> = {
  validation_return: '滚动验证收益达到阈值',
  validation_drawdown: '滚动验证回撤受控',
  validation_sharpe: '滚动验证夏普达到阈值',
  minimum_trades: '有效交易次数充足',
  direction_consistency: '发现集与验证集方向一致',
  validation_window_majority: '多数滚动窗口为正',
  validation_p_value: '统计显著性达到阈值',
  validation_rank_ic_direction: 'Rank IC 方向正确',
  cost_stress_return: '成本压力后收益达标',
  cost_stress_drawdown: '成本压力后回撤受控',
  cost_stress_sharpe: '成本压力后夏普达标',
  cost_stress_window_majority: '成本压力下多数窗口为正',
  confirmation_return: '锁定确认集收益达标',
  incremental_return: '确认集增量收益达标',
  confirmation_drawdown: '锁定确认集回撤受控',
  confirmation_sharpe: '锁定确认集夏普达标',
  p_value: '确认集 p 值达标',
  window_majority: '确认集多数窗口为正',
  parameter_plateau: '相邻参数存在稳定平台',
  regime_stability: '不同市场状态表现稳定',
}

const LIFECYCLE_STATUS: Record<FactorLifecycleState, string> = {
  draft: '待验证',
  exploratory: '探索中',
  research_passed: '研究通过',
  trading_validated: '模拟验证通过',
  degraded: '已降级',
  retired: '已退役',
}

const ARCHIVE_RISK: Record<string, string> = {
  candidate_data_validation_not_completed: '候选数据覆盖验证未完成',
  locked_confirmation_not_passed: '锁定确认尚未通过',
  simulation_observation_not_completed: '模拟观察周期尚未完成',
  monitoring_gate_failed: '持续监控门禁失败',
  factor_retired: '因子已退役',
  no_factor_factory_run: '没有关联的自动研究运行',
  rolling_validation_not_passed: '滚动验证未通过',
  observation_period_incomplete: '真实观察期未结束',
  simulation_gate_not_passed: '模拟交易门禁未通过',
  factor_factory_run_failed: '自动研究运行失败',
}

function pct(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`
}

function num(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function asString(value: unknown, fallback = '—') {
  return typeof value === 'string' && value ? value : fallback
}

function nestedNumber(value: unknown, ...path: string[]) {
  let current: unknown = value
  for (const key of path) {
    if (!current || typeof current !== 'object') return null
    current = (current as Record<string, unknown>)[key]
  }
  return typeof current === 'number' && Number.isFinite(current) ? current : null
}

function nestedString(value: unknown, ...path: string[]) {
  let current: unknown = value
  for (const key of path) {
    if (!current || typeof current !== 'object') return null
    current = (current as Record<string, unknown>)[key]
  }
  return typeof current === 'string' && current ? current : null
}

function nestedBoolean(value: unknown, ...path: string[]) {
  let current: unknown = value
  for (const key of path) {
    if (!current || typeof current !== 'object') return null
    current = (current as Record<string, unknown>)[key]
  }
  return typeof current === 'boolean' ? current : null
}

function nestedRecord(value: unknown, ...path: string[]) {
  let current: unknown = value
  for (const key of path) {
    if (!current || typeof current !== 'object') return null
    current = (current as Record<string, unknown>)[key]
  }
  return current && typeof current === 'object' ? current as Record<string, unknown> : null
}

function nestedRecords(value: unknown, ...path: string[]) {
  let current: unknown = value
  for (const key of path) {
    if (!current || typeof current !== 'object') return []
    current = (current as Record<string, unknown>)[key]
  }
  return Array.isArray(current)
    ? current.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    : []
}

const DIRECTION_LIGHT_LABELS: Record<string, string> = {
  GREEN: 'GREEN 继续深挖',
  YELLOW: 'YELLOW 补充证据',
  RED: 'RED 更换结构',
  DEAD: 'DEAD 切换方向',
}

function newExperimentNonce() {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return `run-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function aiGenerationMessage(status: string | null, error: string | null, provider: string | null, acceptedCount: number) {
  if (!status || status === 'disabled' || status === 'generated') return null
  const source = provider === 'deepseek' ? 'DeepSeek' : provider === 'openai' ? 'OpenAI' : provider === 'custom' ? '兼容 API' : 'AI'
  if (status === 'generated_partial') return `${source} 输出在末尾截断；已保留 ${acceptedCount} 个完整且通过校验的 AI 候选，其余由规则候选补齐。`
  if (status === 'reasoning_budget_exhausted') return `${source} 的推理过程耗尽了输出预算，未返回候选 JSON；本轮已回退规则候选。`
  if (status === 'invalid_output') return `${source} 已响应，但候选格式或 DSL 校验未通过；本轮已回退规则候选。`
  if (status === 'token_budget_insufficient' || status === 'token_budget_exceeded') return `${source} token 预算不足；本轮已回退规则候选。`
  if (/api_key.*(?:未配置|not configured)/i.test(error ?? '')) return `${source} 未配置 API Key；本轮已回退规则候选。`
  if (/timeout/i.test(error ?? '')) return `${source} 响应超时；本轮未收到完整结果，已回退规则候选。`
  if (/connection|disconnected|protocol/i.test(error ?? '')) return `${source} 连接中断；本轮未收到完整结果，已回退规则候选。`
  return `${source} 本轮不可用；已回退规则候选。`
}

function factorFamilyLabel(value: string | null | undefined) {
  const family = value?.toLowerCase() ?? ''
  if (!family) return '未分类'
  if (family.includes('manual')) return '手工 Alpha'
  if (family.includes('reversal')) return '均值反转'
  if (family.includes('breakout')) return '价格突破'
  if (family.includes('momentum') || family.includes('trend') || family.includes('efficiency')) return '趋势动量'
  if (family.includes('volume') || family.includes('liquidity') || family.includes('pressure')) return '量价流动性'
  if (family.includes('volatility')) return '波动率状态'
  if (family.includes('location') || family.includes('range')) return '价格位置'
  if (family.includes('ai')) return 'AI 复合提案'
  return value?.replace(/^factor_factory_/, '').replace(/^brain_/, '').replace(/_/g, ' ') ?? '未分类'
}

function alphaAstExpression(value: unknown): string {
  if (!value || typeof value !== 'object') return '定义不可用'
  const node = value as Record<string, unknown>
  const op = typeof node.op === 'string' ? node.op : ''
  if (op === 'field') return asString(node.name, 'field')
  if (op === 'const') return typeof node.value === 'number' ? String(node.value) : 'const'
  if (op === 'builtin_factor') return `builtin_factor(${asString(node.name ?? node.key, 'unknown')})`
  if (['add', 'sub', 'mul', 'div', 'gt', 'lt'].includes(op)) {
    return `${op}(${alphaAstExpression(node.left)}, ${alphaAstExpression(node.right)})`
  }
  if (['neg', 'abs'].includes(op)) return `${op}(${alphaAstExpression(node.value)})`
  if (['lag', 'diff', 'pct_change'].includes(op)) {
    return `${op}(${alphaAstExpression(node.value)}, ${String(node.periods ?? '?')})`
  }
  if (['rolling_mean', 'rolling_std', 'rolling_min', 'rolling_max', 'rolling_sum', 'rolling_zscore', 'rank'].includes(op)) {
    return `${op}(${alphaAstExpression(node.value)}, ${String(node.window ?? '?')})`
  }
  if (op === 'rolling_winsorize') {
    const bounds = typeof node.lower === 'number' && typeof node.upper === 'number'
      ? `, ${node.lower}, ${node.upper}`
      : ''
    return `${op}(${alphaAstExpression(node.value)}, ${String(node.window ?? '?')}${bounds})`
  }
  if (op === 'where') {
    return `where(${alphaAstExpression(node.condition)}, ${alphaAstExpression(node.then)}, ${alphaAstExpression(node.else)})`
  }
  if (op === 'industry_neutralize') {
    return `industry_neutralize(${alphaAstExpression(node.value)}, ${alphaAstExpression(node.industry)}, ${alphaAstExpression(node.date)})`
  }
  return JSON.stringify(node)
}

function candidateStageLabel(candidate: FactorFactoryRunResponse['candidates'][number], run: FactorFactoryRunResponse['run']) {
  const selected = candidate.factor_key === run.selected_factor_key
  if (selected && run.status === 'paper_observing') return '7 天模拟中'
  if (selected && run.status === 'paper_rejected') return '7 天模拟淘汰'
  if (selected && run.status === 'trading_validated') return '7 天模拟通过'
  if (candidate.status === 'preflight_rejected') {
    return nestedString(candidate.gate, 'reason') === 'formula_duplicate' ? '重复公式淘汰' : '相似信号淘汰'
  }
  if (candidate.status === 'gate_rejected') return '滚动门禁淘汰'
  if (candidate.status === 'preliminary_passed') return '滚动初筛通过'
  if (candidate.status === 'confirmation_rejected') return '确认集淘汰'
  if (candidate.status === 'research_passed') return '确认集通过'
  if (candidate.status === 'invalid') return '表达式无效'
  return candidate.status
}

function ObservationCurve({ observations }: { observations: FactorFactoryRunResponse['observations'] }) {
  const points = observations
    .map((item) => ({ equity: Number(item.equity), label: new Date(item.market_time).toLocaleString('zh-CN', { hour12: false }) }))
    .filter((item) => Number.isFinite(item.equity))
  if (points.length < 2) {
    return <div className={s.curveEmpty}>至少需要 2 个真实前向观察点，当前不绘制曲线。</div>
  }
  const values = points.map((item) => item.equity)
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  const span = Math.max(maximum - minimum, Math.abs(maximum) * 0.002, 1)
  const path = points.map((item, index) => {
    const x = points.length === 1 ? 0 : (index / (points.length - 1)) * 100
    const y = 38 - ((item.equity - minimum) / span) * 34
    return `${x.toFixed(2)},${y.toFixed(2)}`
  }).join(' ')
  const latest = points[points.length - 1]
  return <div className={s.observationCurve}>
    <svg viewBox="0 0 100 42" preserveAspectRatio="none" role="img" aria-label="真实前向观察权益曲线">
      <line x1="0" y1="38" x2="100" y2="38" />
      <polyline points={path} />
    </svg>
    <div><span>{points[0].label}</span><strong>{num(latest.equity, 0)}</strong><span>{latest.label}</span></div>
  </div>
}

function gateState(value: boolean | null) {
  return value === null ? '待采集' : value ? '正常' : '阻断'
}

function archiveRiskLabel(value: string) {
  if (ARCHIVE_RISK[value]) return ARCHIVE_RISK[value]
  if (value.startsWith('confirmation:')) return `确认门禁：${value.slice('confirmation:'.length)}`
  if (value.startsWith('simulation:')) return `模拟门禁：${value.slice('simulation:'.length)}`
  return value
}

function archiveCriteria(value: Record<string, unknown> | undefined) {
  if (!value) return '—'
  const entries = Object.entries(value)
  if (entries.length === 0) return '—'
  return entries.slice(0, 4).map(([key, item]) => `${key}=${typeof item === 'object' ? JSON.stringify(item) : String(item)}`).join(' · ')
}

function timeLabel(value: number | null | undefined) {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}

export function FactorFactoryWorkflow() {
  const [archive, setArchive] = useState<FactorFactoryArchiveRecord[]>([])
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [archiveFilter, setArchiveFilter] = useState<'' | FactorLifecycleState>('')
  const [archiveMeta, setArchiveMeta] = useState({ admitted: 0, research: 0, excluded: 0 })
  const [selectedArchiveId, setSelectedArchiveId] = useState('')
  const [busy, setBusy] = useState<'refresh' | ''>('')
  const [autoPaperTarget, setAutoPaperTarget] = useState<'simulation_orders' | 'okx_demo'>('okx_demo')
  const [autoMarket, setAutoMarket] = useState<'crypto' | 'a_shares'>('crypto')
  const [autoSymbol, setAutoSymbol] = useState('BTC-USDT-SWAP')
  // A crypto instrument is executable only after the current OKX public
  // catalog has positively verified it.  Do not trust the historical/default
  // symbol while the catalog request is pending (or when it failed).
  const [autoInstrumentTradingReady, setAutoInstrumentTradingReady] = useState(false)
  const [instrumentQuery, setInstrumentQuery] = useState('BTC-USDT-SWAP')
  const [instrumentOptions, setInstrumentOptions] = useState<InstrumentSuggestion[]>(COMMON_INSTRUMENTS.crypto)
  const [instrumentSearchOpen, setInstrumentSearchOpen] = useState(false)
  const [instrumentSearchBusy, setInstrumentSearchBusy] = useState(false)
  const [favoriteInstruments, setFavoriteInstruments] = useLocalStorage<FavoriteInstrument[]>(FAVORITE_INSTRUMENTS_KEY, [])
  const [okxCatalogOpen, setOkxCatalogOpen] = useState(false)
  const [okxCatalogQuery, setOkxCatalogQuery] = useState('')
  const [okxCatalog, setOkxCatalog] = useState<OkxSwapCatalogResponse | null>(null)
  const [okxCatalogBusy, setOkxCatalogBusy] = useState(false)
  const [okxCatalogError, setOkxCatalogError] = useState('')
  const [okxKlineOpen, setOkxKlineOpen] = useState(false)
  const [autoSource, setAutoSource] = useState<FactorFactorySource>('okx_live')
  const [autoInterval, setAutoInterval] = useState<'1h' | '4h' | '1d'>('4h')
  const [autoHorizon, setAutoHorizon] = useState(5)
  const [autoBars, setAutoBars] = useState(720)
  const [autoBudget, setAutoBudget] = useState(30)
  const [autoDays, setAutoDays] = useState(7)
  const [autoCandidateMode, setAutoCandidateMode] = useState<'brain' | 'library' | 'manual'>('brain')
  const [autoUseAi, setAutoUseAi] = useState(true)
  const [aiProviders, setAiProviders] = useState<LLMConfigResp['providers']>([])
  const [autoAiProvider, setAutoAiProvider] = useState<LLMProviderId | ''>('')
  const [autoAiCount, setAutoAiCount] = useState(6)
  const [autoAlphaBrief, setAutoAlphaBrief] = useState('寻找因果安全、成本后收益稳定、回撤受控，并对相邻参数稳健的量价 Alpha 表达式。')
  const [manualPreset, setManualPreset] = useState<ManualAlphaPreset>('volume_pressure')
  const [manualProfile, setManualProfile] = useState<ManualAlphaProfile>('balanced')
  const [manualAlphaText, setManualAlphaText] = useState(manualAlphaExpression('volume_pressure', 'balanced'))
  const [manualBatch, setManualBatch] = useState<ManualAlphaDraft[]>([])
  const [alphaDsl, setAlphaDsl] = useState<AlphaDslCatalog>(DEFAULT_ALPHA_DSL)
  const [alphaDslQuery, setAlphaDslQuery] = useState('')
  const [autoRun, setAutoRun] = useState<FactorFactoryRunResponse | null>(null)
  const autoLoadSequence = useRef(0)
  const [selectedAutoCandidateId, setSelectedAutoCandidateId] = useState('')
  const [candidateQuery, setCandidateQuery] = useState('')
  const [candidateFamilyFilter, setCandidateFamilyFilter] = useState('')
  const [autoBusy, setAutoBusy] = useState<'load' | 'start' | 'observe' | 'cohort-review' | 'live-request' | 'manual-approval' | ''>('load')
  const [autoView, setAutoView] = useState<'candidates' | 'cohort'>('candidates')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    void api.llmConfig()
      .then((response) => {
        if (cancelled) return
        const configured = response.providers.filter((provider) => provider.configured)
        setAiProviders(configured)
        setAutoAiProvider((current) => (
          configured.some((provider) => provider.id === current)
            ? current
            : configured.find((provider) => provider.id === response.provider)?.id
              ?? configured[0]?.id
              ?? ''
        ))
      })
      .catch(() => {
        if (!cancelled) {
          setAiProviders([])
          setAutoAiProvider('')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (autoCandidateMode !== 'manual') return
    let cancelled = false
    void api.alphaDslCatalog()
      .then((catalog) => {
        if (!cancelled) setAlphaDsl(catalog)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [autoCandidateMode])

  useEffect(() => {
    let cancelled = false
    const common = COMMON_INSTRUMENTS[autoMarket].filter((item) => matchesInstrument(item, instrumentQuery))
    setInstrumentOptions(autoMarket === 'crypto' ? [] : common)
    const timer = window.setTimeout(async () => {
      setInstrumentSearchBusy(true)
      try {
        let remote: InstrumentSuggestion[]
        if (autoMarket === 'crypto') {
          const catalog = await api.okxSwapCatalog(instrumentQuery.trim(), 20)
          remote = catalog.instruments.flatMap<InstrumentSuggestion>((item) => {
              const code = normalizedDirectSymbol(item.code, 'crypto')
              return code ? [{
                code,
                market: item.market,
                name: item.name,
                exchange: item.exchange,
                verified: okxCatalogTradingReady(catalog.source, item),
              }] : []
            })
        } else {
          remote = (await api.instruments(instrumentQuery.trim(), 12, autoMarket)).instruments
            .flatMap<InstrumentSuggestion>((item) => item.code ? [{
              code: item.code,
              market: item.market,
              name: item.name,
              exchange: item.exchange,
              verified: true,
            }] : [])
        }
        if (cancelled) return
        const merged = [...remote, ...(autoMarket === 'crypto' ? [] : common)].filter(
          (item, index, rows) => rows.findIndex((candidate) => candidate.code === item.code) === index,
        )
        setInstrumentOptions(merged.slice(0, 12))
        if (autoMarket === 'crypto') {
          const direct = normalizedDirectSymbol(instrumentQuery, 'crypto')
          const matched = remote.find((item) => item.code === direct)
          setAutoSymbol(matched ? direct : '')
          setAutoInstrumentTradingReady(Boolean(matched?.verified))
          if (matched && !matched.verified) setAutoPaperTarget('simulation_orders')
        }
      } catch {
        if (!cancelled) setInstrumentOptions(autoMarket === 'crypto' ? [] : common)
      } finally {
        if (!cancelled) setInstrumentSearchBusy(false)
      }
    }, 180)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [autoMarket, instrumentQuery])

  const loadOkxCatalog = useCallback(async (refresh = false) => {
    setOkxCatalogBusy(true)
    setOkxCatalogError('')
    try {
      const response = await api.okxSwapCatalog(okxCatalogQuery.trim(), 120, refresh)
      setOkxCatalog(response)
      if (!response.ok) setOkxCatalogError(okxCatalogErrorMessage(response.error))
    } catch (reason) {
      setOkxCatalogError(okxCatalogErrorMessage(reason))
    } finally {
      setOkxCatalogBusy(false)
    }
  }, [okxCatalogQuery])

  useEffect(() => {
    if (!okxCatalogOpen) return
    const timer = window.setTimeout(() => void loadOkxCatalog(false), 160)
    return () => window.clearTimeout(timer)
  }, [loadOkxCatalog, okxCatalogOpen])

  const visibleAlphaOperators = useMemo(() => {
    const needle = alphaDslQuery.trim().toLowerCase()
    if (!needle) return alphaDsl.operators
    return alphaDsl.operators.filter((item) => `${item.name} ${item.signature} ${item.description}`.toLowerCase().includes(needle))
  }, [alphaDsl, alphaDslQuery])
  const marketFavorites = useMemo(
    () => favoriteInstruments.filter((item) => item.market === autoMarket),
    [autoMarket, favoriteInstruments],
  )
  const activeFavorite = marketFavorites.some((item) => item.code === autoSymbol)
  const autoResearchReady = Boolean(autoSymbol) && (
    autoMarket !== 'crypto' || autoInstrumentTradingReady || isResearchOnlySource(autoSource)
  )
  const selectInstrument = useCallback((item: InstrumentSuggestion) => {
    const market = item.market === 'a_shares' ? 'a_shares' : 'crypto'
    const catalogMatch = market === 'crypto'
      ? instrumentOptions.find((candidate) => candidate.code === item.code)
      : undefined
    const tradingReady = market !== 'crypto' || Boolean(catalogMatch?.verified)
    if (market !== autoMarket) setAutoMarket(market)
    setAutoSymbol(item.code)
    setAutoInstrumentTradingReady(tradingReady)
    setInstrumentQuery(item.code)
    setAutoSource(market === 'crypto' ? 'okx_live' : 'akshare_live')
    setAutoInterval(market === 'crypto' ? '4h' : '1d')
    setAutoPaperTarget(market === 'crypto' && tradingReady ? 'okx_demo' : 'simulation_orders')
    setInstrumentSearchOpen(false)
  }, [autoMarket, instrumentOptions])
  const toggleFavoriteInstrument = useCallback(() => {
    if (!autoSymbol) return
    setFavoriteInstruments((current) => {
      const exists = current.some((item) => item.market === autoMarket && item.code === autoSymbol)
      if (exists) return current.filter((item) => !(item.market === autoMarket && item.code === autoSymbol))
      const matched = instrumentOptions.find((item) => item.code === autoSymbol)
        ?? COMMON_INSTRUMENTS[autoMarket].find((item) => item.code === autoSymbol)
      return [...current, {
        code: autoSymbol,
        market: autoMarket,
        name: matched?.name || autoSymbol,
        exchange: matched?.exchange || (autoMarket === 'crypto' ? 'okx' : ''),
        verified: autoMarket === 'crypto'
          ? Boolean(autoInstrumentTradingReady && matched?.verified)
          : matched?.verified,
      }]
    })
  }, [autoInstrumentTradingReady, autoMarket, autoSymbol, instrumentOptions, setFavoriteInstruments])
  const loadArchive = useCallback(async () => {
    setBusy('refresh')
    try {
      const response = await api.factorFactoryArchive(archiveFilter || undefined, 100)
      setArchive(response.archives)
      setArchiveMeta({
        admitted: response.total,
        research: response.research_record_count,
        excluded: response.ineligible_count,
      })
      setSelectedArchiveId((current) => response.archives.some((item) => item.archive_id === current)
        ? current
        : response.archives[0]?.archive_id ?? '')
    } catch {
      setArchive([])
      setArchiveMeta({ admitted: 0, research: 0, excluded: 0 })
      setSelectedArchiveId('')
    } finally {
      setBusy('')
    }
  }, [archiveFilter])

  useEffect(() => {
    if (archiveOpen) void loadArchive()
  }, [archiveOpen, loadArchive])

  const loadLatestAutoRun = useCallback(async () => {
    const sequence = ++autoLoadSequence.current
    setAutoBusy('load')
    if (!autoSymbol) {
      setAutoRun(null)
      setAutoBusy('')
      return
    }
    try {
      const history = await api.factorFactoryRuns(1, {
        market: autoMarket,
        symbol: autoSymbol,
        interval: autoInterval,
      })
      const detail = history.runs[0] ? await api.factorFactoryRun(history.runs[0].id) : null
      if (sequence === autoLoadSequence.current) setAutoRun(detail)
    } catch {
      if (sequence === autoLoadSequence.current) setAutoRun(null)
    } finally {
      if (sequence === autoLoadSequence.current) setAutoBusy('')
    }
  }, [autoInterval, autoMarket, autoSymbol])

  useEffect(() => { void loadLatestAutoRun() }, [loadLatestAutoRun])

  const loadManualAlphaFile = useCallback(async (file: File) => {
    setError('')
    try {
      const parsed = JSON.parse(await file.text()) as unknown
      const rows = Array.isArray(parsed)
        ? parsed
        : parsed && typeof parsed === 'object' && Array.isArray((parsed as Record<string, unknown>).candidates)
          ? (parsed as { candidates: unknown[] }).candidates
          : null
      if (!rows || rows.length === 0 || rows.length > 30) {
        throw new Error('JSON 必须是 1 到 30 个候选的数组，或包含 candidates 数组。')
      }
      const candidates = rows.map((row, index) => {
        if (!row || typeof row !== 'object') throw new Error(`第 ${index + 1} 个候选不是对象。`)
        const candidate = row as ManualAlphaDraft
        const hasExpression = typeof candidate.expression === 'string' && candidate.expression.trim().length > 0
        const hasAst = Boolean(candidate.formula_ast && typeof candidate.formula_ast === 'object')
        if (hasExpression === hasAst) {
          throw new Error(`第 ${index + 1} 个候选必须且只能提供 expression 或 formula_ast。`)
        }
        return {
          ...candidate,
          candidate_id: candidate.candidate_id || `uploaded_alpha_${index + 1}`,
          label: candidate.label || `上传 Alpha ${index + 1}`,
        }
      })
      setManualBatch(candidates)
      setAutoCandidateMode('manual')
      setAutoBudget(Math.max(1, candidates.length + (manualAlphaText.trim() ? 1 : 0)))
    } catch (reason) {
      setManualBatch([])
      setError(reason instanceof Error ? reason.message : 'Alpha JSON 文件解析失败')
    }
  }, [manualAlphaText])

  const startAutoResearch = useCallback(async () => {
    setError('')
    if (autoMarket === 'crypto' && !autoInstrumentTradingReady && !isResearchOnlySource(autoSource)) {
      setError('该合约尚未由当前 OKX 公共目录验证。请选择已验证合约，或显式选择研究专用通道。')
      return
    }
    if (isResearchOnlySource(autoSource) && autoPaperTarget !== 'simulation_orders') {
      setError('研究专用行情通道只能进入本地独立模拟。')
      return
    }
    setAutoBusy('start')
    const manualCandidates = [...manualBatch]
    if (autoCandidateMode === 'manual' && manualAlphaText.trim()) {
      const manualId = manualCandidates.some((item) => item.candidate_id === 'manual_alpha_input')
        ? 'manual_alpha_input_2'
        : 'manual_alpha_input'
      manualCandidates.unshift({
        candidate_id: manualId,
        label: '手工输入 Alpha',
        family: 'manual_alpha',
        expression: manualAlphaText.trim(),
        hypothesis: autoAlphaBrief.trim(),
      })
    }
    if (autoCandidateMode === 'manual' && manualCandidates.length === 0) {
      setError('请填写手工 Alpha 表达式，或先上传 JSON 批次。')
      setAutoBusy('')
      return
    }
    if (manualCandidates.length > 30) {
      setError('手工与上传的 Alpha 合计不能超过 30 个。')
      setAutoBusy('')
      return
    }
    try {
      const liveSource = autoMarket === 'a_shares' ? 'akshare_live' : autoSource
      const response = await api.startFactorFactory({
        experiment_nonce: newExperimentNonce(),
        market: autoMarket,
        source: liveSource,
        symbol: autoSymbol,
        dataset: 'uptrend', seed: 12, interval: autoInterval, n_bars: autoBars,
        candidate_budget: autoCandidateMode === 'manual' ? Math.max(autoBudget, manualCandidates.length) : autoBudget,
        horizon: autoHorizon,
        cost_profile_id: autoMarket === 'a_shares' ? 'a-shares-reference' : 'okx-reference',
        cost_profile_version: '1.0.0',
        candidate_mode: autoCandidateMode, alpha_brief: autoAlphaBrief,
        use_ai: autoCandidateMode === 'brain' && autoUseAi,
        ...(autoCandidateMode === 'brain' && autoUseAi && autoAiProvider
          ? { ai_provider: autoAiProvider }
          : {}),
        ai_candidate_count: autoCandidateMode === 'brain' && autoUseAi ? Math.min(autoAiCount, autoBudget) : 0,
        maximum_ai_tokens: 12_000,
        initial_capital: 1_000_000, observation_days: Math.max(7, autoDays),
        paper_target: autoPaperTarget, maximum_demo_exposure: 0.1, maximum_demo_loss: 25,
        manual_candidates: manualCandidates,
      })
      setAutoRun(response)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '自动因子研究失败')
    } finally {
      setAutoBusy('')
    }
  }, [autoAiCount, autoAiProvider, autoAlphaBrief, autoBars, autoBudget, autoCandidateMode, autoDays, autoHorizon, autoInstrumentTradingReady, autoInterval, autoMarket, autoPaperTarget, autoSource, autoSymbol, autoUseAi, manualAlphaText, manualBatch])

  const refreshAutoObservation = useCallback(async () => {
    if (!autoRun) return
    setAutoBusy('observe')
    setError('')
    try {
      const response = autoRun.run.status === 'paper_observing'
        ? await api.observeFactorFactory(autoRun.run.id, autoRun.run.config.source === 'okx_live')
        : await api.factorFactoryRun(autoRun.run.id)
      setAutoRun(response)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模拟观察刷新失败')
    } finally {
      setAutoBusy('')
    }
  }, [autoRun])

  const reviewAutoCohort = useCallback(async () => {
    if (!autoRun) return
    setAutoBusy('cohort-review')
    setError('')
    try {
      const response = await api.reviewFactorFactoryCohort(
        autoRun.run.id,
        autoAiProvider || undefined,
      )
      setAutoRun(response)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI 同期证据评审失败')
    } finally {
      setAutoBusy('')
    }
  }, [autoAiProvider, autoRun])

  const requestAutoSmallLive = useCallback(async () => {
    if (!autoRun) return
    setAutoBusy('live-request')
    setError('')
    try {
      setAutoRun(await api.requestFactorFactorySmallLive(
        autoRun.run.id,
        'factor-factory-user',
        '程序门禁和 AI 证据评审已对齐，提交人工审批。',
      ))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '小额实盘申请失败')
    } finally {
      setAutoBusy('')
    }
  }, [autoRun])

  const approveAutoSmallLive = useCallback(async (approval: {
    actor: string
    maximum_capital: number
    maximum_exposure: number
    maximum_loss: number
    valid_until: string
  }) => {
    if (!autoRun?.run.selected_factor_version) return
    setAutoBusy('manual-approval')
    setError('')
    try {
      setAutoRun(await api.approveFactorFactorySmallLive(autoRun.run.id, {
        ...approval,
        symbol: String(autoRun.run.config.symbol),
        interval: autoRun.run.config.interval as '1h' | '4h' | '1d',
        factor_version: autoRun.run.selected_factor_version,
        strategy_version: 'cohort-execution-v1',
        risks_acknowledged: true,
      }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '人工审批写入失败')
    } finally {
      setAutoBusy('')
    }
  }, [autoRun])

  const autoBest = autoRun?.candidates.find(
    (item) => item.factor_key === autoRun.run.selected_factor_key,
  ) ?? autoRun?.candidates.find((item) => item.rank === 1) ?? autoRun?.candidates[0]
  const autoCandidateFamilies = useMemo(() => {
    const counts = new Map<string, { label: string; count: number }>()
    for (const candidate of autoRun?.candidates ?? []) {
      const value = candidate.definition?.family ?? 'unclassified'
      const current = counts.get(value)
      counts.set(value, { label: factorFamilyLabel(value), count: (current?.count ?? 0) + 1 })
    }
    return [...counts.entries()].map(([value, item]) => ({ value, ...item }))
  }, [autoRun])
  const visibleAutoCandidates = useMemo(() => {
    const needle = candidateQuery.trim().toLowerCase()
    return (autoRun?.candidates ?? []).filter((candidate) => {
      const family = candidate.definition?.family ?? 'unclassified'
      if (candidateFamilyFilter && family !== candidateFamilyFilter) return false
      if (!needle) return true
      const searchable = [
        candidate.definition?.label,
        candidate.factor_key,
        factorFamilyLabel(family),
        CANDIDATE_SOURCE_LABELS[candidate.source] ?? candidate.source,
        alphaAstExpression(candidate.definition?.ast),
      ].filter(Boolean).join(' ').toLowerCase()
      return searchable.includes(needle)
    })
  }, [autoRun, candidateFamilyFilter, candidateQuery])
  const selectedAutoCandidate = autoRun?.candidates.find((candidate) => candidate.id === selectedAutoCandidateId)
    ?? visibleAutoCandidates[0]
    ?? autoBest
  const selectedGateChecks = Object.entries(nestedRecord(selectedAutoCandidate?.gate, 'checks') ?? {})
    .filter((entry): entry is [string, boolean] => typeof entry[1] === 'boolean')
  const selectedPassedChecks = selectedGateChecks.filter(([, passed]) => passed)
  const selectedFailedChecks = selectedGateChecks.filter(([, passed]) => !passed)
  const selectedCandidateValidationReturn = nestedNumber(selectedAutoCandidate?.metrics, 'rolling_validation', 'summary', 'total_return')
  const selectedCandidateValidationDrawdown = nestedNumber(selectedAutoCandidate?.metrics, 'rolling_validation', 'summary', 'max_drawdown')
  const selectedCandidateValidationSharpe = nestedNumber(selectedAutoCandidate?.metrics, 'rolling_validation', 'summary', 'metrics', 'sharpe')
  const selectedCandidateValidationIc = nestedNumber(selectedAutoCandidate?.metrics, 'rolling_validation', 'summary', 'rank_ic')

  useEffect(() => {
    if (!autoRun) {
      setSelectedAutoCandidateId('')
      return
    }
    const preferred = autoRun.candidates.find((candidate) => candidate.factor_key === autoRun.run.selected_factor_key)
      ?? autoRun.candidates.find((candidate) => candidate.rank === 1)
      ?? autoRun.candidates[0]
    setSelectedAutoCandidateId(preferred?.id ?? '')
  }, [autoRun])
  const autoMessage = asString(autoRun?.run.result.message, '尚未启动自动研究')
  const autoEndsAt = autoRun?.run.observation_ends_at
    ? new Date(autoRun.run.observation_ends_at * 1000).toLocaleString('zh-CN', { hour12: false })
    : '—'
  const autoStatusVariant = autoRun?.run.status === 'trading_validated'
    ? 'up'
    : autoRun?.run.status === 'paper_observing'
      ? 'live'
      : autoRun?.run.status === 'failed' || autoRun?.run.status === 'degraded'
        ? 'down'
        : 'warn'
  const autoDemoStatus = nestedString(autoRun?.run.result, 'paper', 'okx_demo', 'latest_activation', 'status')
  const autoDemoStrategy = nestedString(autoRun?.run.result, 'paper', 'okx_demo', 'latest_activation', 'strategy_id')
  const autoDemoOrders = nestedNumber(autoRun?.run.result, 'paper', 'okx_demo', 'latest_evidence', 'order_count')
  const autoDemoFillRate = nestedNumber(autoRun?.run.result, 'paper', 'okx_demo', 'latest_evidence', 'fill_rate')
  const autoDemoFunding = nestedNumber(autoRun?.run.result, 'paper', 'okx_demo', 'latest_evidence', 'funding_rate', 'funding_rate')
  const autoPreflightAccepted = nestedNumber(autoRun?.run.result, 'candidate_preflight', 'accepted_candidates')
  const autoPreflightRejected = nestedNumber(autoRun?.run.result, 'candidate_preflight', 'rejected_candidates')
  const autoCorrelationRejected = nestedNumber(autoRun?.run.result, 'candidate_preflight', 'correlation_cluster_rejections')
  const autoFormulaDuplicates = nestedNumber(autoRun?.run.result, 'candidate_preflight', 'formula_duplicate_count')
  const autoCandidateGeneration = nestedRecord(autoRun?.run.result, 'candidate_generation')
    ?? nestedRecord(autoRun?.run.config, 'candidate_generation')
  const autoSourceCounts = nestedRecord(autoCandidateGeneration, 'source_counts')
  const autoGeneratedAi = nestedNumber(autoSourceCounts, 'ai') ?? 0
  const autoGeneratedGrammar = (nestedNumber(autoSourceCounts, 'random_dsl') ?? 0)
    + (nestedNumber(autoSourceCounts, 'symbolic_regression') ?? 0)
    + (nestedNumber(autoSourceCounts, 'template') ?? 0)
  const autoGeneratedManual = nestedNumber(autoSourceCounts, 'human') ?? 0
  const autoAiStatus = nestedString(autoCandidateGeneration, 'ai', 'status')
  const autoAiError = nestedString(autoCandidateGeneration, 'ai', 'error')
  const autoRunAiProvider = nestedString(autoCandidateGeneration, 'ai', 'requested_provider')
  const autoAcceptedAiCandidates = nestedNumber(autoCandidateGeneration, 'ai', 'candidate_count') ?? 0
  const autoAiGenerationMessage = aiGenerationMessage(autoAiStatus, autoAiError, autoRunAiProvider, autoAcceptedAiCandidates)
  const autoDirectionRadar = nestedRecord(autoRun?.run.result, 'direction_radar')
  const autoDirectionOverall = nestedRecord(autoDirectionRadar, 'overall')
  const autoDirectionLight = nestedString(autoDirectionOverall, 'light')
  const autoDirectionAction = nestedString(autoDirectionOverall, 'action')
  const autoDirectionDsi = nestedNumber(autoDirectionOverall, 'dsi')
  const autoDirectionSamples = nestedNumber(autoDirectionOverall, 'sample_count')
  const autoDirectionCeiling = nestedNumber(autoDirectionOverall, 'maximum_sharpe')
  const autoDirectionOperatorFamilies = nestedNumber(autoDirectionOverall, 'operator_family_count')
  const autoDirectionFamilies = nestedRecords(autoDirectionRadar, 'families')
  const demoRiskNormal = nestedBoolean(autoRun?.run.result, 'paper', 'okx_demo', 'latest_evidence', 'risk_mode_normal')
  const demoReconciliationClear = nestedBoolean(autoRun?.run.result, 'paper', 'okx_demo', 'latest_evidence', 'reconciliation_clear')
  const autoRunPaperTarget = nestedString(autoRun?.run.config, 'paper_target')
  const autoRunMarket = nestedString(autoRun?.run.config, 'market') ?? autoMarket
  const autoRunSymbol = nestedString(autoRun?.run.config, 'symbol') ?? autoSymbol
  const autoRunInterval = nestedString(autoRun?.run.config, 'interval') ?? autoInterval
  const autoDataBars = nestedNumber(autoRun?.run.config, 'data_provenance', 'bars')
  const autoRequestedBars = nestedNumber(autoRun?.run.config, 'data_provenance', 'requested_bars')
  const autoValidationReturn = nestedNumber(autoBest?.metrics, 'rolling_validation', 'summary', 'total_return')
  const autoValidationDrawdown = nestedNumber(autoBest?.metrics, 'rolling_validation', 'summary', 'max_drawdown')
  const autoValidationSharpe = nestedNumber(autoBest?.metrics, 'rolling_validation', 'summary', 'metrics', 'sharpe')
  const autoValidationIc = nestedNumber(autoBest?.metrics, 'rolling_validation', 'summary', 'rank_ic')
  const autoConfirmationReturn = nestedNumber(autoBest?.metrics, 'locked_confirmation', 'summary', 'total_return')
  const autoConfirmationSharpe = nestedNumber(autoBest?.metrics, 'locked_confirmation', 'summary', 'metrics', 'sharpe')
  const autoConfirmationPValue = nestedNumber(autoBest?.metrics, 'locked_confirmation', 'summary', 'raw_p_value')
  const autoParameterPlateau = nestedBoolean(autoRun?.run.result, 'confirmation_gate', 'checks', 'parameter_plateau')
  const autoRegimeStability = nestedBoolean(autoRun?.run.result, 'confirmation_gate', 'checks', 'regime_stability')
  const selectedArchive = archive.find((item) => item.archive_id === selectedArchiveId) ?? archive[0]
  const selectedPreregistration = selectedArchive?.preregistration.experiments[0]
  const selectedLatestRun = selectedArchive?.post_study_evidence.latest_run
  const selectedValidationReturn = nestedNumber(selectedLatestRun?.candidate.metrics, 'rolling_validation', 'summary', 'total_return')
  const selectedConfirmationReturn = nestedNumber(selectedLatestRun?.candidate.metrics, 'locked_confirmation', 'summary', 'total_return')
  const selectedDataHash = selectedArchive?.evidence_chain.data_snapshot_hashes[0]

  return (
    <section className={s.workflow} aria-label="因子工厂工作流">
      <header className={s.workflowHeader}>
        <div>
          <span className={s.eyebrow}>BRAIN-STYLE ALPHA LAB / OKX DEMO</span>
          <h2>AI Alpha 研究与 7 天模拟验证</h2>
          <p>AI、规则和手工候选均通过同一受控研究路径回测；通过后进入 OKX Demo 并连续记录真实前向收益。</p>
        </div>
        <div className={s.headerState}>
          <Badge variant={autoRun?.run.status === 'trading_validated' ? 'up' : 'neutral'} dot>{autoRun ? FACTORY_STATUS[autoRun.run.status] ?? autoRun.run.status : '待启动'}</Badge>
          <span>{autoMessage}</span>
          <span>实盘开关：关闭</span>
        </div>
      </header>

      <section className={s.autoPanel} aria-label="自动因子研究与模拟观察">
        <header className={s.autoHeader}>
          <div><span className={s.eyebrow}>ALPHA EXPRESSION MINER</span><h3>表达式挖掘、统一回测、前向观察</h3><p>{autoMessage}</p></div>
          <div className={s.autoHeaderActions}>
            {autoRun && <Badge variant={autoStatusVariant} dot>{FACTORY_STATUS[autoRun.run.status] ?? autoRun.run.status}</Badge>}
            <Button variant="ghost" size="sm" loading={autoBusy === 'observe' || autoBusy === 'load'} disabled={!autoRun} onClick={() => void refreshAutoObservation()} icon={<RefreshCw size={15} />}>刷新观察</Button>
          </div>
        </header>
        <div className={s.controlSurface}><div className={s.alphaBriefBar}>
          <Field label="Alpha 研究方向"><Textarea rows={2} value={autoAlphaBrief} onChange={(event) => setAutoAlphaBrief(event.target.value)} /></Field>
          <div className={s.alphaPolicy}>
            <span><ShieldCheck size={15} />仅安全 DSL AST</span>
            <span><FlaskConical size={15} />统一回测与回撤门禁</span>
            <span><TimerReset size={15} />OKX Demo 至少 7 天</span>
          </div>
        </div>
        {autoCandidateMode === 'manual' && <div className={s.manualAlphaPanel}>
          <div className={s.manualAlphaEditor}>
            <div className={s.manualPresetRow}>
              <Field label="Alpha 模板"><Select value={manualPreset} options={ALPHA_PRESET_OPTIONS} onChange={(event) => {
                const next = event.target.value as ManualAlphaPreset
                setManualPreset(next)
                setManualAlphaText(manualAlphaExpression(next, manualProfile))
              }} /></Field>
              <Field label="参数风格"><Select value={manualProfile} options={ALPHA_PROFILE_OPTIONS} onChange={(event) => {
                const next = event.target.value as ManualAlphaProfile
                setManualProfile(next)
                setManualAlphaText(manualAlphaExpression(manualPreset, next))
              }} /></Field>
            </div>
            <Field label="手工 Alpha 表达式"><Textarea rows={3} value={manualAlphaText} placeholder="mul(rolling_zscore(pct_change(close, 3), 20), rank(volume, 20))" onChange={(event) => setManualAlphaText(event.target.value)} /></Field>
            <div className={s.manualUpload}>
              <label><input type="file" accept="application/json,.json" onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void loadManualAlphaFile(file)
              }} /><FileCheck2 size={16} /><span>上传 Alpha JSON</span></label>
              <strong>{manualBatch.length} 个上传候选</strong>
              {manualBatch.length > 0 && <button type="button" onClick={() => setManualBatch([])}>清空批次</button>}
            </div>
          </div>
          <aside className={s.alphaDslGuide} aria-label="Alpha 参数手册">
            <header>
              <div><span className={s.eyebrow}>DSL REFERENCE</span><strong>字段与参数</strong></div>
              <small>{alphaDsl.version}</small>
            </header>
            <Input value={alphaDslQuery} placeholder="搜索算子，如 zscore / window" prefix={<Search size={14} />} onChange={(event) => setAlphaDslQuery(event.target.value)} />
            <div className={s.alphaDslLimits}>
              <span><b>periods</b>{alphaDsl.limits.periods_min}–{alphaDsl.limits.periods_max}</span>
              <span><b>window</b>{alphaDsl.limits.window_min}–{alphaDsl.limits.window_max}</span>
              <span><b>深度</b>≤ {alphaDsl.limits.max_depth}</span>
              <span><b>算子</b>≤ {alphaDsl.limits.max_operators}</span>
            </div>
            <div className={s.alphaDslFields}>
              {alphaDsl.fields.map((field) => <button type="button" key={field.name} title={`使用字段 ${field.name}`} onClick={() => setManualAlphaText(field.name)}>
                <code>{field.name}</code><span>{field.label}</span><small>{field.unit}</small>
              </button>)}
            </div>
            <div className={s.alphaDslParameters}>
              {alphaDsl.parameters.map((parameter) => <span key={parameter.name}><code>{parameter.name}</code><small>{parameter.description}</small></span>)}
            </div>
            <div className={s.alphaDslOperators}>
              {visibleAlphaOperators.map((operator) => <button type="button" key={operator.name} title={`使用示例：${operator.example}`} onClick={() => setManualAlphaText(operator.example)}>
                <code>{operator.signature}</code><span>{operator.description}</span>
              </button>)}
              {visibleAlphaOperators.length === 0 && <p>没有匹配算子</p>}
            </div>
          </aside>
        </div>}
        <div className={s.autoControls}>
          <Field label="研究市场"><Select value={autoMarket} options={[{ value: 'crypto', label: '虚拟货币' }, { value: 'a_shares', label: 'A 股' }]} onChange={(event) => {
            const market = event.target.value as typeof autoMarket
            setAutoMarket(market)
            if (market === 'a_shares') {
              setOkxCatalogOpen(false)
              setOkxKlineOpen(false)
              setAutoSymbol('600519')
              setAutoInstrumentTradingReady(true)
              setInstrumentQuery('600519')
              setAutoSource('akshare_live')
              setAutoInterval('1d')
              setAutoPaperTarget('simulation_orders')
              setAutoBars(720)
            } else {
              setAutoSymbol('BTC-USDT-SWAP')
              // The default symbol is a query seed, not proof of a currently
              // tradable contract.  The catalog effect below must verify it.
              setAutoInstrumentTradingReady(false)
              setInstrumentQuery('BTC-USDT-SWAP')
              setAutoSource('okx_live')
              setAutoInterval('4h')
              setAutoPaperTarget('okx_demo')
              setAutoBars(720)
              setAutoDays((current) => Math.max(7, current))
            }
          }} /></Field>
          <Field label="研究标的"><div className={s.instrumentPicker} onBlur={() => window.setTimeout(() => setInstrumentSearchOpen(false), 120)}>
            <div className={s.instrumentInputRow}>
              <Input
                value={instrumentQuery}
                placeholder={autoMarket === 'crypto' ? '代码或名称，如 AVGO / 博通' : '代码或名称，如 600519 / 贵州茅台'}
                prefix={<Search size={15} />}
                invalid={!autoSymbol && instrumentQuery.trim().length > 0}
                role="combobox"
                aria-expanded={instrumentSearchOpen}
                aria-controls="factor-instrument-options"
                onFocus={() => setInstrumentSearchOpen(true)}
                onChange={(event) => {
                  const next = event.target.value.slice(0, 64)
                  setInstrumentQuery(next)
                  setAutoSymbol(autoMarket === 'a_shares' ? normalizedDirectSymbol(next, autoMarket) : '')
                  if (autoMarket === 'crypto') setAutoInstrumentTradingReady(false)
                  setInstrumentSearchOpen(true)
                }}
              />
              <button
                type="button"
                className={activeFavorite ? s.favoriteActive : s.favoriteButton}
                disabled={!autoSymbol}
                aria-label={activeFavorite ? `取消收藏 ${autoSymbol}` : `收藏 ${autoSymbol || '当前研究标的'}`}
                title={activeFavorite ? '取消收藏' : '收藏当前标的'}
                onMouseDown={(event) => event.preventDefault()}
                onClick={toggleFavoriteInstrument}
              ><Star size={17} fill={activeFavorite ? 'currentColor' : 'none'} /></button>
            </div>
            {instrumentSearchOpen && <div id="factor-instrument-options" className={s.instrumentOptions} role="listbox">
              {marketFavorites.length > 0 && <div className={s.favoriteGroup} role="group" aria-label="收藏标的">
                <strong><Star size={13} fill="currentColor" />收藏标的</strong>
                {marketFavorites.map((item) => <button type="button" role="option" aria-selected={item.code === autoSymbol} key={`favorite:${item.market}:${item.code}`} onMouseDown={(event) => event.preventDefault()} onClick={() => selectInstrument(item)}>
                  <span><strong>{item.name || item.code}</strong><small>{item.code}</small></span>
                  <span>已收藏{item.code === autoSymbol && <Check size={14} />}</span>
                </button>)}
              </div>}
              {instrumentOptions.map((item) => <button type="button" role="option" aria-selected={item.code === autoSymbol} key={`${item.market}:${item.code}`} onMouseDown={(event) => event.preventDefault()} onClick={() => selectInstrument(item)}>
                <span><strong>{item.name || item.code}</strong><small>{item.code}</small></span>
                <span>{item.verified ? 'OKX 已验证' : '仅目录元数据'}{item.code === autoSymbol && <Check size={14} />}</span>
              </button>)}
              {!instrumentSearchBusy && instrumentOptions.length === 0 && <p>{autoMarket === 'crypto' ? 'OKX 当前目录没有匹配合约' : '没有匹配标的'}</p>}
              {instrumentSearchBusy && <p>正在搜索…</p>}
            </div>}
          </div></Field>
          <Field label="候选引擎"><Select value={autoCandidateMode} options={[{ value: 'brain', label: '模板组合 -> 回测筛选 -> AI 精炼' }, { value: 'manual', label: '手工 / JSON 批次' }, { value: 'library', label: '固定候选库' }]} onChange={(event) => setAutoCandidateMode(event.target.value as typeof autoCandidateMode)} /></Field>
          <Field label="AI 提案"><label className={s.aiToggle}><input type="checkbox" checked={autoUseAi} disabled={autoCandidateMode !== 'brain'} onChange={(event) => setAutoUseAi(event.target.checked)} /><span>{autoCandidateMode === 'manual' ? '手工批次模式' : autoCandidateMode === 'library' ? '候选库模式' : autoUseAi ? '优胜候选后精炼' : '仅规则筛选'}</span></label></Field>
          <Field label="AI 模型来源"><Select value={autoAiProvider} disabled={autoCandidateMode !== 'brain' || !autoUseAi || aiProviders.length === 0} options={aiProviders.length > 0 ? aiProviders.map((provider) => ({ value: provider.id, label: provider.label })) : [{ value: '', label: '跟随系统设置' }]} onChange={(event) => setAutoAiProvider(event.target.value as LLMProviderId)} /></Field>
          <Field label="AI 候选数"><Input type="number" min={0} max={autoBudget} disabled={autoCandidateMode !== 'brain' || !autoUseAi} value={Math.min(autoAiCount, autoBudget)} onChange={(event) => setAutoAiCount(Math.max(0, Number(event.target.value)))} /></Field>
          <Field label="模拟目标"><Select value={autoPaperTarget} options={autoMarket === 'crypto' ? [{ value: 'okx_demo', label: 'OKX Demo' }, { value: 'simulation_orders', label: '本地独立模拟' }] : [{ value: 'simulation_orders', label: '本地独立模拟' }]} onChange={(event) => {
            const target = event.target.value as typeof autoPaperTarget
            if (target === 'okx_demo' && !autoInstrumentTradingReady) {
              setAutoPaperTarget('simulation_orders')
              setError('OKX Demo 只能使用当前 OKX 公共目录已验证的合约。')
              return
            }
            setAutoPaperTarget(target)
            if (target === 'okx_demo') {
              setAutoSource('okx_live')
              setAutoInterval('4h')
              setAutoBars(720)
              setAutoDays((current) => Math.max(7, current))
            }
          }} /></Field>
          <Field label="行情通道"><Select value={autoSource} disabled={autoPaperTarget === 'okx_demo' || autoMarket === 'a_shares'} options={autoMarket === 'a_shares' ? [{ value: 'akshare_live', label: 'AkShare 实时行情' }] : [{ value: 'okx_local', label: 'OKX 本地归档（研究专用，不可执行）' }, { value: 'okx_live', label: 'OKX 实时公共行情' }, { value: 'synthetic', label: '确定性合成（研究专用，不可执行）' }]} onChange={(event) => {
            const source = event.target.value as FactorFactorySource
            setAutoSource(source)
            if (isResearchOnlySource(source)) setAutoPaperTarget('simulation_orders')
          }} /></Field>
          <Field label="研究周期"><Select value={autoInterval} options={autoMarket === 'a_shares' ? [{ value: '1d', label: '日线' }, { value: '1h', label: '1 小时' }] : [{ value: '1h', label: '1 小时' }, { value: '4h', label: '4 小时' }]} onChange={(event) => {
            const nextInterval = event.target.value as typeof autoInterval
            setAutoInterval(nextInterval)
            setAutoBars(nextInterval === '1h' && autoMarket === 'crypto' ? 2880 : 720)
          }} /></Field>
          <Field label="预测持有期"><Input type="number" min={1} max={60} value={autoHorizon} onChange={(event) => setAutoHorizon(Math.min(60, Math.max(1, Number(event.target.value))))} /></Field>
          <Field label="历史样本"><Input type="number" min={240} max={5000} value={autoBars} onChange={(event) => setAutoBars(Number(event.target.value))} /></Field>
          <Field label="候选预算"><Input type="number" min={1} max={30} value={autoBudget} onChange={(event) => setAutoBudget(Number(event.target.value))} /></Field>
          <Field label="观察天数"><Input type="number" min={7} max={365} value={autoDays} onChange={(event) => setAutoDays(Math.max(7, Number(event.target.value)))} /></Field>
          <Button variant="primary" loading={autoBusy === 'start'} disabled={!autoResearchReady} onClick={() => void startAutoResearch()} icon={<ScanSearch size={16} />}>{autoRun ? '启动新实验' : '启动自动研究'}</Button>
        </div></div>
        {autoMarket === 'crypto' && <div className={s.marketDataBar}>
          <span className={autoSymbol && autoInstrumentTradingReady ? s.marketVerified : s.marketUnverified}>
            {autoSymbol && autoInstrumentTradingReady ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}
            <strong>{autoSymbol || '尚未选择已验证合约'}</strong>
            <small>{autoSymbol ? autoInstrumentTradingReady ? 'OKX 公共目录已验证，可使用实时行情' : isResearchOnlySource(autoSource) ? '已显式选择研究专用通道，只能进入本地独立模拟' : '公共目录缓存或未验证元数据；请选择已验证合约，或显式选择研究专用通道' : '输入代码后从目录结果中选择'}</small>
          </span>
          <div>
            <button type="button" onClick={() => setOkxCatalogOpen((current) => !current)}><ListFilter size={15} />合约目录</button>
            <button type="button" disabled={!autoSymbol || !autoInstrumentTradingReady} onClick={() => setOkxKlineOpen((current) => !current)}><CandlestickChart size={15} />实时 K 线</button>
          </div>
        </div>}
        {autoMarket === 'crypto' && okxCatalogOpen && <section className={s.okxCatalog} aria-label="OKX 永续合约目录">
          <header>
            <div><span className={s.eyebrow}>OKX INSTRUMENT RESEARCH CATALOG</span><h4>{okxCatalog?.source === 'okx_public' ? '当前可交易 USDT 永续' : 'OKX 公共目录缓存元数据'}</h4><p>{okxCatalog?.source === 'okx_public' ? '代码、中文关键词和基础币均可搜索；结果来自 OKX 公共市场目录。' : '公共目录不可用时仅保留同端点公共目录缓存用于搜索；缓存不能证明可交易，也不会自动切换到本地归档。'}</p></div>
            <div className={s.okxCatalogActions}>
              <button type="button" aria-label="刷新 OKX 合约目录" title="强制刷新 OKX 合约目录" onClick={() => void loadOkxCatalog(true)}><RefreshCw size={15} /></button>
              <button type="button" aria-label="关闭 OKX 合约目录" title="关闭" onClick={() => setOkxCatalogOpen(false)}><X size={16} /></button>
            </div>
          </header>
          <div className={s.okxCatalogSearch}>
            <Input value={okxCatalogQuery} placeholder="搜索代码或名称，如 BTC、黄金、石油、博通" prefix={<Search size={15} />} onChange={(event) => setOkxCatalogQuery(event.target.value.slice(0, 64))} />
            <span><b>{okxCatalog?.count ?? 0}</b> 个匹配 / {okxCatalog?.total ?? 0} 个合约</span>
            <small>{okxCatalog?.source === 'okx_public' ? `实时目录 · ${okxCatalog.trading_ready_count ?? okxCatalog.instruments.filter(okxTradingReady).length} 个可交易` : okxCatalog?.source === 'okx_public_cache' ? '公共目录缓存 · 仅元数据' : '等待公共目录'}</small>
          </div>
          {okxCatalogError && <div className={s.okxCatalogError}><CircleAlert size={15} />{okxCatalogError}</div>}
          {okxCatalog?.degraded && <div className={s.okxCatalogWarning}><CircleAlert size={15} /><span>{okxCatalog.warning || 'OKX 公共目录暂不可用，当前展示的是公共目录缓存元数据。'} 当前列表不可作为实时可交易证明。</span></div>}
          <div className={s.okxContractList}>
            {okxCatalog?.instruments.map((item: OkxSwapInstrument) => {
              const tradingReady = okxCatalogTradingReady(okxCatalog.source, item)
              return <button type="button" key={item.code} className={item.code === autoSymbol ? s.okxContractActive : s.okxContract} onClick={() => {
              setAutoSymbol(item.code)
              setAutoInstrumentTradingReady(tradingReady)
              setInstrumentQuery(item.code)
              setAutoSource('okx_live')
              setAutoPaperTarget(tradingReady ? 'okx_demo' : 'simulation_orders')
              if (!tradingReady) {
                const intervals = okxAvailableIntervals(item)
                const available = intervals.includes('4h') ? '4h' : intervals.includes('1h') ? '1h' : intervals.includes('1d') ? '1d' : autoInterval
                setAutoInterval(available)
              }
              setOkxCatalogOpen(false)
              setOkxKlineOpen(tradingReady)
            }}>
              <span><strong>{item.name || item.code}</strong><code>{item.code}</code></span>
              <span><small>面值</small><b>{num(item.contract_size, 6)}</b></span>
              <span><small>价格精度</small><b>{item.price_precision ?? '—'}</b></span>
              <span><small>最小数量</small><b>{item.minimum_amount ?? '—'}</b></span>
              <span className={tradingReady ? s.contractTrading : s.contractResearch}>{tradingReady ? '当前可交易' : '仅研究'}</span>
            </button>
            })}
            {!okxCatalogBusy && okxCatalog?.ok && okxCatalog.instruments.length === 0 && <p>OKX 当前目录没有匹配合约。</p>}
            {okxCatalogBusy && <p>正在读取 OKX 公共合约目录…</p>}
          </div>
        </section>}
        {autoMarket === 'crypto' && okxKlineOpen && autoSymbol && <section className={s.okxKlinePanel} aria-label="OKX 实时公共 K 线">
          <header><div><span className={s.eyebrow}>LIVE PUBLIC OHLCV</span><h4>{autoSymbol} 实时 K 线</h4></div><button type="button" aria-label="关闭实时 K 线" title="关闭" onClick={() => setOkxKlineOpen(false)}><X size={16} /></button></header>
          <KlineCard key={`${autoSymbol}:${autoInterval}`} symbol={autoSymbol} market="crypto" defaultPeriod={autoInterval === '4h' ? '4H' : '1H'} showInstrumentControls={false} />
        </section>}
        {autoRun && <>
          <div className={s.resultTabs}>
            <SegmentedControl value={autoView} onChange={(value) => setAutoView(value as 'candidates' | 'cohort')} options={[{ value: 'candidates', label: '候选研究' }, { value: 'cohort', label: '同期评估' }]} size="sm" />
            <span>{autoView === 'cohort' ? '基准池、独立账本与准入门禁' : '候选排序、研究门禁与前向观察'}</span>
          </div>
          {autoView === 'cohort' ? <FactorCohortPanel run={autoRun} busy={autoBusy} onReview={reviewAutoCohort} onRequest={requestAutoSmallLive} onApprove={approveAutoSmallLive} /> : <>
          <div className={s.researchContextBar}>
            <span><small>研究标的</small><strong>{autoRunSymbol}</strong></span>
            <span><small>市场 / 周期</small><strong>{autoRunMarket} / {autoRunInterval}</strong></span>
            <span><small>相似预检淘汰</small><strong>{autoPreflightRejected ?? 0}（公式 {autoFormulaDuplicates ?? 0} / 信号 {autoCorrelationRejected ?? 0}）</strong></span>
            <span><small>下一轮规则</small><strong>仅排名最高且门禁通过的 1 个</strong></span>
          </div>
          <div className={s.autoKpis}>
            <div><small>AI / 规则 / 手工</small><strong>{autoGeneratedAi} / {autoGeneratedGrammar} / {autoGeneratedManual}</strong></div>
            <div><small>预检 / 生成状态</small><strong>{autoPreflightAccepted ?? '—'} / {autoAiStatus ?? nestedString(autoRun.run.config, 'candidate_mode') ?? '—'}</strong></div>
            <div><small>当前优胜因子</small><strong title={autoRun.run.selected_factor_key ?? ''}>{autoRun.run.selected_factor_key ?? '无通过因子'}</strong></div>
            <div><small>模拟累计收益</small><strong className={(autoRun.observation_summary.after_cost_return ?? 0) >= 0 ? s.up : s.down}>{pct(autoRun.observation_summary.after_cost_return)}</strong></div>
            <div><small>模拟最大回撤</small><strong>{pct(autoRun.observation_summary.max_drawdown)}</strong></div>
            <div><small>观察 / 成交</small><strong>{autoRun.observation_summary.count} / {autoRun.simulation_orders.length}</strong></div>
            <div><small>观察截止</small><strong>{autoEndsAt}</strong></div>
          </div>
          {autoAiGenerationMessage && <div className={s.aiGenerationWarning} role="status"><CircleAlert size={16} /><span>{autoAiGenerationMessage}</span><code title={autoAiError ?? ''}>{autoAiStatus}</code></div>}
          {autoDirectionLight && <section className={s.directionRadar} aria-label="方向雷达">
            <div className={s.directionRadarSummary}>
              <span className={s[`direction${autoDirectionLight}`]}>{DIRECTION_LIGHT_LABELS[autoDirectionLight] ?? autoDirectionLight}</span>
              <span><small>DSI</small><strong>{num(autoDirectionDsi, 3)}</strong></span>
              <span><small>样本</small><strong>{autoDirectionSamples ?? '—'}</strong></span>
              <span><small>最高 Sharpe</small><strong>{num(autoDirectionCeiling)}</strong></span>
              <span><small>算子族</small><strong>{autoDirectionOperatorFamilies ?? '—'} / 6</strong></span>
              <p>{autoDirectionAction}</p>
            </div>
            {autoDirectionFamilies.length > 0 && <div className={s.directionFamilyRail}>
              {autoDirectionFamilies.slice(0, 12).map((family) => {
                const light = nestedString(family, 'light') ?? 'YELLOW'
                const name = nestedString(family, 'name') ?? '未分类'
                const dsi = nestedNumber(family, 'dsi')
                return <span key={name} className={s[`direction${light}`]} title={nestedString(family, 'action') ?? ''}><b>{factorFamilyLabel(name)}</b><small>{light} · {num(dsi, 2)}</small></span>
              })}
            </div>}
          </section>}
          {autoRunPaperTarget === 'okx_demo' && <div className={s.demoStatusBar}>
            <span><small>Demo 状态</small><strong>{autoDemoStatus ?? (autoRun ? '等待研究通过' : '未启动')}</strong></span>
            <span><small>Runner 策略</small><strong title={autoDemoStrategy ?? ''}>{autoDemoStrategy ?? '—'}</strong></span>
            <span><small>订单 / 成交率</small><strong>{autoDemoOrders === null ? '—' : `${autoDemoOrders} / ${pct(autoDemoFillRate)}`}</strong></span>
            <span><small>资金费率</small><strong>{autoDemoFunding === null ? '—' : pct(autoDemoFunding, 4)}</strong></span>
            <span><small>风险 / 对账</small><strong>{gateState(demoRiskNormal)} / {gateState(demoReconciliationClear)}</strong></span>
          </div>}
          {autoBest && <div className={s.researchEvidenceBar}>
            <span><small>滚动收益 / 回撤</small><strong>{pct(autoValidationReturn)} / {pct(autoValidationDrawdown)}</strong></span>
            <span><small>滚动夏普 / IC</small><strong>{num(autoValidationSharpe)} / {num(autoValidationIc, 3)}</strong></span>
            <span><small>确认收益 / 夏普</small><strong>{pct(autoConfirmationReturn)} / {num(autoConfirmationSharpe)}</strong></span>
            <span><small>确认 p 值</small><strong>{num(autoConfirmationPValue, 4)}</strong></span>
            <span><small>参数平台</small><strong>{gateState(autoParameterPlateau)}</strong></span>
            <span><small>状态稳定</small><strong>{gateState(autoRegimeStability)}</strong></span>
          </div>}
          <div className={s.autoBody}>
            <div className={s.candidateTable}>
              <div className={s.candidateToolbar}>
                <Input value={candidateQuery} placeholder="搜索名称、家族或 DSL" onChange={(event) => setCandidateQuery(event.target.value)} />
                <Select value={candidateFamilyFilter} options={[{ value: '', label: '全部因子家族' }, ...autoCandidateFamilies.map((family) => ({ value: family.value, label: `${family.label} (${family.count})` }))]} onChange={(event) => setCandidateFamilyFilter(event.target.value)} />
                <strong>{visibleAutoCandidates.length} / {autoRun.candidates.length}</strong>
              </div>
              {autoCandidateFamilies.length > 0 && <div className={s.candidateFamilyBar}><strong>因子家族</strong>{autoCandidateFamilies.map((family) => <span key={family.value}>{family.label} {family.count}</span>)}</div>}
              <div className={s.candidateHead}><span>排名</span><span>候选因子</span><span>滚动收益</span><span>夏普</span><span>阶段</span></div>
              {visibleAutoCandidates.map((candidate) => {
                const validationReturn = nestedNumber(candidate.metrics, 'rolling_validation', 'summary', 'total_return')
                const sharpe = nestedNumber(candidate.metrics, 'rolling_validation', 'summary', 'metrics', 'sharpe')
                const expression = alphaAstExpression(candidate.definition?.ast)
                const stageLabel = candidateStageLabel(candidate, autoRun.run)
                return <button type="button" className={s.candidateRow} aria-selected={candidate.id === selectedAutoCandidate?.id} key={candidate.id} onClick={() => setSelectedAutoCandidateId(candidate.id)}><span>{candidate.rank ?? '—'}</span><span className={s.candidateIdentity}><span><strong>{candidate.definition?.label ?? candidate.factor_key}</strong><em>{factorFamilyLabel(candidate.definition?.family)}</em></span><code title={expression}>{expression}</code><small>{CANDIDATE_SOURCE_LABELS[candidate.source] ?? candidate.source} · {candidate.factor_key}</small></span><span className={(validationReturn ?? 0) >= 0 ? s.up : s.down}>{pct(validationReturn)}</span><span>{num(sharpe)}</span><span><Badge variant={stageLabel.includes('通过') ? 'up' : stageLabel.includes('淘汰') || stageLabel.includes('无效') ? 'down' : 'info'}>{stageLabel}</Badge></span></button>
              })}
              {visibleAutoCandidates.length === 0 && <p className={s.candidateEmpty}>没有匹配候选。</p>}
            </div>
            <div className={s.researchSideRail}>
              {selectedAutoCandidate && <section className={s.candidateInspector} aria-label="Alpha 详情">
                <header><div><span>ALPHA DETAIL · {autoRunSymbol}</span><h4>{selectedAutoCandidate.definition?.label ?? selectedAutoCandidate.factor_key}</h4></div><Badge variant={candidateStageLabel(selectedAutoCandidate, autoRun.run).includes('通过') ? 'up' : candidateStageLabel(selectedAutoCandidate, autoRun.run).includes('淘汰') || candidateStageLabel(selectedAutoCandidate, autoRun.run).includes('无效') ? 'down' : 'info'}>{candidateStageLabel(selectedAutoCandidate, autoRun.run)}</Badge></header>
                <div className={s.candidateCode}><small>DSL CODE</small><code>{alphaAstExpression(selectedAutoCandidate.definition?.ast)}</code></div>
                <div className={s.alphaSummary} aria-label="Alpha 指标摘要">
                  <div><small>滚动收益</small><strong className={(selectedCandidateValidationReturn ?? 0) >= 0 ? s.up : s.down}>{pct(selectedCandidateValidationReturn)}</strong></div>
                  <div><small>夏普</small><strong>{num(selectedCandidateValidationSharpe)}</strong></div>
                  <div><small>最大回撤</small><strong>{pct(selectedCandidateValidationDrawdown)}</strong></div>
                  <div><small>Rank IC</small><strong>{num(selectedCandidateValidationIc, 3)}</strong></div>
                </div>
                <section className={s.alphaCurvePanel} aria-label="真实前向收益曲线">
                  <header><strong>前向权益</strong><span>{autoRun.observations.length} 个真实观察点</span></header>
                  <ObservationCurve observations={autoRun.observations} />
                </section>
                <section className={s.alphaTesting} aria-label="Alpha 测试状态">
                  <header><strong>测试状态</strong><span className={selectedFailedChecks.length > 0 ? s.down : s.up}>{selectedPassedChecks.length} 通过 · {selectedFailedChecks.length} 未通过</span></header>
                  <div className={s.alphaCoverage}>
                    <span>样本覆盖</span>
                    <strong>{autoDataBars ?? '—'} / {autoRequestedBars ?? '—'} 根</strong>
                    <Badge variant={autoDataBars !== null && autoRequestedBars !== null && autoDataBars < autoRequestedBars ? 'warn' : 'neutral'}>{autoDataBars !== null && autoRequestedBars !== null && autoDataBars < autoRequestedBars ? '部分样本' : '完整/未知'}</Badge>
                  </div>
                  {selectedGateChecks.length > 0 ? <div className={s.alphaCheckList}>
                    {selectedGateChecks.map(([key, passed]) => <span className={passed ? s.alphaCheckPass : s.alphaCheckFail} key={key}>{passed ? <Check size={13} /> : <X size={13} />}<b>{RESEARCH_CHECK_LABELS[key] ?? key.replace(/_/g, ' ')}</b></span>)}
                  </div> : nestedString(selectedAutoCandidate.gate, 'reason') ? <p>预检淘汰：{nestedString(selectedAutoCandidate.gate, 'reason') === 'formula_duplicate' ? '公式完全重复' : '发现集信号高度相似'}；保留 {nestedString(selectedAutoCandidate.gate, 'kept_candidate') ?? '更早候选'}。</p> : <p>该候选没有可展示的门禁明细。</p>}
                </section>
                <dl>
                  <div><dt>因子家族</dt><dd>{factorFamilyLabel(selectedAutoCandidate.definition?.family)}</dd></div>
                  <div><dt>生成来源</dt><dd>{CANDIDATE_SOURCE_LABELS[selectedAutoCandidate.source] ?? selectedAutoCandidate.source}</dd></div>
                  <div><dt>输入字段</dt><dd>{selectedAutoCandidate.definition?.input_fields?.join(' · ') || '—'}</dd></div>
                  <div><dt>预测周期</dt><dd>{selectedAutoCandidate.definition?.horizon ?? '—'}</dd></div>
                  <div><dt>滚动收益</dt><dd>{pct(selectedCandidateValidationReturn)}</dd></div>
                  <div><dt>滚动夏普</dt><dd>{num(selectedCandidateValidationSharpe)}</dd></div>
                  <div><dt>公式哈希</dt><dd title={selectedAutoCandidate.definition?.formula_hash}>{selectedAutoCandidate.definition?.formula_hash?.slice(0, 12) ?? '—'}</dd></div>
                  <div><dt>实验编号</dt><dd title={selectedAutoCandidate.experiment_id ?? ''}>{selectedAutoCandidate.experiment_id?.slice(0, 12) ?? '—'}</dd></div>
                </dl>
              </section>}
              <div className={s.observationRail}>
                <div className={s.observationTitle}><TimerReset size={16} /><span>收益记录</span></div>
                {autoRun.observations.length === 0 ? <p>尚未进入模拟观察。</p> : autoRun.observations.slice(-6).reverse().map((item) => {
                  const simulationOrderId = nestedString(item.payload, 'simulation_order', 'simulation_order_id')
                  return <div key={item.id}><span>{new Date(item.market_time).toLocaleString('zh-CN', { hour12: false })}</span><strong className={item.net_return >= 0 ? s.up : s.down}>{pct(item.net_return, 3)}</strong><small>权益 {num(item.equity, 0)} · 仓位 {pct(item.position_weight, 1)}{simulationOrderId ? ` · ${simulationOrderId}` : ' · 无调仓'}</small></div>
                })}
              </div>
            </div>
          </div>
          <footer className={s.autoAudit}><span>运行 {autoRun.run.id.slice(0, 12)}</span><span>计划 {autoRun.run.research_plan_id}</span><span>样本 {autoDataBars ?? '—'} / 请求 {autoRequestedBars ?? '—'}</span><span>实盘开关关闭</span>{autoBest && <span>首位 {autoBest.definition?.label ?? autoBest.factor_key}</span>}{autoRun.simulation_orders.length > 0 && <Link to={`/simulation?q=${encodeURIComponent(`factor-factory:${autoRun.run.id}`)}`}>查看模拟订单</Link>}</footer>
          </>}
        </>}
      </section>

      <section className={s.archiveSection} aria-label="因子证据档案">
        <header>
          <div><span className={s.eyebrow}>ADMITTED FACTOR LEDGER</span><h3>可选因子档案</h3><p>只收录完成至少 7 个真实自然日模拟，并通过收益、回撤、执行、风险、资金费率和对账门禁的因子。</p></div>
          <div className={s.archiveActions}>
            {archiveOpen ? <Select aria-label="档案状态" value={archiveFilter} options={[
              { value: '', label: '全部状态' },
              { value: 'trading_validated', label: '模拟验证通过' },
              { value: 'degraded', label: '已降级' },
              { value: 'retired', label: '已退役' },
            ]} onChange={(event) => setArchiveFilter(event.target.value as '' | FactorLifecycleState)} /> : null}
            {archiveOpen ? <Button variant="ghost" size="sm" loading={busy === 'refresh'} onClick={() => void loadArchive()} icon={<RefreshCw size={15} />}>刷新档案</Button> : null}
            <Button variant="secondary" size="sm" onClick={() => setArchiveOpen((open) => !open)}>{archiveOpen ? '收起档案' : '查看档案'}</Button>
          </div>
        </header>
        {archiveOpen ? <><div className={s.archiveSummary}>
          <span><small>已准入档案</small><strong>{archiveMeta.admitted}</strong></span>
          <span><small>研究记录</small><strong>{archiveMeta.research}</strong></span>
          <span><small>尚未准入</small><strong>{archiveMeta.excluded}</strong></span>
          <span><small>当前筛选</small><strong>{archive.length}</strong></span>
        </div>
        {archive.length === 0 ? <p className={s.empty}>目前没有因子完成七日模拟准入。</p> : <div className={s.archiveWorkspace}>
          <div className={s.archiveLedger}>
            <div className={s.archiveLedgerHead}><span>因子 / 版本</span><span>范围</span><span>状态</span><span>最近运行</span></div>
            {archive.map((item) => {
              const latest = item.post_study_evidence.latest_run
              const state = item.lifecycle.current_state
              return <button type="button" key={item.archive_id} className={item.archive_id === selectedArchive?.archive_id ? s.archiveLedgerActive : s.archiveLedgerRow} onClick={() => setSelectedArchiveId(item.archive_id)} aria-pressed={item.archive_id === selectedArchive?.archive_id}>
                <span><strong>{item.definition.label}</strong><small>{item.definition.key}@{item.definition.version}</small></span>
                <span>{item.scope.symbol ?? item.scope.market}<small>{item.scope.interval ?? '—'} · {item.scope.data_source ?? '未关联行情'}</small></span>
                <span><Badge variant={state === 'trading_validated' ? 'up' : state === 'degraded' || state === 'retired' ? 'down' : 'neutral'}>{LIFECYCLE_STATUS[state]}</Badge></span>
                <span>{latest ? FACTORY_STATUS[latest.status] ?? latest.status : '仅定义'}<small>{latest ? timeLabel(latest.updated_at) : timeLabel(item.definition.created_at)}</small></span>
              </button>
            })}
          </div>
          {selectedArchive && <aside className={s.archiveDetail} aria-label={`${selectedArchive.definition.label}证据详情`}>
            <header className={s.archiveDetailHeader}>
              <div><span className={s.eyebrow}>IMMUTABLE FACTOR RECORD</span><h4>{selectedArchive.definition.label}</h4><p>{selectedArchive.definition.key}@{selectedArchive.definition.version}</p></div>
              <Badge variant={selectedArchive.verified ? 'up' : 'neutral'} dot>{LIFECYCLE_STATUS[selectedArchive.lifecycle.current_state]}</Badge>
            </header>
            <div className={s.archiveHashRail}>
              <span title={selectedArchive.definition.formula_hash}><small>公式哈希</small><code>{selectedArchive.definition.formula_hash.slice(0, 16)}…</code></span>
              <span title={selectedArchive.definition.definition_hash}><small>定义哈希</small><code>{selectedArchive.definition.definition_hash.slice(0, 16)}…</code></span>
              <span title={selectedDataHash ?? ''}><small>数据快照</small><code>{selectedDataHash ? `${selectedDataHash.slice(0, 16)}…` : '—'}</code></span>
            </div>
            <div className={s.archiveKpis}>
              <span><small>滚动验证收益</small><strong className={(selectedValidationReturn ?? 0) >= 0 ? s.up : s.down}>{pct(selectedValidationReturn)}</strong></span>
              <span><small>锁定确认收益</small><strong className={(selectedConfirmationReturn ?? 0) >= 0 ? s.up : s.down}>{pct(selectedConfirmationReturn)}</strong></span>
              <span><small>模拟成本后收益</small><strong className={(selectedLatestRun?.observation_summary.after_cost_return ?? 0) >= 0 ? s.up : s.down}>{pct(selectedLatestRun?.observation_summary.after_cost_return)}</strong></span>
              <span><small>真实观察天数</small><strong>{num(selectedArchive.archive_gate.observed_days, 2)}</strong></span>
            </div>
            <div className={s.archiveEvidenceColumns}>
              <section className={s.archiveEvidencePane}>
                <h5><BookOpenCheck size={16} />事前假设</h5>
                <dl>
                  <div><dt>原始假设</dt><dd>{selectedPreregistration?.hypothesis ?? selectedArchive.preregistration.definition_hypothesis}</dd></div>
                  <div><dt>失效条件</dt><dd>{selectedPreregistration?.proposal.invalidation_conditions.join('；') || selectedArchive.preregistration.invalidation_condition || '未单独声明'}</dd></div>
                  <div><dt>主指标</dt><dd>{selectedPreregistration?.pre_registration.primary_metric ?? '—'}</dd></div>
                  <div><dt>通过门槛</dt><dd>{archiveCriteria(selectedPreregistration?.pre_registration.pass_criteria)}</dd></div>
                  <div><dt>数据窗口</dt><dd>{selectedPreregistration ? `${selectedPreregistration.data_window.start ?? '—'} → ${selectedPreregistration.data_window.end ?? '—'}` : '—'}</dd></div>
                  <div><dt>候选预算</dt><dd>{selectedPreregistration?.pre_registration.maximum_candidates ?? '—'}</dd></div>
                </dl>
              </section>
              <section className={s.archiveEvidencePane}>
                <h5><FileCheck2 size={16} />事后证据</h5>
                <dl>
                  <div><dt>当前结论</dt><dd>{LIFECYCLE_STATUS[selectedArchive.lifecycle.current_state]}</dd></div>
                  <div><dt>决策规则</dt><dd>{selectedArchive.post_study_evidence.decision.rule}</dd></div>
                  <div><dt>研究运行</dt><dd>{selectedLatestRun?.run_id ?? '—'}</dd></div>
                  <div><dt>确认 p 值</dt><dd>{num(nestedNumber(selectedLatestRun?.candidate.metrics, 'locked_confirmation', 'summary', 'raw_p_value'), 4)}</dd></div>
                  <div><dt>最大模拟回撤</dt><dd>{pct(selectedLatestRun?.observation_summary.maximum_drawdown)}</dd></div>
                  <div><dt>账本更新时间</dt><dd>{timeLabel(selectedLatestRun?.updated_at ?? selectedArchive.post_study_evidence.decision.created_at)}</dd></div>
                </dl>
              </section>
            </div>
            <section className={s.archiveRisks}>
              <h5><ShieldAlert size={16} />剩余风险</h5>
              {selectedArchive.remaining_risks.length === 0 ? <span className={s.riskClear}><Check size={14} />已通过当前预注册门禁</span> : <div>{selectedArchive.remaining_risks.map((risk) => <span key={risk}>{archiveRiskLabel(risk)}</span>)}</div>}
            </section>
            <footer className={s.archiveChain}>
              <span><Link2 size={14} />生命周期 {selectedArchive.evidence_chain.lifecycle_event_ids.length}</span>
              <span>实验 {selectedArchive.evidence_chain.experiment_ids.length}</span>
              <span>运行 {selectedArchive.evidence_chain.run_ids.length}</span>
              <span>订单 {selectedArchive.evidence_chain.simulation_order_ids.length}</span>
              <code title={selectedArchive.archive_id}>{selectedArchive.archive_id.slice(0, 16)}…</code>
            </footer>
          </aside>}
        </div>}</> : null}
      </section>
      {error && <div className={s.error} role="alert"><CircleAlert size={17} />{error}</div>}
    </section>
  )
}

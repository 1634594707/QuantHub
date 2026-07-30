import { useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Gauge,
  Info,
  Play,
  ScanLine,
  ShieldAlert,
  ShieldCheck,
  Waves,
} from 'lucide-react'
import { api } from '../api/client'
import type {
  DrawdownLevel,
  FactorCurvePoint,
  FactorEvaluation,
  FactorResearchResp,
  FactorStatus,
} from '../api/types'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { Button } from '../components/ui/Button/Button'
import { EmptyState } from '../components/ui/EmptyState/EmptyState'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
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

export default function FactorResearchPage() {
  const [form, setForm] = useState({
    market: 'a_shares', symbol: '600519', interval: '1d', limit: 500, horizon: 5, transaction_cost_bps: 10,
  })
  const [result, setResult] = useState<FactorResearchResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function analyze(event: React.FormEvent) {
    event.preventDefault()
    if (!form.symbol.trim()) return
    setLoading(true)
    setError('')
    try {
      const response = await api.factorResearch({ ...form, symbol: form.symbol.trim().toUpperCase() })
      if (!response.ok) throw new Error(response.error || '因子验证失败')
      setResult(response)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '因子验证失败')
    } finally {
      setLoading(false)
    }
  }

  const signal = result?.current_signal
  const SignalIcon = signal ? LEVEL_ICON[signal.level] : Activity
  const selectedNames = result?.summary.selected_factors
    .map((key) => result.factors.find((factor) => factor.key === key)?.label || key)
    .join(' + ') || '—'
  const multifactorMethod = result?.methods.find((method) => method.key === 'multifactor')

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

      <form className={s.toolbar} onSubmit={analyze}>
        <label><span>市场</span><Select value={form.market} options={MARKETS} onChange={(event) => setForm({ ...form, market: event.target.value })} /></label>
        <label><span>标的</span><Input variant="mono" value={form.symbol} onChange={(event) => setForm({ ...form, symbol: event.target.value })} placeholder="600519 / AAPL" /></label>
        <label><span>周期</span><Select value={form.interval} options={INTERVALS} onChange={(event) => setForm({ ...form, interval: event.target.value })} /></label>
        <label><span>预测窗口</span><Select value={String(form.horizon)} options={HORIZONS} onChange={(event) => setForm({ ...form, horizon: Number(event.target.value) })} /></label>
        <label><span>历史长度</span><Input type="number" min={120} max={5000} step={20} value={form.limit} suffix="根" onChange={(event) => setForm({ ...form, limit: Number(event.target.value) })} /></label>
        <label><span>单边成本</span><Input type="number" min={0} max={200} value={form.transaction_cost_bps} suffix="bp" onChange={(event) => setForm({ ...form, transaction_cost_bps: Number(event.target.value) })} /></label>
        <Button type="submit" variant="primary" loading={loading} icon={<Play size={16} />}>运行研究</Button>
      </form>

      {error && <div className={s.error} role="alert"><AlertTriangle size={17} /><span>{error}</span></div>}

      {!result ? (
        <EmptyState
          title="选择标的并验证因子"
          desc="系统将读取真实历史 K 线，比较六类因子与六种量化方法，并给出当前回撤动作。"
          icon={<Waves size={30} />}
        />
      ) : (
        <div className={s.results}>
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
      )}
    </div>
  )
}
